# ReScope team pack (Member 1 + Member 2)

```
member1/   Research & Evidence Lead (tasks 1.1 to 1.14)  start with member1/TASKS.md   (unchanged v6 pack)
member2/   Reasoning & Interface Lead (tasks 2.1 to 2.15) start with member2/TASKS.md   (new)
```
**How they connect:** Member 1 collects and calculates (evidence, metric series, benchmark, coverage). Member 2 reads that output
through `member2/rescope_m2/adapter.py` and runs the 12-stage reasoning pipeline, then shows it in the dashboard.

**Fast look (no network, no keys):**
```
cd member2
pip install -r requirements.txt
python scripts/make_demo_bundles.py      # five FICTIONAL companies
streamlit run dashboard.py
```
**Real company:** run Member 1's `export_for_member2.py`, then `member2/scripts/run_pipeline.py --handover ...` (see member2/TASKS.md, work package A).

Dashboard theme: #202A44, #2E4A7F, #7B93B7, #C9D2DC, #F6F7F9. Research findings, not investment advice.
