# ReScope: Member 1 (Research & Evidence Lead) implementation

**Start with `TASKS.md`**: every Member 1 task with exact commands and done-criteria. `REPORT_SECTIONS.md` has draft report text.

Code for tasks 1.1 to 1.14 of the build plan. Python 3.11+.

```
pip install -r requirements.txt
python -m pytest -q                      # 86 offline tests, no network needed
python scripts/run_member1_demo.py       # end-to-end demo on FICTIONAL data, regenerates data/sample_*.json
```

## What is verified and what is not (read this first)

| Status | What |
| --- | --- |
| **Tested offline (48 tests pass)** | schema, store, cache, HTTP retry/throttle/cache, period and date parsing, source tagging, dedupe/syndication, intake and peers, archetype rules, PDF page locators, HTML ingestion, collector failure tolerance, search fallback and both Member 2 hooks, metric maths, table extraction, series building, proxies, benchmark, triangulation, say-vs-do, disclosure changes, coverage, no-hard-coding scan, evaluation sheet, the public API |
| **NOT tested against real sites** | Everything that talks to the live internet: the exchange list download, document discovery through Tavily/ddgs, IR pages, PDF extraction on real results PDFs, RSS, GDELT, data.gov.in, World Bank. The development sandbox could not reach those hosts, so these paths are exercised only with fake transports |
| **Needs tuning on real documents** | `quant/extract.py` label regexes and header detection, archetype keyword lists, tier weights, the 0.45 claim-clustering threshold, benchmark thresholds |
| **Needs you to fill in** | `config/industry_series.json` (verified official series URLs/IDs; see the `.example` file), your contact in `.env` (goes into the User-Agent), the Tavily key |

Before relying on any URL in `rescope/config.py`, check the site's current terms and structure. Do not bypass blocks; use the inbox fallback instead.

## Findings from the first live run (11 Oct) and what changed
- Company and exchange sites returned HTTP 403 to automated downloads; two sites were skipped because robots.txt forbids it (correct behaviour). Do not bypass these blocks.
- Most documents that did download were broker research and transcript aggregators, not filings. Fixed: documents are now classified by host and content (`collectors/documents.py: classify_document`): only exchange hosts and the company's own site earn tier 1; analyst research is third-party news (tier 4); unknown hosts get tier 3 with an `unverified_host` flag.
- Numbers from different documents can use different units. Fixed: `quant/series.py: raw_from_extracted` uses one anchor document and merges another only when overlapping figures agree; skipped documents are explained in `metric_notes`.
- GDELT rate-limits (HTTP 429). Fixed: slower host interval, longer back-off, search fallback for news.
- New: `collectors/structured.py` pulls quarterly statements from a data aggregator (`yfinance`, unofficial) so receivable and inventory days are possible. It is tier 3, flagged `aggregator` and `unofficial_data`, has no volume data, and covers about 4 to 5 quarters. Install with `pip install yfinance`; disable with `--no-structured`. Check its terms and say in the report that it is an aggregator.

- Bug found and fixed (second live run): year-on-year growth used an index offset, so a missing quarter silently gave a wrong growth number. It now compares each quarter with the SAME quarter a year earlier (`quant/series.py: prior_year`) and returns None if that quarter is absent. Coverage now lists missing quarters and warns when no official filing was read.
- New: `quant/volume_claims.py` extracts management-stated volume growth ('underlying volume growth of 4%') with its quarter and source. A quarter is taken only from the claim's own sentence; sources that disagree by more than 1 percentage point for the same quarter are dropped and reported; the resulting `volume_growth_yoy` points are labelled 'STATED by management'.
- Peers now use the aggregator only by default (`--peer-docs` to also search documents for peers).
- Third live run: a volume value was given the wrong quarter (taken from a stray period in a table chunk). Quarters are now taken only from the claim's own sentence, from a quarter named in the document title (prose only, never table cells), or, for transcripts, from the call date (the quarter that just ended). Stated beats inferred. The missing-quarters warning now looks only at the latest 8 quarters. Transcripts and presentations are also searched quarter by quarter.
- Fourth live run: price/mix was missing because stated volume and computed revenue growth never fell in the same quarter. Management-stated sales growth ('underlying sales growth of 5%, driven by underlying volume growth of 4%') is now read only from sentences that also state a volume figure; price/mix is derived from that pair when no computed revenue growth exists for the quarter (computed revenue growth is preferred when present). GDELT non-JSON replies are handled as rate limits.
- Closed after the five-company batch (HUL, Nestle, Tata Consumer, Titan, Asian Paints; 108 to 760 seconds each; Titan and Asian Paints found one peer):
  - Hosts that refuse or time out three times in a row are skipped for the rest of the run, and document kinds run in parallel (cold runs must fit the demo window).
  - Peers: companies named in at least two of the target's own documents are added when fewer than three peers were found; needs the full NSE list via `--all-listed`.
  - Industry series can be flagged `"price_index": true` (feeds the volume proxy automatically) and `"pairs_with": "<metric>"` (used in the benchmark).
  - Segment/channel mix shares are read from tables that have a 'segment revenue' heading and a total that matches the sum (per quarter).
  - Another document in different units is merged only when the unit change is a proven power of ten (rupees vs crore) on 2+ matching cells; otherwise it is skipped.
  - Google Trends search interest is optional (`--trends`), flagged `lead_only`; manual PDFs are copied into the shared cache; the filings-availability flag on peers comes from what was actually collected.
- Peer quality: brokers, rating agencies and banks are never peers; with the aggregator's industry for the target, a peer must share it (or, weaker, its sector and be named in 3+ documents). NSE same-label peers that do not match are replaced when at least three matching peers exist.
- Helper scripts: `scripts/show_run.py`, `show_metrics.py`, `show_volume_mentions.py`, `inspect_store.py`, `check_intake.py`.

## Task map

| Task | Module(s) | Notes |
| --- | --- | --- |
| 1.1 Repo, schema, sample evidence | `schema.py`, `store.py`, `sample_data.py`, `data/sample_evidence.json` | Contract fields exactly as in the plan; extra optional fields `publisher`, `independent`, `flags`. Sample data is fictional |
| 1.2 Intake and peers | `intake/listings.py`, `archetype.py`, `resolver.py` | `resolve_company(name, universe, ...)`: fuzzy match, archetype, peers (industry plus names in competition text, filtered by filings availability), warnings. No company names in code |
| 1.3 Filings and results | `collectors/documents.py`, `pdf_utils.py`, `http.py` | Search-led discovery, polite fetch (User-Agent, throttle, back-off, robots.txt), PDF to page-level evidence with `p.N` / `p.N table K` locators |
| 1.4 Annual report, presentation, transcript | `collectors/documents.py` (`KINDS`), `tagging/tagger.py` | Tier 1 / 3 / 3, passage chunking, `collect_from_ir_page` for PDF link pages |
| 1.5 Peers and industry | `collectors/industry.py`, `api.collect` | Peers reuse the document collector with `role=peer`; industry series are config-driven, `role=industry`, tier 2 |
| 1.6 Search and alt data | `collectors/search.py`, `collectors/industry.py` | Tavily then ddgs; `find_disconfirming`, `find_prior_coverage` (novelty check hook); RSS, GDELT, Wayback, optional Trends |
| 1.7 Tagging, dedupe, syndication | `tagging/dedupe.py` | Origin hash, shingle similarity, syndicated / same-publisher / statement-only flags, `dated_before_event` flag |
| 1.8 Quantitative engine | `quant/metrics.py`, `extract.py`, `series.py` | Pure functions; price/volume split adds up exactly; proxy only when labelled; cross-checks reject inconsistent totals; every point keeps its locator |
| 1.9 Benchmark | `quant/benchmark.py` | `company_specific` / `sector_wide` / `mixed` / `insufficient` per metric and overall |
| 1.10 Triangulation | `analysis/triangulation.py` | sentence-transformers if installed, else TF-IDF; independence counts after syndication merge; needs 2+ independent types with one outside the company |
| 1.11 Say-vs-do, disclosure change, sufficiency, coverage | `analysis/say_vs_do.py`, `disclosure_change.py`, `sufficiency.py` | Generic rule library; missing data gives `insufficient`, never a guess |
| 1.12 Caching and backups | `cache.py`, `http.py`, `collectors/local_ingest.py`, `scripts/prewarm_cache.py` | Backups live in the same cache; manual PDFs go through the same pipeline and are flagged `manual_download`; never hand-edit data |
| 1.13 Testing and no-hard-coding | `eval/checks.py`, `scripts/run_company.py`, `tests/` | Evaluation sheet CSV; `python -m rescope.eval.checks --universe <real list>` scans code for company names/tickers (exit 1 on a hit) |
| 1.14 Finals preparation | `api.validate_company_input`, parallel `Member1API.collect`, per-source failure isolation, `scripts/prewarm_cache.py` | The live run is still the full pipeline from a cold name |

Tasks 1.13 and 1.14 are partly **your time, not code**: running 5 real companies, closing the failure log, testing unseen non-NIFTY names and timing a cold run all need live access. The tooling for them is here.

## For Member 2: the interface (plan Section 6.3)

```python
from rescope.api import Member1API
api = Member1API(universe=load_universe("data/equity_list.csv"))
profile = api.resolve("Company Name")                    # CompanyProfile (symbols, archetype, peers, warnings)
api.collect(profile, years=["FY26", "FY25"])             # fills SQLite; returns per-source counts and errors
api.build_metrics(profile.name)                          # {metric: MetricSeries} with locators; proxies flagged
api.benchmark(profile)                                   # company vs peers vs industry
api.coverage(profile)                                    # score, warnings, proxies_used
api.find_disconfirming(hypothesis, entity, peers)        # skeptic
api.find_prior_coverage(finding, entity)                 # novelty check: items, independent_count, publishers
```
Until real data is ready, load `data/sample_evidence.json` and `data/sample_outputs.json` (fictional) and build against them.

## Rules baked into the code
- No company name, ticker or company-specific number in code or prompts (`eval/checks.py` enforces it).
- Code does all arithmetic. Missing inputs return `None`; proxies are labelled `is_proxy=True` and lower the coverage score.
- Evidence without a URL is rejected by the schema.
- A failing source is recorded in `errors`, never raised.
- Fetching is polite: real contact in the User-Agent, per-host throttle, retries with back-off, robots.txt respected, cached.

## Layout
```
rescope/            package (schema, store, cache, http, api, intake/, collectors/, tagging/, quant/, analysis/, eval/)
scripts/            run_member1_demo.py, run_company.py (live), prewarm_cache.py
config/             industry_series.json (fill in), industry_series.example.json
data/               fictional sample files
tests/              86 offline tests
```
