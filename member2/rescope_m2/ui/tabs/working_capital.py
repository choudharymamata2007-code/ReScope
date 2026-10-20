"""Tab 3: Working capital. Receivable, inventory, payable days and the cash conversion cycle."""
import streamlit as st

from .. import charts, data
from ..helpers import show
from ...common import label

TITLE = "Working capital"


def render(b: dict, ctx: dict) -> None:
    k = ctx["k"]
    ms = data.available(b, data.WC_METRICS)
    st.subheader("Are customers paying more slowly, or stock building up?")
    if not ms:
        st.warning("No working-capital metrics were disclosed for this company.")
        return
    pick = st.radio("Metric", ms, format_func=label, horizontal=True, key=f"{k}-wc-pick")
    cp = next((c["period"] for c in b["timeline"]["change_points"] if c["metric"] == pick), None)
    show(charts.line_compare(data.metric_frame(b, pick), change_period=cp, height=400), f"{k}-wc-main")
    st.caption("Dark blue = company, dashed = peer median, light lines = individual peers. Dotted line marks the detected change point.")
    others = [m for m in ms if m != pick][:3]
    for col, m in zip(st.columns(len(others) or 1), others):
        with col:
            show(charts.line_compare(data.metric_frame(b, m), height=260, show_peers=False), f"{k}-wc-mini-{m}")
