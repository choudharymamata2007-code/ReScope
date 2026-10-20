# Member 1 status (v6, 18 Oct 2026)

Code for tasks 1.1-1.12 was already in place. This package is cleaned (no venv, cache, .env, backups, run output)
and `config/industry_series.json` now lists two World Bank India series (CPI index, CPI inflation) for task 1.5.
They are UNVERIFIED here (no network when packaged): run work package A and check the `industry` source shows items.

## Still needs YOUR machine (cannot be done offline)
- 1.5  Confirm both industry series load; add a MOSPI/RBI series if you want sector depth. Add data\all_listed.csv.
- 1.13 Run 5 companies (incl. one without volume disclosure, one non-NIFTY): `python scripts/run_batch.py names.txt --universe data/equity_list.csv`,
       then `python -m rescope.eval.checks --universe data/equity_list.csv` must end with 0 hits.
- 1.14 Time a cold run; prewarm backups with scripts/prewarm_cache.py.
- Handover: `python scripts/export_for_member2.py "<real company>" --universe data/equity_list.csv`.

## Known decisions for you
- Companies not listed in config/official_domains.json get official_domains=[] (fail-closed, tested), so their own
  documents are tier 3 "unverified_host". Add verified domains per company, or decide to relax this for the finals.
- config/official_domains.json contains a company name; the hard-coding checker does not scan config/.
- Check periods like Q3 FY27 / FY28 in stored evidence (future-dated).
- Create .env from .env.example (set RESCOPE_CONTACT).
