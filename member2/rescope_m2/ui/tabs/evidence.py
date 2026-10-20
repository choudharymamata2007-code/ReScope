"""Tab 6: Evidence trail with click-through to the source passage."""
import html
import streamlit as st

from .. import charts, data
from ..helpers import show, table

TITLE = "Evidence"


def render(b: dict, ctx: dict) -> None:
    k = ctx["k"]
    st.subheader("Every claim traces to a document, date and passage")
    mix = data.source_mix(b)
    a, c, d = st.columns(3)
    with a:
        show(charts.donut(mix["types"]), f"{k}-ev-donut")
    with c:
        show(charts.tier_bars(mix["tiers"]), f"{k}-ev-tier")
    with d:
        if b["triangulation"]:
            show(charts.triangulation_bars(b["triangulation"], 300), f"{k}-ev-tri")
    items = b["discovery"].get("evidence", [])
    if not items:
        st.info("No evidence is shown because no finding survived.")
        return
    left, right = st.columns([3, 2])
    with left:
        stance = st.radio("Show", ["all", "supports", "counter"], horizontal=True, key=f"{k}-ev-stance")
        rows = [r for r in data.evidence_rows(b) if stance == "all" or r["stance"] == stance]
        table(rows, key=f"{k}-ev-table", height=360)
    with right:
        shown = [e for e in items if stance == "all" or e["stance"] == stance] or items
        idx = st.selectbox("Open a source passage", range(len(shown)), key=f"{k}-ev-pick",
                           format_func=lambda i: f"{shown[i]['source_type']} · {shown[i].get('period') or shown[i]['date'] or '-'} · {shown[i]['title'][:42]}")
        e = shown[idx]
        st.markdown(f"<div class='rs-card'><div class='rs-kicker'>{html.escape(e['stance'])} · tier {e['tier']} · {html.escape(e['role'])}</div>"
                    f"<h4 style='margin:6px 0'>{html.escape(e['title'])}</h4>"
                    f"<div class='rs-sub'>Date {html.escape(e['date'] or 'n/a')} · locator {html.escape(e.get('locator') or 'n/a')} · "
                    f"{'independent' if e['independent'] else 'not independent'}</div>"
                    f"<div class='rs-passage' style='margin:10px 0'>{data.passage_html(e)}</div>"
                    f"<a href='{html.escape(e['url'], quote=True)}' target='_blank'>Open source document</a>"
                    f"<div class='rs-note'>Why it is here: {html.escape(e.get('why', ''))}</div></div>", unsafe_allow_html=True)
