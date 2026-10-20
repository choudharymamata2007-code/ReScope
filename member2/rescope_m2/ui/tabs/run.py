"""Tab 9: Run a company. Live step tracker driven by the pipeline's progress events."""
import json
import streamlit as st

from ... import adapter, pipeline
from ..data import BUNDLE_DIR

TITLE = "Run a company"


def _tracker(done: list[dict]) -> str:
    rows = []
    for i, name in enumerate(pipeline.STAGES, 1):
        ev = next((e for e in done if e["stage"] == i), None)
        mark = "●" if ev else "○"
        rows.append(f"<div class='rs-step'><b>{mark}</b><div><strong>{name}</strong>"
                    f"<div class='rs-sub'>{ev['summary'] if ev else ''}</div></div></div>")
    return "<div class='rs-card'>" + "".join(rows) + "</div>"


def render(b: dict, ctx: dict) -> None:
    st.subheader("Give it a company name")
    st.caption("The live run starts from the name only. Results are saved so they appear in the company list as a cached backup.")
    mode = st.radio("Source", ["Live run (Member 1 collectors)", "Handover folder"], horizontal=True, key="run-mode")
    name = st.text_input("Company name", key="run-name") if mode.startswith("Live") else st.text_input("Handover folder path", key="run-folder")
    if not st.button("Run", key="run-go") or not name.strip():
        return
    slot, done = st.empty(), []
    try:
        if mode.startswith("Live"):
            adapter.ensure_member1_on_path()
            from rescope.api import Member1API                         # type: ignore
            from rescope.intake.listings import load_universe          # type: ignore
            api = Member1API(universe=load_universe(str(adapter.MEMBER1_DIR / "data" / "equity_list.csv")))
            with st.spinner("Resolving the company and collecting evidence (Member 1)..."):
                profile = api.resolve(name.strip())
                api.collect(profile)
            inp = adapter.from_member1(api, profile)
        else:
            inp = adapter.from_handover(name.strip())
        for ev in pipeline.stream(inp):
            if ev["stage"] == "result":
                bundle = ev["bundle"]
            else:
                done.append(ev)
                slot.markdown(_tracker(done), unsafe_allow_html=True)
        out = BUNDLE_DIR / bundle["slug"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "bundle.json").write_text(json.dumps(bundle, indent=1, default=str), encoding="utf-8")
        st.success(f"Done. Choose “{bundle['company']}” in the company box at the top.")
    except Exception as e:  # show, do not crash the dashboard
        st.error(f"Run failed: {e}")
