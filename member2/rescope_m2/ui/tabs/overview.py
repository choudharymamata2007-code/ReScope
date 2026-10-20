"""Tab 1: Overview. Discovery banner, why it matters, key numbers, headline charts, counterargument and falsification."""
import html
import streamlit as st

from .. import charts, data
from ..helpers import card, kpi_card, show
from ..theme import rating_badge

TITLE = "Overview"


def render(b: dict, ctx: dict) -> None:
    d, sc, k = b["discovery"], b.get("score"), ctx["k"]
    badge = rating_badge(sc["rating"], sc["total"]) if sc else rating_badge("Weak")
    st.markdown(
        f"<div class='rs-banner'><div class='rs-kicker'>The discovery · {html.escape(b['company'])}</div>"
        f"<h2>{html.escape(d['discovery'])}</h2><div style='display:flex;gap:14px;align-items:center;flex-wrap:wrap'>{badge}"
        f"<span class='rs-chip'>{html.escape(b.get('label', ''))}</span><span class='rs-chip'>{html.escape(b['profile'].get('archetype', ''))}</span></div>"
        f"<p class='rs-note' style='margin-top:12px'>{html.escape(d['disclaimer'])}</p></div>", unsafe_allow_html=True)
    if ctx["plain"]:
        st.info(" ".join(data.plain_summary(b)))
    st.write("")
    cards = data.kpis(b)
    for col, c in zip(st.columns(len(cards)), cards):
        col.markdown(kpi_card(c), unsafe_allow_html=True)
    st.write("")
    left, right = st.columns([3, 2])
    bullets = "".join(f"<li style='margin-bottom:6px'>{html.escape(x)}</li>" for x in d["why_it_matters"])
    left.markdown(card("Why it matters", f"<ul style='padding-left:18px;margin:8px 0 0 0'>{bullets}</ul>"), unsafe_allow_html=True)
    if sc:
        with right:
            show(charts.gauge(sc["total"], sc["rating"]), f"{k}-ov-gauge")
    metrics = data.lead_metrics(b)[:2]
    cp = (b["timeline"].get("primary_change_point") or {}).get("period")
    for col, m in zip(st.columns(len(metrics) or 1), metrics):
        with col:
            show(charts.line_compare(data.metric_frame(b, m), change_period=cp), f"{k}-ov-{m}")
    c1, c2 = st.columns(2)
    ca, fa = d.get("counterargument") or {}, d.get("falsification") or {}
    c1.markdown(f"<div class='rs-box counter'><div class='rs-kicker'>Counterargument</div><h4>{html.escape(ca.get('title', 'None'))}</h4>"
                f"<p>{html.escape(ca.get('text', ''))}</p></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='rs-box falsify'><div class='rs-kicker'>Falsification condition</div><h4>What would prove this wrong</h4>"
                f"<p>{html.escape(fa.get('statement', ''))}</p></div>", unsafe_allow_html=True)
