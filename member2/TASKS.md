# Member 2 task pack: Reasoning & Interface Lead

Tasks 2.1 to 2.15 from the build plan, each mapped to code, a command and a done-criterion. Commands are for **Windows PowerShell in VS Code**, run from this `member2` folder.

## 0. Setup (once)
```
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m unittest discover -s tests -v        # 32 tests, no network, no API key needed
python scripts/make_demo_bundles.py            # builds 5 FICTIONAL demo companies into data\bundles
streamlit run dashboard.py
```
Optional: copy `.env.example` to `.env` and add a model key. With no key every stage runs on built-in rules, so the demo never depends on a model.
Member 1's code sits in `..\member1`; Member 2 reads it through `rescope_m2/adapter.py` (no copy needed).

## 1. The 15 tasks
| # | Task | Built in | Done when |
| --- | --- | --- | --- |
| 2.1 | LLM wrapper | `llm.py` | `llm.call(prompt_id, inputs, schema)` retries, falls back Claude to Gemini to Groq, validates JSON, logs to SQLite (`data/m2_runs.db`, table `llm_log`) |
| 2.2 | Prompt library | `prompts.py`, `prompts/*.yaml` | six versioned prompts; `python scripts/check_no_names.py ..\member1\data\equity_list.csv` prints `0 hit(s)` |
| 2.3 | Angle planner and hypotheses | `planner.py` | 3 to 5 hypotheses, each TESTED in code on the metric series and ranked; untestable ones listed with the metric needed |
| 2.4 | Orchestrator and progress events | `pipeline.py` | `pipeline.stream(inputs)` yields 12 stage events then the bundle |
| 2.5 | Claim extraction | `claims.py` | claims carry URL, locator, period; no URL means dropped; model claims must quote the passage exactly |
| 2.6 | Timeline and change point | `timeline.py`, `common.detect_change_point` | primary change point flagged; claims, disclosure changes merged into one dated list |
| 2.7 | Contradiction finder | `contradictions.py` | claim pairs (NLI if installed, judge quotes both passages) plus management-vs-numbers from Member 1 say-vs-do |
| 2.8 | Skeptic | `skeptic.py` | predictions, `find_disconfirming` hook, sector test, survived/weakened/rejected, max 2 rounds, next hypothesis if rejected |
| 2.9 | Counterargument and falsification | `falsify.py` | strongest alternative picked by strength; condition has metric, operator, threshold, periods and is schema-validated |
| 2.10 | Scoring | `scoring.py` | 0.30/0.25/0.20/0.15/0.10 weights, contradiction penalty, Strong/Moderate/Weak, Moderate cap when peers match, Weak on thin coverage |
| 2.11 | Discovery writer | `writer.py` | 8 elements; `check_discovery` passes for every demo company; numbers come only from the metric series |
| 2.12 | Dashboard | `dashboard.py`, `rescope_m2/ui/` | tabs at the top (see section 3); every chart reads the selected company |
| 2.13 | Landing connection and polish | `ui/theme.py` | palette applied, fade/badge/pulse motion, reduced-motion respected. **Landing page itself and its button URL are still yours** |
| 2.14 | Extra analysis | `extras.py`, `falsify.evaluate_falsification` | falsification monitor, language drift, why-not, peer heatmap, run diff |
| 2.15 | Report layout and finals | see section 4 | you write the PDF and rehearse; this pack gives you the numbers and screens |

## 2. Work packages (in this order)
**A. First run on real Member 1 data**
```
cd ..\member1
python scripts\export_for_member2.py "Hindustan Unilever" --universe data\equity_list.csv
cd ..\member2
python scripts\run_pipeline.py --handover ..\member1\handover\hindustan-unilever-limited --no-llm
streamlit run dashboard.py
```
Pick the company in the box at the top. The handover export does not write say-vs-do, disclosure or triangulation files; for those use `--name "Company"` (live) which asks Member 1's API for them, or drop `say_vs_do.json`, `disclosure_changes.json`, `triangulation.json` into the handover folder.

**B. Turn on the model (optional)**: put a key in `.env`, rerun A without `--no-llm`. Check `llm_log` for failures. A model may only re-word text; any number it adds that the code did not compute makes the reply be discarded.

**C. Two-company test (task 2.11)**: run two different companies with no code change; both must end `check problems: none`.

**D. Finals**: `python scripts\run_pipeline.py --name "Company"` from a cold name is the live path; the dashboard's **Run a company** tab shows the same 12 steps lighting up. A stored result is a **cached backup** and the dashboard labels it so.

## 3. Dashboard map
Top bar: company selector (rating and data label shown), Plain-language switch. Tabs: **Overview** (banner, badge, key numbers, headline charts, counterargument, falsification) · **Growth quality** (volume vs price/mix) · **Working capital** (metric switch vs peers) · **Peers & industry** (heatmap, verdicts, peer overlay) · **Timeline** (change point and events) · **Evidence** (source mix, triangulation, click-through passage) · **Reasoning** (12 steps, hypotheses, skeptic, contradictions, say-vs-do, why-not) · **Data quality** (score breakdown, coverage meter) · **Run a company**.

## 4. Rules
- No company name, ticker or number in code or prompts (tested). Demo company names live only in `demo/demo_companies.json`.
- Code does all arithmetic. A model never supplies a figure.
- Weak or thin results are shown as Weak with the reason; nothing is forced.
- No investment advice anywhere; the disclaimer is on every page and `check_discovery` rejects advice wording.

## 5. Known limits (tell the judges, do not hide them)
- Claim direction and topic come from keyword rules unless a model is on; a sentence mixing two topics can be misread. Review contradictions by eye.
- The company-vs-sector test uses Member 1's benchmark; with fewer than 2 peers it returns "insufficient" and the finding is at most Moderate.
- Scoring weights and tier weights are starting values; tune on your 5-company test.
- Demo bundles are fictional and generated to exercise every path; they are not findings about real companies.
