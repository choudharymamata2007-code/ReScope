# ReScope: Member 2 (Reasoning & Interface Lead)
Start with `TASKS.md`. Quick start:
```
pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/make_demo_bundles.py
streamlit run dashboard.py
```
Package `rescope_m2/`: `llm`, `prompts`, `planner`, `claims`, `contradictions`, `timeline`, `skeptic`, `falsify`, `scoring`, `writer`, `extras`, `pipeline` (core, standard library only) and `ui/` (Streamlit + Plotly dashboard in the five-colour palette).
