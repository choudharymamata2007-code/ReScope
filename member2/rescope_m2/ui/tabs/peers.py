"""Tab 4: Peers and industry. Heatmap, company-vs-sector verdicts, overlay chart."""
import streamlit as st

from .. import charts, data
from ..helpers import show, table
from ...common import label

TITLE = "Peers & industry"


def render(b: dict, ctx: dict) -> None:
    k = ctx["k"]
    st.subheader("Company story or sector story?")
    peers = data.book_of(b).peers
    h = b["extras"]["peer_heatmap"]
    if h["metrics"] and len(h["entities"]) > 1:
        show(charts.heatmap(h), f"{k}-pe-heat")
    else:
        st.info("Too few peers with data for a heatmap.")
    left, right = st.columns([2, 3])
    with left:
        show(charts.verdict_bar(data.verdict_counts(b)), f"{k}-pe-verdict")
        st.caption(f"Overall benchmark verdict: **{b['benchmark'].get('overall', 'insufficient').replace('_', ' ')}**")
    with right:
        ms = data.available(b, data.WC_METRICS + data.GROWTH_METRICS)
        if ms:
            m = st.selectbox("Metric", ms, format_func=label, key=f"{k}-pe-metric")
            chosen = st.multiselect("Peers shown", peers, default=peers, key=f"{k}-pe-peers")
            show(charts.line_compare(data.metric_frame(b, m, chosen), height=320), f"{k}-pe-lines")
    table(data.benchmark_rows(b), key=f"{k}-pe-bench")
    ind = data.book_of(b).data.get("industry", {})
    if ind:
        name = next(iter(ind))
        show(charts.line_compare(data.metric_frame(b, name, []), show_peers=False, height=260, title=f"Industry series: {label(name)}"), f"{k}-pe-ind")
