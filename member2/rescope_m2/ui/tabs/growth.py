"""Tab 2: Growth quality. Price vs volume split and gross margin."""
import streamlit as st

from .. import charts, data
from ..helpers import show, table
from ...common import fmt, label

TITLE = "Growth quality"


def render(b: dict, ctx: dict) -> None:
    k = ctx["k"]
    g = data.growth_split(b)
    st.subheader("Is growth coming from volume or from price?")
    if not g["periods"]:
        st.warning("Growth metrics were not disclosed or collected for this company. Coverage warnings explain what is missing.")
    else:
        show(charts.growth_bars(g), f"{k}-gq-bars")
        if g["has_split"]:
            show(charts.price_share_line(g), f"{k}-gq-share")
        else:
            st.info("A volume / price split is not available for this company, so only the disclosed series are drawn. "
                    "Nothing is estimated.")
    ms = [m for m in ("revenue_growth_yoy", "gross_margin") if m in data.available(b, ["revenue_growth_yoy", "gross_margin"])]
    cols = st.columns(len(ms) or 1)
    for col, m in zip(cols, ms):
        with col:
            show(charts.line_compare(data.metric_frame(b, m)), f"{k}-gq-{m}")
    with st.expander("Series with source locators"):
        bk = data.book_of(b)
        rows = [{"metric": label(m), "period": p["period"], "value": fmt(m, p["value"]), "locator": p.get("locator", ""), "proxy": p.get("is_proxy", False)}
                for m in data.available(b, data.GROWTH_METRICS) for p in bk.points(bk.company, m)]
        table(rows, key=f"{k}-gq-tbl", height=260)
