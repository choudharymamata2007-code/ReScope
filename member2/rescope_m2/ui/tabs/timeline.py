"""Tab 5: Timeline. When did the story change?"""
import streamlit as st

from .. import charts, data
from ..helpers import show, table
from ...common import label

TITLE = "Timeline"


def render(b: dict, ctx: dict) -> None:
    k = ctx["k"]
    st.subheader("When did the trend turn?")
    ms = data.available(b, data.WC_METRICS + data.GROWTH_METRICS)
    if not ms:
        st.warning("No series long enough to date a change.")
        return
    cp = b["timeline"].get("primary_change_point")
    default = ms.index(cp["metric"]) if cp and cp["metric"] in ms else 0
    m = st.selectbox("Metric", ms, index=default, format_func=label, key=f"{k}-tl-metric")
    ts = data.timeline_series(b, m)
    show(charts.timeline_chart(ts), f"{k}-tl-chart")
    if ts["change_point"]:
        st.success(ts["change_point"]["text"])
    else:
        st.info("No clear change point in this series.")
    kinds = st.multiselect("Event types", ["change_point", "claim", "disclosure"], default=["change_point", "disclosure", "claim"], key=f"{k}-tl-kinds")
    rows = [{"date": e["date"], "period": e.get("period") or "", "type": e["kind"].replace("_", " "), "event": e["label"], "source": e.get("url") or ""}
            for e in b["timeline"]["events"] if e["kind"] in kinds]
    table(rows, key=f"{k}-tl-events", height=300)
