# Member 1 task pack: Research & Evidence Lead

Everything assigned to Member 1 (tasks 1.1 to 1.14), in one place. Commands are for **Windows PowerShell in VS Code**, run from the folder that contains `requirements.txt` (the inner `rescope` folder).

## 0. Setup (once)

1. Activate the environment (do this in every new terminal; the prompt must start with `(venv)`):
   ```
   conda deactivate
   venv\Scripts\Activate.ps1
   ```
2. Create your settings file: copy `.env.example` to `.env` (same folder) and edit it:
   ```
   RESCOPE_CONTACT=your-real-email@example.com
   TAVILY_API_KEY=
   ```
   The program now reads `.env` by itself. Leave `TAVILY_API_KEY` empty to use the free DuckDuckGo fallback (`pip install ddgs`). Never share or commit `.env`.
3. Install and test:
   ```
   pip install -r requirements.txt
   python -m pytest -q
   ```
   You should see all tests pass (86).
4. Put your NIFTY 50 list at `data\equity_list.csv` (columns: Company Name, Industry, Symbol, Series, ISIN Code).
5. (Recommended) Also save the full NSE list of listed companies (`EQUITY_L.csv`, name and symbol columns) as `data\all_listed.csv`, and add `--all-listed data/all_listed.csv` to the run commands below. It lets the system find peers outside the NIFTY 50 (needed for companies like Titan and Asian Paints, which have only one NIFTY 50 peer).

## 1. The 14 tasks

| # | Task | Built in | What YOU do | Done when |
| --- | --- | --- | --- | --- |
| 1.1 | Repo, schema, sample evidence | `schema.py`, `store.py`, `sample_data.py`, `data/sample_*.json` | Give Member 2 the project folder and `data/sample_evidence.json` | Member 2 can load the sample file |
| 1.2 | Company intake and peers | `intake/` | `python scripts/check_intake.py "Company Name"` for each test company | Right symbol, industry, archetype and 3+ peers (non-NIFTY names need a fuller list) |
| 1.3 | Filings and results collectors | `collectors/documents.py`, `http.py`, `structured.py` | Run a company (work package A) | Quarterly figures stored with source labels; blocked sites listed, not worked around |
| 1.4 | Annual report, presentation, transcript collectors | `collectors/documents.py` | Same run; inspect with `scripts/inspect_store.py` | Documents stored with page-level locators and honest type and tier |
| 1.5 | Peer and industry collectors | `api.collect`, `collectors/industry.py` | Work packages A and B | Peer series and at least two industry series stored |
| 1.6 | Search, alt data, hooks | `collectors/search.py` | Nothing extra; Member 2 calls `find_disconfirming` and `find_prior_coverage` | A search quota or block falls back cleanly |
| 1.7 | Tagging, deduplication, syndication | `tagging/` | Nothing extra (runs automatically) | Duplicates collapse; flags appear in the store |
| 1.8 | Quantitative engine | `quant/` | Work package A; read `scripts/show_metrics.py` | Metric tables with source pointers; no invented numbers |
| 1.9 | Peer and industry benchmark | `quant/benchmark.py` | Work packages A and B | Benchmark verdict for the test company |
| 1.10 | Triangulation | `analysis/triangulation.py` | Work package C | Claim clusters show independent source counts |
| 1.11 | Say vs do, disclosure change, sufficiency, coverage | `analysis/` | Work package C | Alignment table, change flags and coverage warnings on real data |
| 1.12 | Caching and backups | `cache.py`, `scripts/prewarm_cache.py` | Work package H | Second run is fast; a cold run still works |
| 1.13 | Testing and no-hard-coding check | `eval/checks.py`, `scripts/run_batch.py` | Work packages D and E | Failure log closed; zero company-specific code |
| 1.14 | Finals preparation | `api.py`, `scripts/prewarm_cache.py` | Work package H | Cold-start run finishes within the demo window |

## 2. Work packages (do them in this order)

### A. Full run on one company, with peers
```
python scripts/run_company.py "Hindustan Unilever" --universe data/equity_list.csv | Out-File -Encoding utf8 run.json
python scripts/show_run.py run.json
python scripts/show_metrics.py "Hindustan Unilever Ltd."
python scripts/show_volume_mentions.py "Hindustan Unilever Ltd."
```
Check: growth is year-on-year against the same quarter; `volume_growth_yoy` appears where management gave a clear figure; coverage lists missing quarters and says no official filing was read; peers have data.
If the downloads are blocked (HTTP 403), do **not** work around it. Save the official PDF by hand into `data\inbox\results\` (also `annual_report`, `presentation`, `transcript`), name it with its quarter (for example `Company_results_Q2_FY26.pdf`), do not edit it, and re-run with `--inbox data/inbox`. Manual files are for development; the live demo must not depend on them.

### B. Industry series (at least two)
1. Find two official, public series relevant to consumer companies (for example a food price index) from sources such as MOSPI, RBI, data.gov.in or the World Bank. Check each site's terms.
2. Edit `config\industry_series.json` (see `config\industry_series.example.json`). For a CSV you can download from a stable link use `url`. If you can only download by hand, save the **unedited** file under `data\industry\` and add `"path": "data/industry/yourfile.csv"`; keep `url` as the public page it came from. It is labelled `manual_download`.
3. Re-run work package A. The `industry` source should show items, and the benchmark can use the series.

### C. Check the analysis on real text
```
python scripts/analyze_company.py "Hindustan Unilever Ltd."
```
Read the say-vs-do verdicts, disclosure changes and triangulation clusters. Do they make sense against what you read? Note any false positives; send them to me to tune.

### D. Test five companies (Task 1.13)
1. Copy `names_example.txt` to `names.txt`; list five companies. Include at least one that does not state volume growth, and one non-NIFTY consumer name if your list has it.
2. Run:
   ```
   python scripts/run_batch.py names.txt --universe data/equity_list.csv
   ```
3. Open `eval_runs\evaluation_sheet.csv` and `eval_runs\batch_summary.csv`. Every failure is a row. Fix or report each one until none is unexplained.

### E. No-hard-coding check
```
python -m rescope.eval.checks --universe data/equity_list.csv
```
It must end with `0 hit(s)`. Run it before every submission.

### F. Hand over to Member 2
```
python scripts/export_for_member2.py "Hindustan Unilever" --universe data/equity_list.csv
```
Give Member 2 the `handover\...` folder and the project. In Python they use `Member1API` (see `README.md`).

### G. Your report sections
Open `REPORT_SECTIONS.md`: drafts for sources, triangulation and calculations. Fill the bracketed results from your runs.

### H. Finals preparation
1. Test unseen companies (including non-NIFTY) with `run_batch.py`.
2. Time a cold run (delete `cache\` and `data\rescope.db`, then run one company). It must fit the demo window; if not, tell me which step is slow.
3. Warm the cache for backup: `python scripts/prewarm_cache.py names.txt --universe data/equity_list.csv`.
4. A cached or pre-run result must always be labelled "Cached backup". The live run starts from the company name only.

## 3. Rules (do not break these)
- No company name, ticker or company-specific number in code or prompts.
- Do not bypass blocks, robots.txt or login walls. Use the manual inbox for development only.
- Never edit downloaded data or numbers by hand.
- Say openly that quarterly figures come from an unofficial aggregator when official sites cannot be read.
- Treat payable days and the cash conversion cycle as unverified.

## 4. When something fails, send me
The error text (last 15 lines), the command you ran, and the output of `python scripts/show_run.py run.json` if a run completed.
