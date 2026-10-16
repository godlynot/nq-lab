# NQ lab: find a Nasdaq-100 trading strategy that beats random timing

## The goal

Find trading strategies for the Nasdaq-100 (the NDX100 CFD at the prop firm
FundedNext) that make money after costs **because of when they trade**, not by
luck and not just because the market went up or down.

You have one year of hourly bars: 2022. Every strategy you hand in will later
be tested **once** on about 13 years of hourly data you do not have
(2012-2021 and 2023-2026), with the same scoring code you have here. You get
no feedback from that test while you work. A strategy that only fits 2022
will fail it.

## What is in this folder

- `nq_2022.csv`: 5,903 hourly bars of the Nasdaq-100 for 2022. Times are UTC
  bar opens. `server_day` is the prop firm's trading day (it turns at 17:00
  New York time; weekends roll into Monday).
- `lab.py`: the scorer. `python lab.py --selftest` checks this environment;
  `python lab.py my_strategy.py` scores one strategy; `python lab.py folder/`
  scores every .py file in a folder.
- `example_strategy.py`: the file format (a moving-average crossover; it
  loses in 2022).

Do not edit `lab.py` or the data. The judge uses its own copies.

## What a strategy is

One .py file that defines

    def positions(df):  ->  a pandas Series or numpy array, one value per bar

with -1 (short), 0 (flat) or +1 (long) for every bar. `df` has a UTC
DatetimeIndex and the columns open, high, low, close, volume, server_day.

- The position at bar i may use bars 0..i only. It is held from bar i's
  close to bar i+1's close. `lab.py` re-runs every strategy on cut-off data
  and refuses any that looks ahead.
- Start the file with a docstring whose first line is `IDEA: <one sentence>`.
- Imports: numpy, pandas and math only. No files, network or system access
  (no open, eval, exec, getattr, read_*/to_* methods, private `_` attributes).
  Do not name a variable `open`; use `o = df["open"]`. Files that break this
  are refused before they run. Limit 20 kB.
- No facts specific to 2022: no hard-coded dates, price levels or event
  calendars. Rules about the time of day or the weekday are fine (the US cash
  session is 13:30-20:00 UTC in summer, 14:30-21:00 UTC in winter).

## How it is scored

Costs are FundedNext's real ones: a spread of 0.01% of the position on every
entry and every exit, plus swap for every night a position is held (long 1.22
basis points a night, short 0.19, Friday counts three nights).

The number that matters is **z**: your strategy's average net return per trade
against 200 random-timing twins -- the same trades with the same direction and
the same holding time, entered at random bars. z above 0 means your timing
beat chance; a market trend alone does not raise z, because the twins share
your direction.

`lab.py` also prints the net return per trade, win rate, total return, max
drawdown, time in the market, and the excess over the twins in the first and
second half of your trades.

## What makes a strategy likely to survive the hidden years

Trying many ideas on one year will always turn up some that look good by
chance. The hidden test will expose them. So:

- **Prefer simple ideas with a reason** (a known market behaviour) and few
  parameters, over a tuned combination of conditions.
- **Aim for 100+ trades in 2022.** With 20 trades, a high z is mostly luck.
- **Check both halves.** Positive excess in the first and second half of the
  year is a good sign; one great month is not.
- **Check the neighbours.** If a 20-bar lookback works but 18 and 22 do not,
  it is noise. Report how the neighbours did.
- **Count everything you try.** We correct for how many ideas were tried, so
  an honest count matters more than a pretty result.
- The end use is FundedNext's exam (+8%, then +5%, before a 10% total loss or
  a 5% loss in one day), so large drawdowns matter too -- but the edge (z)
  comes first.

## What to hand in

A folder `submissions/` with:

1. **Up to 20 strategy files**, your best, each one passing
   `python lab.py submissions/<file>.py` without errors.
2. **`LOG.md`**: one line per submitted strategy (file name, idea, its 2022
   lab.py line, how its parameter neighbours scored), and **the total number
   of distinct ideas and parameter settings you tested** along the way.
3. **`NOTES.md`**: what you learned about 2022's price action, including what
   did not work. Negative results are useful.

Zip the folder when you are done.
