# nq-lab

A scorer and a brief for one year (2022) of Nasdaq-100 hourly bars: find
strategies that beat random timing after FundedNext's costs. **Read
BRIEF.md** -- it is the task and the rules.

The price data is not in this repo: `build_nq_2022.py` downloads it from
Dukascopy's public feed and checks it.

## Steps

1. Build the data. In this folder run `python build_nq_2022.py`. It makes
   12 requests (the feed often answers 503, so it waits and retries) and
   must end with `MATCH`. If it stops on a fetch error, run it again:
   months already fetched are kept in `work/`.
2. Check the files are exact:

       python -c "import hashlib; [print(f, hashlib.sha256(open(f,'rb').read().replace(bytes([13,10]), bytes([10]))).hexdigest()) for f in ('lab.py','nq_2022.csv','example_strategy.py','BRIEF.md','build_nq_2022.py')]"

   It must print exactly:

       lab.py 859ff60485bfa29979c6b4f505e6dae3ffeea61584c07ebd65e0384ebf509d33
       nq_2022.csv ffe1b411c4d634f69e3a3b3339e6db827cde7e03823f937edc98b2bd8aef7378
       example_strategy.py 0be927d676bb82ca277044d146241a787ea6c084ebdbdb73808cb7915ce66e57
       BRIEF.md 39d09b786b89941e712b3665f434b7eb4cb163f183a26c64e83866dc7b7c73f9
       build_nq_2022.py a812e3f5ea2d2b84c04ec10c547bd5f551373c56d3d46d13af4e1051373fc83b

3. `python lab.py --selftest` must end with `SELFTEST OK`.
4. Work as BRIEF.md says. Drafts and exploration go in `work/`. Final
   strategies, `LOG.md` and `NOTES.md` go in `submissions/`.
5. Hand in: zip `submissions/` and give it to the person running the lab.
   Never change `lab.py`, `BRIEF.md`, `example_strategy.py` or the data.

## The rule that matters most

Use only `nq_2022.csv`. Never download any other market data or years,
from anywhere.
