"""Tab 7: Reasoning. Pipeline steps, hypotheses, skeptic, contradictions, say-vs-do, why-not."""
import html
import streamlit as st

from .. import charts, data
from ..helpers import html_table, show, verdict_span
from ...common import label

TITLE = "Reasoning"


def render(b: dict, ctx: dict) -> None:
    k = ctx["k"]
    st.subheader("How the agent reached (or refused) a finding")
    steps = "".join(f"<div class='rs-step'><b>{e['stage']}</b><div><strong>{html.escape(e['name'])}</strong>"
                    f"<div class='rs-sub'>{html.escape(e['summary'])}</div></div></div>" for e in b["events"])
    a, c = st.columns([3, 2])
    a.markdown(f"<div class='rs-card'><div class='rs-kicker'>12-stage pipeline</div>{steps}</div>", unsafe_allow_html=True)
    with c:
        show(charts.stage_bars(b["events"]), f"{k}-rs-stages")
    st.markdown("#### Competing hypotheses")
    rows = data.hypothesis_rows(b)
    if rows:
        show(charts.hypothesis_bars(rows), f"{k}-rs-hyp")
        st.markdown(html_table([{"hypothesis": r["statement"], "angle": r["angle"], "support": f"{r['support']:.0%}", "skeptic": r["verdict"]}
                                for r in rows], ["hypothesis", "angle", "support", "skeptic"], ("skeptic",)), unsafe_allow_html=True)
    sk = b.get("skeptic")
    if sk:
        st.markdown("#### Skeptic rounds")
        for r in sk["rounds"]:
            with st.expander(f"Round {r['round']}: {r['verdict']} (sector: {r['sector'].replace('_', ' ')})", expanded=r["round"] == 1):
                st.markdown("**Predictions**\n" + "\n".join(f"- {p}" for p in r["predictions"]))
                st.markdown("**Counter-queries sent to collection**\n" + "\n".join(f"- {q}" for q in r["queries"]))
                st.write(f"Counter-evidence found: {r['counter_found']} (independent: {r['independent_counter']}). " + "; ".join(r["reasons"]))
    ca = b.get("counterargument")
    if ca and ca.get("others"):
        with st.expander("Other alternative explanations considered"):
            for o in ca["others"]:
                st.markdown(f"**{o['title']}** (strength {o['strength']}): {o['text']}")
    mon = b["extras"].get("falsification_monitor")
    if mon:
        st.markdown(f"#### Falsification monitor: {verdict_span(mon['status'])}", unsafe_allow_html=True)
    if b["contradictions"]:
        st.markdown("#### Contradictions")
        for x in b["contradictions"]:
            st.markdown(f"<div class='rs-box counter' style='margin-bottom:8px'><div class='rs-kicker'>{html.escape(x['kind'].replace('_', ' '))} · {html.escape(str(x['topic']))}</div>"
                        f"<p><em>“{html.escape(x['quote_a'])}”</em><br/><em>“{html.escape(x['quote_b'])}”</em></p>"
                        f"<div class='rs-note'>{html.escape(x['detail'])}</div></div>", unsafe_allow_html=True)
    if b["say_vs_do"]:
        st.markdown("#### Say vs do")
        st.markdown(html_table([{"management said": r["statement"], "metric": label(r["metric"]), "verdict": r["verdict"], "detail": r["detail"]}
                                for r in b["say_vs_do"]], ["management said", "metric", "verdict", "detail"], ("verdict",)), unsafe_allow_html=True)
    if b["disclosure_changes"]:
        st.markdown("#### Disclosure changes")
        st.markdown(html_table([{"kind": d["kind"].replace("_", " "), "detail": d["detail"]} for d in b["disclosure_changes"]], ["kind", "detail"]), unsafe_allow_html=True)
    wn = b["extras"]["why_not"]
    if wn:
        st.markdown("#### Why not? Hypotheses that did not become the finding")
        st.markdown(html_table(wn, ["statement", "outcome", "reason"]), unsafe_allow_html=True)
    dr = b["extras"]["language_drift"]
    if dr["periods"]:
        show(charts.drift_lines(dr), f"{k}-rs-drift")
