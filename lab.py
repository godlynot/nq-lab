#!/usr/bin/env python3
"""
NQ lab: score a trading strategy on Nasdaq-100 hourly bars, the way the judge will.

    python lab.py --selftest                      check this environment first
    python lab.py my_strategy.py                  score one strategy on nq_2022.csv
    python lab.py submissions/                    score every .py file in a folder
    python lab.py my_strategy.py --json           the same, as one JSON line

A strategy is one .py file that defines

    def positions(df) -> pandas.Series or numpy array

returning, for every bar, -1 (short), 0 (flat) or +1 (long). df has a UTC
DatetimeIndex and the columns open, high, low, close, volume, server_day. The
position at bar i may use bars 0..i only; it is held from bar i's close to bar
i+1's close. Only numpy, pandas and math may be imported (see BRIEF.md).

Costs are FundedNext's (Stellar 2-Step, NDX100, read 2026-10-15): spread 0.01%
of the position a side (deliberately above the ~0.5 bp quoted), swap for every
rollover held through (long 1.22 bp, short 0.19 bp of the position a night,
Friday's counted three times).

The score that matters is `z`: the strategy's mean net return per trade against
200 random-timing twins -- the same trades, same direction and same holding
time, entered at random bars. Beating that is beating luck plus market drift.
Needs only Python 3.8+, numpy and pandas.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import math
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "nq_2022.csv")
SIDE = 0.0001                                   # spread, a fraction of the position, a side
SWAP_LONG = 37.2912 / (10 * 30550.8)            # 1.2206e-4 a night: -372.912 pts/lot x 0.1 $/pt / $305,508
SWAP_SHORT = 5.76 / (10 * 30550.8)              # 1.885e-5 a night
TWINS = 200
CUTS = 12                                       # lookahead check: re-runs on cut-off data
MAX_BYTES = 20000
ALLOWED_IMPORTS = {"numpy", "pandas", "math", "typing", "__future__"}
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars",
                   "getattr", "setattr", "delattr", "input", "breakpoint", "help", "exit", "quit",
                   "memoryview", "__builtins__"}
FORBIDDEN_ATTRS = {"read_csv", "read_parquet", "read_pickle", "read_json", "read_excel", "read_sql",
                   "read_table", "read_html", "read_hdf", "read_feather", "read_fwf", "read_clipboard",
                   "read_xml", "read_orc", "read_sas", "read_spss", "read_stata", "to_csv", "to_parquet",
                   "to_pickle", "to_json", "to_excel", "to_sql", "to_hdf", "to_feather", "to_clipboard",
                   "to_html", "to_latex", "to_markdown", "to_xml", "to_stata", "to_orc", "load", "loadtxt",
                   "genfromtxt", "fromfile", "tofile", "save", "savez", "savez_compressed", "savetxt",
                   "memmap", "system", "popen", "DataSource", "eval", "query", "lib", "ctypeslib", "io",
                   "f2py", "distutils", "testing", "os", "sys", "subprocess", "builtins", "importlib",
                   "pipe", "apply_along_axis", "ExcelWriter", "ExcelFile", "HDFStore", "api", "util",
                   "core", "compat", "plotting", "options", "set_option", "show_versions"}
ALLOWED_SUBMODULES = {"numpy.lib.stride_tricks"}         # for sliding_window_view


# ---- data -------------------------------------------------------------------
def load(path: str = DATA) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.index = pd.DatetimeIndex(pd.to_datetime(d.pop("time"), utc=True), name="time")
    for c in ("open", "high", "low", "close", "volume"):
        d[c] = d[c].astype(float)
    d["server_day"] = d["server_day"].astype(str)
    return d


def rollover_units(server_day) -> np.ndarray:
    """units[i] = swap nights charged for holding from bar i to bar i+1 (the
    last entry is 0): 1 when the server day turns, 3 when the day left is a
    Friday."""
    sd = list(server_day)
    n = len(sd)
    u = np.zeros(n)
    for i in range(n - 1):
        if sd[i + 1] != sd[i]:
            u[i] = 3.0 if date.fromisoformat(sd[i]).weekday() == 4 else 1.0
    return u


# ---- the screen: what a strategy file may contain ------------------------------
def screen(path: str) -> list:
    """Reasons to refuse the file before running it (empty = allowed)."""
    raw = open(path, "rb").read()
    if len(raw) > MAX_BYTES:
        return [f"file is {len(raw)} bytes (limit {MAX_BYTES})"]
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=path)
    except (SyntaxError, UnicodeDecodeError) as e:
        return [f"does not parse: {e}"]
    why = []

    def bad_module(m: str) -> bool:
        parts = m.split(".")
        if parts[0] not in ALLOWED_IMPORTS:
            return True
        return m not in ALLOWED_SUBMODULES and any(p in FORBIDDEN_ATTRS or p.startswith("_") for p in parts[1:])

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if bad_module(a.name):
                    why.append(f"line {node.lineno}: import {a.name} (only numpy, pandas, math)")
        elif isinstance(node, ast.ImportFrom):
            m = node.module or ""
            if node.level or bad_module(m):
                why.append(f"line {node.lineno}: from {m} import ... (only numpy, pandas, math)")
            for a in node.names:
                if a.name == "*" or a.name in FORBIDDEN_ATTRS or a.name in FORBIDDEN_NAMES or a.name.startswith("_"):
                    why.append(f"line {node.lineno}: from {m} import {a.name}")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            why.append(f"line {node.lineno}: uses {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRS or node.attr.startswith("_"):
                why.append(f"line {node.lineno}: uses .{node.attr}")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "positions" for n in tree.body):
        why.append("no top-level def positions(df)")
    return why


def idea_of(path: str) -> str:
    try:
        doc = ast.get_docstring(ast.parse(open(path, encoding="utf-8").read())) or ""
    except Exception:
        return ""
    for line in doc.splitlines():
        if line.strip().upper().startswith("IDEA:"):
            return line.strip()[5:].strip()
    return doc.strip().splitlines()[0] if doc.strip() else ""


def load_strategy(path: str):
    why = screen(path)
    if why:
        raise ValueError("refused: " + "; ".join(why))
    name = "strategy_" + os.path.splitext(os.path.basename(path))[0].replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.positions


# ---- running and checking a strategy -------------------------------------------
def run_positions(fn, df: pd.DataFrame) -> np.ndarray:
    out = fn(df.copy())
    p = np.asarray(out.to_numpy() if isinstance(out, (pd.Series, pd.DataFrame)) else out, dtype=float).ravel()
    if len(p) != len(df):
        raise ValueError(f"positions has {len(p)} values for {len(df)} bars")
    p = np.where(np.isnan(p), 0.0, p)
    bad = ~np.isin(p, (-1.0, 0.0, 1.0))
    if bad.any():
        raise ValueError(f"positions must be -1, 0 or 1 (got {p[bad][:3].tolist()} ...)")
    return p


def lookahead(fn, df: pd.DataFrame, p_full: np.ndarray, cuts: int = CUTS, seed: int = 7) -> list:
    """Bars where re-running on data cut off there changes the position: any
    hit means the strategy reads bars after the one it is deciding."""
    n = len(df)
    rng = np.random.default_rng(seed)
    ks = sorted(set(rng.integers(int(n * 0.2), n - 1, size=cuts).tolist()))
    hits = []
    for k in ks:
        p_cut = run_positions(fn, df.iloc[:k + 1])
        diff = np.nonzero(p_cut != p_full[:k + 1])[0]
        if len(diff):
            hits.append({"cut": int(k), "first_changed_bar": int(diff[0])})
    return hits


def trades_of(p: np.ndarray) -> list:
    """Maximal runs of one non-zero position: (entry bar, exit bar, direction).
    Entered at the entry bar's close, left at the exit bar's close."""
    n = len(p)
    out, i = [], 0
    while i < n:
        if p[i] == 0:
            i += 1
            continue
        j = i
        while j + 1 < n and p[j + 1] == p[i]:
            j += 1
        a, b = i, min(j + 1, n - 1)
        if b > a:
            out.append((a, b, int(p[i])))
        i = j + 1
    return out


def segments_of(allowed: np.ndarray) -> list:
    """Contiguous runs of allowed bars: [(start, end)] inclusive."""
    segs, i, n = [], 0, len(allowed)
    while i < n:
        if not allowed[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and allowed[j + 1]:
            j += 1
        segs.append((i, j))
        i = j + 1
    return segs


def trade_net(c, units, a, b, s) -> float:
    swap = (SWAP_LONG if s > 0 else SWAP_SHORT) * float(units[a:b].sum())
    return s * (c[b] / c[a] - 1.0) - 2 * SIDE - swap


def score(df: pd.DataFrame, p: np.ndarray, allowed=None, twins: int = TWINS, seed: int = 11) -> dict:
    """The strategy's trades inside one allowed segment each, against random-
    timing twins drawn inside the allowed segments."""
    n = len(df)
    allowed = np.ones(n, dtype=bool) if allowed is None else np.asarray(allowed, dtype=bool)
    c = df["close"].to_numpy(dtype=float)
    units = rollover_units(df["server_day"])
    cum = np.concatenate([[0.0], np.cumsum(units)])       # units held from a to b = cum[b] - cum[a]
    segs = segments_of(allowed)
    seg_id = np.full(n, -1)
    for k, (s0, s1) in enumerate(segs):
        seg_id[s0:s1 + 1] = k
    tr = [(a, b, s) for a, b, s in trades_of(p) if seg_id[a] >= 0 and seg_id[a] == seg_id[b]]
    res = {"bars": int(allowed.sum()), "trades": len(tr)}
    if not tr:
        return res
    a = np.array([t[0] for t in tr])
    b = np.array([t[1] for t in tr])
    s = np.array([t[2] for t in tr], dtype=float)
    L = b - a
    sw = np.where(s > 0, SWAP_LONG, SWAP_SHORT)
    net = s * (c[b] / c[a] - 1.0) - 2 * SIDE - sw * (cum[b] - cum[a])

    rng = np.random.default_rng(seed)
    seg_len = np.array([s1 - s0 + 1 for s0, s1 in segs])
    seg_start = np.array([s0 for s0, _ in segs])
    tw = np.empty((twins, len(tr)))
    for k in range(len(tr)):
        room = np.clip(seg_len - L[k], 0, None)               # valid starts per segment
        tot = int(room.sum())
        if tot == 0:
            tw[:, k] = net[k]
            continue
        u = rng.integers(0, tot, size=twins)
        cr = np.cumsum(room)
        si = np.searchsorted(cr, u, side="right")
        e = seg_start[si] + (u - (cr[si] - room[si]))
        f = e + L[k]
        tw[:, k] = s[k] * (c[f] / c[e] - 1.0) - 2 * SIDE - sw[k] * (cum[f] - cum[e])
    tm = tw.mean(axis=1)
    sd = float(tm.std(ddof=1))
    z = (float(net.mean()) - float(tm.mean())) / sd if sd > 0 else float("nan")
    h = (len(net) + 1) // 2

    bar_r = np.zeros(n)
    held = np.zeros(n)
    for (ta, tb, ts) in tr:
        held[ta:tb] = ts
    step = np.zeros(n)
    step[1:] = held[:-1] * (c[1:] / c[:-1] - 1.0)
    swap_bar = np.zeros(n)
    swap_bar[1:] = -np.where(held[:-1] > 0, SWAP_LONG, np.where(held[:-1] < 0, SWAP_SHORT, 0.0)) * units[:-1]
    chg = np.abs(np.diff(np.concatenate([[0.0], held])))
    bar_r = step + swap_bar - SIDE * chg
    eq = np.cumprod(1.0 + bar_r)
    dd = float((1.0 - eq / np.maximum.accumulate(eq)).max())

    res.update({
        "long_trades": int((s > 0).sum()), "short_trades": int((s < 0).sum()),
        "mean_net_bp": float(net.mean() * 1e4), "median_net_bp": float(np.median(net) * 1e4),
        "win_rate": float((net > 0).mean()), "avg_hold_bars": float(L.mean()),
        "exposure_pct": float(100.0 * (held != 0)[allowed].mean()),
        "total_return_pct": float(100.0 * (eq[-1] - 1.0)), "max_drawdown_pct": float(100.0 * dd),
        "twin_mean_bp": float(tm.mean() * 1e4), "z": z,
        "p": (0.5 * math.erfc(z / math.sqrt(2)) if z == z else float("nan")),
        "excess_first_half_bp": float((net[:h].mean() - tw[:, :h].mean()) * 1e4),
        "excess_second_half_bp": (float((net[h:].mean() - tw[:, h:].mean()) * 1e4)
                                  if len(net) > h else float("nan"))})
    return res


def evaluate(path: str, df: pd.DataFrame = None, allowed=None, check_lookahead: bool = True) -> dict:
    df = load() if df is None else df
    out = {"strategy": os.path.basename(path), "idea": idea_of(path)}
    try:
        fn = load_strategy(path)
        p = run_positions(fn, df)
        if check_lookahead:
            hits = lookahead(fn, df, p)
            if hits:
                out.update({"ok": False, "error": f"lookahead: re-running on data cut off at bar "
                            f"{hits[0]['cut']} changes bar {hits[0]['first_changed_bar']} ({len(hits)} cuts)"})
                return out
        out.update({"ok": True, **score(df, p, allowed)})
    except Exception as e:
        out.update({"ok": False, "error": f"{type(e).__name__}: {e}"[:400]})
    return out


def show(r: dict) -> str:
    if not r.get("ok"):
        return f"{r['strategy']}: NOT SCORED -- {r.get('error')}"
    if not r.get("trades"):
        return f"{r['strategy']}: 0 trades"
    return (f"{r['strategy']}: {r['trades']} trades ({r['long_trades']} long / {r['short_trades']} short), "
            f"net {r['mean_net_bp']:+.2f} bp a trade (median {r['median_net_bp']:+.2f}, win {100 * r['win_rate']:.0f}%), "
            f"random timing {r['twin_mean_bp']:+.2f} bp -> z {r['z']:+.2f} (p {r['p']:.3f}); "
            f"halves {r['excess_first_half_bp']:+.2f} / {r['excess_second_half_bp']:+.2f} bp over twins; "
            f"total {r['total_return_pct']:+.1f}%, max drawdown {r['max_drawdown_pct']:.1f}%, "
            f"in market {r['exposure_pct']:.0f}%, hold {r['avg_hold_bars']:.1f} bars"
            + (f"  [{r['idea']}]" if r.get("idea") else ""))


# ---- self-test -----------------------------------------------------------------
_CHEAT = 'import pandas as pd\ndef positions(df):\n    return (df["close"].shift(-1) > df["close"]).astype(int)\n'
_SNEAK = 'import os\ndef positions(df):\n    return [0] * len(df)\n'


def selftest() -> int:
    import tempfile
    print(f"python {sys.version.split()[0]}, numpy {np.__version__}, pandas {pd.__version__}")
    ok = True
    df = load()
    first, last = df.index[0], df.index[-1]
    good = len(df) > 5000 and first.year == 2022 and last.year == 2022
    print(f"data: {len(df)} bars, {first} .. {last}: {'ok' if good else 'UNEXPECTED'}")
    ok &= good
    ex = evaluate(os.path.join(HERE, "example_strategy.py"), df)
    print("example: " + show(ex))
    ok &= bool(ex.get("ok")) and ex.get("trades", 0) > 0
    with tempfile.TemporaryDirectory() as t:
        for name, src, want in (("cheat.py", _CHEAT, "lookahead"), ("sneak.py", _SNEAK, "refused")):
            f = os.path.join(t, name)
            open(f, "w", encoding="utf-8").write(src)
            r = evaluate(f, df)
            caught = (not r.get("ok")) and want in r.get("error", "")
            print(f"{name}: {'caught (' + want + ')' if caught else 'NOT CAUGHT: ' + str(r)}")
            ok &= caught
    print("SELFTEST OK" if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "--selftest":
        return selftest()
    as_json = "--json" in args
    target = [a for a in args if not a.startswith("--")][0]
    files = ([os.path.join(target, f) for f in sorted(os.listdir(target)) if f.endswith(".py")]
             if os.path.isdir(target) else [target])
    df = load()
    for f in files:
        r = evaluate(f, df)
        print(json.dumps(r) if as_json else show(r), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
