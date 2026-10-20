"""Tab 8: Data quality. Score breakdown, coverage meter, gaps, proxies, glossary."""
import html
import streamlit as st

from .. import charts, data
from ..helpers import show
from ...common import label

TITLE = "Data quality"


def render(b: dict, ctx: dict) -> None:
    k, cov = ctx["k"], b["coverage"]
    st.subheader("How much should you trust this?")
    a, c = st.columns(2)
    sc = data.score_contributions(b)
    with a:
        if sc["names"]:
            show(charts.component_bars(sc), f"{k}-dq-score")
        else:
            st.info("No score because no finding survived.")
    with c:
        show(charts.coverage_bars(cov.get("components", {})), f"{k}-dq-cov")
    if b.get("score"):
        st.markdown("<div class='rs-card'><div class='rs-kicker'>Why this rating</div><ul>" +
                    "".join(f"<li>{html.escape(x)}</li>" for x in b["score"]["reasoning"]) + "</ul></div>", unsafe_allow_html=True)
    x, y, z = st.columns(3)
    x.metric("Quarters covered", cov.get("quarters_covered", 0))
    y.metric("Peers with data", cov.get("peers_with_data", 0))
    z.metric("Proxies used", len(cov.get("proxies_used", [])))
    if cov.get("metrics_missing"):
        st.warning("Not disclosed or not collected: " + ", ".join(label(m) for m in cov["metrics_missing"]))
    for w in cov.get("warnings", []):
        st.caption("⚠ " + w)
    diff = b["extras"].get("run_diff")
    st.markdown("#### Run-to-run diff")
    st.write(" ".join(diff["changes"]) if diff and diff.get("has_previous") else "No earlier run of this company is stored.")
    if ctx["plain"]:
        st.markdown("#### Plain-language glossary")
        for term, text in data.GLOSSARY.items():
            st.markdown(f"**{term}**: {text}")
