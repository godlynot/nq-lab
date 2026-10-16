#!/usr/bin/env python3
"""
Rebuild nq_2022.csv from Dukascopy's public data feed, byte for byte the file
the judge uses, and check it.

    python build_nq_2022.py            writes nq_2022.csv next to this file, then prints MATCH or MISMATCH

12 requests (one per month of 2022, hourly BID candles for USATECHIDXUSD).
Needs Python 3.8+, numpy and pandas; downloads with the standard library.
"""
import hashlib
import lzma
import os
import struct
import sys
import time
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://datafeed.dukascopy.com/datafeed/USATECHIDXUSD/{y}/{m:02d}/BID_candles_hour_1.bi5"
SCALE = 1000.0
EXPECT = "ffe1b411c4d634f69e3a3b3339e6db827cde7e03823f937edc98b2bd8aef7378"   # sha256 with CRLF -> LF


CACHE = os.path.join(HERE, "work", "dukascopy_cache")


def fetch(url: str, cache_file: str) -> bytes:
    """The month's file, from the cache if an earlier run got it. The feed
    often answers 503 (busy): wait longer each time and retry."""
    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 0:
        return open(cache_file, "rb").read()
    for k in range(12):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                b = r.read()
            if b:
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                with open(cache_file, "wb") as w:
                    w.write(b)
                return b
        except Exception as e:
            print(f"  retry {k + 1}/12 after {type(e).__name__}: {e}", flush=True)
        time.sleep(min(120, 10 * (k + 1)))
    raise RuntimeError(f"could not fetch {url} -- run the script again later; fetched months are kept")


def decode(blob: bytes, start: pd.Timestamp) -> list:
    raw = lzma.decompress(blob)
    out = []
    for k in range(0, len(raw) - len(raw) % 24, 24):
        t, o, c, lo, hi, v = struct.unpack(">5if", raw[k:k + 24])
        out.append((start + pd.Timedelta(seconds=t), o / SCALE, hi / SCALE, lo / SCALE, c / SCALE, v))
    return out


def server_days(ts: pd.Series) -> list:
    """FundedNext's day: New York time plus 7 h (turns at 17:00 New York);
    Saturday and Sunday roll into Monday."""
    idx = pd.DatetimeIndex(pd.to_datetime(ts, utc=True))
    wall = idx.tz_convert("America/New_York").tz_localize(None) + pd.Timedelta(hours=7)
    d = wall.normalize()
    wd = d.weekday.to_numpy()
    d = d + pd.to_timedelta([2 if x == 5 else 1 if x == 6 else 0 for x in wd], unit="D")
    return list(d.strftime("%Y-%m-%d"))


def main() -> int:
    rows = []
    for m in range(1, 13):
        url = URL.format(y=2022, m=m - 1)                      # the feed's month is 0-based
        cached = os.path.join(CACHE, f"2022-{m:02d}.bi5")
        had = os.path.exists(cached)
        rows += decode(fetch(url, cached), pd.Timestamp(year=2022, month=m, day=1, tz="UTC"))
        print(f"  2022-{m:02d}: {len(rows)} candles so far{' (cached)' if had else ''}", flush=True)
        if not had:
            time.sleep(3.0)
    d = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    d = d.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    d = d[d["volume"] > 0].copy()
    d = d[d["timestamp"].dt.year == 2022].copy()
    d["server_day"] = server_days(d["timestamp"])
    d.insert(0, "time", d.pop("timestamp").dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    d = d[["time", "open", "high", "low", "close", "volume", "server_day"]]
    out = os.path.join(HERE, "nq_2022.csv")
    d.to_csv(out, index=False, float_format="%.10g")
    got = hashlib.sha256(open(out, "rb").read().replace(bytes([13, 10]), bytes([10]))).hexdigest()
    print(f"{len(d)} bars -> {out}")
    print("MATCH" if got == EXPECT else f"MISMATCH: {got}")
    return 0 if got == EXPECT else 1


if __name__ == "__main__":
    sys.exit(main())
