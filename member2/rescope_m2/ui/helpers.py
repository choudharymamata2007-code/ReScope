"""Small streamlit helpers that survive API changes between versions."""
from __future__ import annotations
import html

import pandas as pd
import streamlit as st


def show(fig, key: str) -> None:
    try:
        st.plotly_chart(fig, width="stretch", key=key)
    except TypeError:  # older streamlit
        st.plotly_chart(fig, use_container_width=True, key=key)


def table(rows, key: str | None = None, height: int | None = None) -> None:
    df = pd.DataFrame(rows)
    kw = {"hide_index": True, "key": key} if key else {"hide_index": True}
    if height:
        kw["height"] = height
    try:
        st.dataframe(df, width="stretch", **kw)
    except TypeError:
        st.dataframe(df, use_container_width=True, **kw)


def card(kicker: str, body_html: str) -> str:
    return f"<div class='rs-card'><div class='rs-kicker'>{html.escape(kicker)}</div>{body_html}</div>"


def kpi_card(c: dict) -> str:
    proxy = " <span class='rs-note'>(proxy)</span>" if c.get("proxy") else ""
    return card(c["label"], f"<div class='rs-kpi'>{html.escape(str(c['value']))}{proxy}</div><div class='rs-sub'>{html.escape(c['sub'])}</div>")


def verdict_span(v: str) -> str:
    cls = {"aligned": "rs-pass", "survived": "rs-pass", "confirmed": "rs-pass", "company_specific": "rs-pass",
           "misaligned": "rs-fail", "rejected": "rs-fail", "reversed": "rs-fail", "sector_wide": "rs-caution",
           "weakened": "rs-caution", "mixed": "rs-caution"}.get(v, "rs-note")
    mark = {"rs-pass": "✔ ", "rs-fail": "✖ ", "rs-caution": "▲ "}.get(cls, "")
    return f"<span class='{cls}'>{mark}{html.escape(v.replace('_', ' '))}</span>"


def html_table(rows: list[dict], cols: list[str], verdict_cols: tuple[str, ...] = ()) -> str:
    head = "".join(f"<th style='text-align:left;padding:6px 10px;border-bottom:2px solid #C9D2DC'>{html.escape(c)}</th>" for c in cols)
    body = ""
    for r in rows:
        cells = ""
        for c in cols:
            v = r.get(c, "")
            cell = verdict_span(str(v)) if c in verdict_cols else html.escape(str(v))
            cells += f"<td style='padding:6px 10px;border-bottom:1px solid #C9D2DC;vertical-align:top'>{cell}</td>"
        body += f"<tr>{cells}</tr>"
    return f"<div style='overflow-x:auto'><table style='border-collapse:collapse;width:100%;font-size:.9rem'><tr>{head}</tr>{body}</table></div>"
