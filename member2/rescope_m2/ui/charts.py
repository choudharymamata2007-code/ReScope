"""Plotly figure builders. Each takes plain data from ui/data.py and returns a figure in the palette."""
from __future__ import annotations
import plotly.graph_objects as go

from ..common import METRIC_KIND, label
from .theme import BAD, BLUE, GOOD, MIST, NAVY, PLOT_FONT, SNOW, STEEL, WARN

TINTS = [NAVY, BLUE, STEEL, "#4D6597", "#A4B5CD", MIST, "#8996B0"]


def _fmt_axis(metric: str) -> dict:
    kind = METRIC_KIND.get(metric, "num")
    return {"tickformat": ".0%" if kind in ("pct", "share") else ",.0f" if kind == "days" else ",.1f"}


def style(fig: go.Figure, height: int = 340, title: str | None = None, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=44 if title else 16, b=10), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF", font=dict(family=PLOT_FONT, color=NAVY, size=12),
        title=dict(text=title, x=0.01, font=dict(size=15)) if title else None,
        legend=dict(orientation="h", y=1.12, x=0) if legend else None, showlegend=legend,
        hoverlabel=dict(bgcolor=NAVY, font_color=SNOW), transition=dict(duration=400, easing="cubic-in-out"))
    fig.update_xaxes(showgrid=False, linecolor=MIST)
    fig.update_yaxes(gridcolor=MIST, zeroline=True, zerolinecolor=STEEL, linecolor=MIST)
    return fig


def line_compare(fr: dict, show_peers: bool = True, change_period: str | None = None, height: int = 340,
                 title: str | None = None) -> go.Figure:
    """Company vs each peer vs peer median (and the industry series when it carries this metric)."""
    fig = go.Figure()
    if show_peers:
        for i, (name, vals) in enumerate(fr["peers"].items()):
            fig.add_trace(go.Scatter(x=fr["periods"], y=vals, name=name, mode="lines",
                                     line=dict(color=STEEL, width=1.2), opacity=.7, connectgaps=True))
    if fr["peers"] and any(v is not None for v in fr["peer_median"]):
        fig.add_trace(go.Scatter(x=fr["periods"], y=fr["peer_median"], name="Peer median", mode="lines",
                                 line=dict(color=NAVY, width=2, dash="dash"), connectgaps=True))
    fig.add_trace(go.Scatter(x=fr["periods"], y=fr["company"], name="Company", mode="lines+markers",
                             line=dict(color=BLUE, width=3.2), marker=dict(size=7), connectgaps=True))
    if change_period and change_period in fr["periods"]:
        fig.add_shape(type="line", x0=change_period, x1=change_period, y0=0, y1=1, yref="paper",
                      line=dict(color=NAVY, width=1.5, dash="dot"))
        fig.add_annotation(x=change_period, y=1, yref="paper", text="change point", showarrow=False, yshift=10,
                           font=dict(color=NAVY, size=11))
    fig.update_yaxes(**_fmt_axis(fr["metric"]))
    return style(fig, height, title or fr["label"] + (" (proxy)" if fr.get("has_proxy") else ""))


def growth_bars(g: dict, height: int = 360) -> go.Figure:
    fig = go.Figure()
    if g["has_split"]:
        fig.add_trace(go.Bar(x=g["periods"], y=g["volume"], name="Volume", marker_color=BLUE))
        fig.add_trace(go.Bar(x=g["periods"], y=g["price_mix"], name="Price / mix", marker_color=STEEL))
        fig.update_layout(barmode="relative")
    elif g["has_volume"]:
        fig.add_trace(go.Bar(x=g["periods"], y=g["volume"], name="Volume", marker_color=BLUE))
    if any(v is not None for v in g["revenue"]):
        fig.add_trace(go.Scatter(x=g["periods"], y=g["revenue"], name="Revenue growth", mode="lines+markers",
                                 line=dict(color=NAVY, width=2.5), marker=dict(size=6)))
    fig.update_yaxes(tickformat=".0%")
    return style(fig, height, "Where growth comes from: volume vs price/mix")


def price_share_line(g: dict, height: int = 300) -> go.Figure:
    fig = go.Figure(go.Scatter(x=g["periods"], y=g["price_share"], mode="lines+markers", name="Price share of growth",
                               line=dict(color=BLUE, width=3), marker=dict(size=7), connectgaps=True))
    fig.add_shape(type="line", x0=0, x1=1, xref="paper", y0=1, y1=1, line=dict(color=NAVY, dash="dot", width=1))
    fig.update_yaxes(tickformat=".0%")
    return style(fig, height, "Price share of growth (100% = all growth from price/mix)", legend=False)


def heatmap(h: dict, height: int | None = None) -> go.Figure:
    fig = go.Figure(go.Heatmap(z=h["z"], x=h["entities"], y=h["labels"], text=h["text"], texttemplate="%{text}",
                               colorscale=[[0, MIST], [0.5, SNOW], [1, BLUE]], zmid=0, showscale=False,
                               hovertemplate="%{y}<br>%{x}<br>%{text}<extra></extra>", xgap=3, ygap=3))
    fig.update_xaxes(side="top", tickangle=-20)
    return style(fig, height or 90 + 46 * len(h["labels"]), "Peer heatmap: change over the window (darker = rose more than the group)", legend=False)


def gauge(total: float, rating: str, height: int = 260) -> go.Figure:
    fig = go.Figure(go.Indicator(mode="gauge+number", value=total, number=dict(valueformat=".2f", font=dict(color=NAVY)),
                                 gauge=dict(axis=dict(range=[0, 1], tickcolor=NAVY), bar=dict(color=NAVY, thickness=.28),
                                            steps=[dict(range=[0, .5], color=MIST), dict(range=[.5, .75], color=STEEL),
                                                   dict(range=[.75, 1], color=BLUE)],
                                            threshold=dict(line=dict(color=NAVY, width=3), value=total))))
    fig.update_layout(height=height, margin=dict(l=20, r=20, t=40, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      font=dict(family=PLOT_FONT, color=NAVY), title=dict(text=f"Evidence score: {rating}", x=.02, font=dict(size=15)),
                      transition=dict(duration=600))
    return fig


def component_bars(c: dict, height: int = 300) -> go.Figure:
    names = [n.replace("_", " ").capitalize() for n in c["names"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=names, x=c["weights"], orientation="h", name="Maximum", marker_color=MIST))
    fig.add_trace(go.Bar(y=names, x=c["contrib"], orientation="h", name="Earned", marker_color=BLUE,
                         text=[f"{v:.2f}" for v in c["contrib"]], textposition="inside", textfont=dict(color=SNOW)))
    fig.update_layout(barmode="overlay")
    fig.update_yaxes(autorange="reversed")
    return style(fig, height, f"Score breakdown (total {c['total']:.2f}, penalty {c['penalty']:.2f})")


def donut(types: dict, height: int = 300) -> go.Figure:
    fig = go.Figure(go.Pie(labels=list(types), values=list(types.values()), hole=.58, marker=dict(colors=TINTS, line=dict(color="#fff", width=2)),
                           textinfo="label+value", sort=False))
    return style(fig, height, "Evidence by source type", legend=False)


def tier_bars(tiers: dict, height: int = 300) -> go.Figure:
    fig = go.Figure(go.Bar(x=[f"Tier {k}" for k in tiers], y=list(tiers.values()), marker_color=[BLUE, STEEL, STEEL, MIST, MIST][:len(tiers)]))
    return style(fig, height, "Evidence by reliability tier (1 = most reliable)", legend=False)


def triangulation_bars(clusters: list[dict], height: int = 320) -> go.Figure:
    cl = clusters[:8]
    fig = go.Figure(go.Bar(y=[c["representative"][:60] + "…" if len(c["representative"]) > 60 else c["representative"] for c in cl],
                           x=[c["independent_count"] for c in cl], orientation="h",
                           marker_color=[BLUE if c["meets_triangulation"] else MIST for c in cl],
                           text=["meets rule" if c["meets_triangulation"] else "needs more" for c in cl], textposition="auto"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="independent source types", dtick=1)
    return style(fig, height, "Claim clusters: independent source types (2+ needed, one from outside the company)", legend=False)


def hypothesis_bars(rows: list[dict], height: int = 300) -> go.Figure:
    colors = [BLUE if r["lead"] else STEEL for r in rows]
    fig = go.Figure(go.Bar(y=[r["id"].replace("_", " ") for r in rows], x=[r["support"] for r in rows], orientation="h",
                           marker_color=colors, text=[r["verdict"] for r in rows], textposition="auto"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, 1], tickformat=".0%")
    return style(fig, height, "Hypotheses: how well the numbers fit each prediction (lead in dark blue)", legend=False)


def stage_bars(events: list[dict], height: int = 300) -> go.Figure:
    fig = go.Figure(go.Bar(x=[e["name"] for e in events], y=[e["seconds"] for e in events], marker_color=BLUE))
    fig.update_xaxes(tickangle=-35)
    fig.update_yaxes(title="seconds")
    return style(fig, height, "Time per pipeline stage", legend=False)


def verdict_bar(counts: dict, height: int = 280) -> go.Figure:
    names = ["company_specific", "mixed", "sector_wide", "insufficient"]
    fig = go.Figure(go.Bar(x=[n.replace("_", " ") for n in names], y=[counts.get(n, 0) for n in names],
                           marker_color=[BLUE, STEEL, NAVY, MIST]))
    fig.update_yaxes(dtick=1)
    return style(fig, height, "Company-vs-sector verdict across metrics", legend=False)


def coverage_bars(components: dict, height: int = 280) -> go.Figure:
    names = [k.replace("_", " ").capitalize() for k in components]
    vals = list(components.values())
    fig = go.Figure(go.Bar(y=names, x=vals, orientation="h", marker_color=[BLUE if v >= .67 else STEEL if v >= .34 else MIST for v in vals],
                           text=[f"{v * 100:.0f}%" for v in vals], textposition="auto"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, 1], tickformat=".0%")
    return style(fig, height, "Data coverage meter", legend=False)


def drift_lines(d: dict, height: int = 300) -> go.Figure:
    fig = go.Figure()
    for i, (theme, vals) in enumerate(d["themes"].items()):
        fig.add_trace(go.Scatter(x=d["periods"], y=vals, name=theme, mode="lines+markers", line=dict(color=TINTS[i % len(TINTS)], width=2)))
    fig.update_yaxes(title="mentions per 1,000 words")
    return style(fig, height, "Management language drift")


def timeline_chart(ts: dict, height: int = 380) -> go.Figure:
    fr, cp = ts["frame"], ts["change_point"]
    fig = line_compare(fr, show_peers=False, change_period=cp["period"] if cp else None, height=height,
                       title=f"{fr['label']} with dated events")
    ys = [v for v in fr["company"] if v is not None]
    if ys:
        lo = min(ys) - (max(ys) - min(ys)) * 0.12
        kinds = {"claim": (STEEL, "circle"), "disclosure": (WARN, "diamond"), "change_point": (NAVY, "star")}
        for kind, (color, sym) in kinds.items():
            ev = [e for e in ts["events"] if e["kind"] == kind and e.get("period") in fr["periods"]]
            if ev:
                fig.add_trace(go.Scatter(x=[e["period"] for e in ev], y=[lo] * len(ev), mode="markers", name=kind.replace("_", " "),
                                         marker=dict(color=color, size=10, symbol=sym), text=[e["label"][:120] for e in ev],
                                         hovertemplate="%{x}<br>%{text}<extra></extra>"))
    return fig
