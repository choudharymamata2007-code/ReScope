"""ReScope dashboard.  streamlit run dashboard.py
Top bar with the company selector, then one tab per section. Every chart reads the selected company's bundle."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import streamlit as st

from rescope_m2.ui import data, theme
from rescope_m2.ui.tabs import evidence, growth, overview, peers, quality, reasoning, run, timeline, working_capital

st.set_page_config(page_title="ReScope", page_icon="◈", layout="wide", initial_sidebar_state="collapsed")
st.markdown(theme.CSS, unsafe_allow_html=True)

TABS = [overview, growth, working_capital, peers, timeline, evidence, reasoning, quality, run]


def main() -> None:
    bundles = data.list_bundles()
    st.markdown("<div class='rs-top'><div class='rs-brand'>ReScope<small>Evidence-backed discovery</small></div>"
                "<span class='rs-chip'>Research findings, not investment advice</span></div>", unsafe_allow_html=True)
    if not bundles:
        st.warning("No company bundles yet. Run `python scripts/make_demo_bundles.py` for the fictional demo set, "
                   "or use the Run a company tab.")
        ctx = {"k": "none", "plain": False}
        st.tabs([run.TITLE])[0].write("")
        return
    c1, c2, c3 = st.columns([3, 1.2, 1.2])
    pick = c1.selectbox("Company", range(len(bundles)), format_func=lambda i: f"{bundles[i]['company']}  ·  {bundles[i]['rating']}  ·  {bundles[i]['label']}", key="company")
    plain = c2.toggle("Plain language", key="plain")
    b = data.load_bundle(bundles[pick]["path"])
    c3.caption(f"Generated {b['generated_at']}")
    ctx = {"k": b["slug"], "plain": plain}
    for tab, mod in zip(st.tabs([m.TITLE for m in TABS]), TABS):
        with tab:
            mod.render(b, ctx)
    st.markdown("<div class='rs-foot'>ATMOS 2026 · BITS Pilani Hyderabad Campus · Research findings for a human to verify; not investment advice. "
                "Demo companies are fictional and illustrative.</div>", unsafe_allow_html=True)


main()
