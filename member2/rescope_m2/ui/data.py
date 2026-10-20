"""Pure data preparation for the dashboard: bundles in, plain lists and dicts out (no streamlit, no plotly).
Every chart takes its numbers from here, so charts change with the selected company and are unit-testable."""
from __future__ import annotations
import json
import html
from pathlib import Path
from typing import Optional

from ..common import MetricBook, fmt, label, median, sort_periods, trend

BUNDLE_DIR = Path(__file__).resolve().parents[2] / "data" / "bundles"
WC_METRICS = ["receivable_days", "inventory_days", "payable_days", "cash_conversion_cycle"]
GROWTH_METRICS = ["revenue_growth_yoy", "volume_growth_yoy", "price_mix_growth_yoy", "price_share_of_growth", "gross_margin"]


def list_bundles(folder: Path = BUNDLE_DIR) -> list[dict]:
    out = []
    for p in sorted(Path(folder).glob("*/bundle.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"company": d["company"], "slug": d["slug"], "path": str(p), "label": d.get("label", ""),
                        "rating": (d.get("score") or {}).get("rating", "Weak")})
        except (OSError, ValueError, KeyError):
            continue
    return out


def load_bundle(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def book_of(b: dict) -> MetricBook:
    return MetricBook(b["metrics"], b["company"])


def metric_frame(b: dict, metric: str, peers: Optional[list[str]] = None) -> dict:
    """Aligned series for one metric: company, each peer, peer median, and the industry series if it has this name."""
    bk = book_of(b)
    use = bk.peers if peers is None else [p for p in peers if p in bk.peers]
    pers = sort_periods([p for e in [bk.company] + use for p, _ in bk.series(e, metric)])
    pick = lambda e: dict(bk.series(e, metric))
    co = pick(bk.company)
    peer_vals = {e: [pick(e).get(p) for p in pers] for e in use}
    med = []
    for p in pers:
        v = [pick(e).get(p) for e in use if pick(e).get(p) is not None]
        med.append(median(v))
    ind = bk.series("industry", metric) if "industry" in bk.data else []
    return {"metric": metric, "label": label(metric), "periods": pers, "company": [co.get(p) for p in pers],
            "peers": peer_vals, "peer_median": med, "industry": ind,
            "has_proxy": bk.has_proxy(bk.company, metric)}


def available(b: dict, wanted: list[str]) -> list[str]:
    bk = book_of(b)
    return [m for m in wanted if len(bk.values(bk.company, m)) >= 3]


def growth_split(b: dict) -> dict:
    bk = book_of(b)
    pers = sort_periods([p for m in ("volume_growth_yoy", "price_mix_growth_yoy", "revenue_growth_yoy")
                         for p, _ in bk.series(bk.company, m)])
    g = lambda m: dict(bk.series(bk.company, m))
    v, pm, rv, sh = g("volume_growth_yoy"), g("price_mix_growth_yoy"), g("revenue_growth_yoy"), g("price_share_of_growth")
    return {"periods": pers, "volume": [v.get(p) for p in pers], "price_mix": [pm.get(p) for p in pers],
            "revenue": [rv.get(p) for p in pers], "price_share": [sh.get(p) for p in pers],
            "has_volume": bool(v), "has_split": bool(v and pm)}


def kpis(b: dict) -> list[dict]:
    """Key-number cards: the metrics that substantiate the finding, plus strength and coverage."""
    cards = []
    for n in (b["discovery"].get("numbers") or [])[:3]:
        d = n["last"] - n["first"]
        arrow = "▲" if d > 0 else "▼" if d < 0 else "■"
        cards.append({"label": n["label"], "value": n["last_display"],
                      "sub": f"{arrow} from {n['first_display']} in {n['first_period']}", "proxy": n["is_proxy"]})
    sc = b.get("score")
    cards.append({"label": "Evidence Strength", "value": sc["rating"] if sc else "Weak",
                  "sub": f"score {sc['total']:.2f}" if sc else "no surviving finding", "proxy": False})
    cards.append({"label": "Data coverage", "value": f"{b['coverage'].get('coverage_score', 0) * 100:.0f}%",
                  "sub": f"{b['coverage'].get('quarters_covered', 0)} quarters, {b['coverage'].get('peers_with_data', 0)} peers", "proxy": False})
    return cards[:5]


def lead_metrics(b: dict) -> list[str]:
    ms = [n["metric"] for n in (b["discovery"].get("numbers") or [])]
    return ms or available(b, WC_METRICS + GROWTH_METRICS)[:2]


def score_contributions(b: dict) -> dict:
    sc = b.get("score")
    if not sc:
        return {"names": [], "values": [], "weights": [], "penalty": 0.0, "total": 0.0}
    names = list(sc["weights"])
    vals = [sc["components"][k] for k in names]
    return {"names": names, "values": vals, "weights": [sc["weights"][k] for k in names],
            "contrib": [round(sc["weights"][k] * sc["components"][k], 4) for k in names],
            "penalty": sc["penalty"], "total": sc["total"]}


def source_mix(b: dict) -> dict:
    ev = b["discovery"].get("evidence") or b["evidence"]
    types: dict[str, int] = {}
    tiers: dict[int, int] = {}
    for e in ev:
        t = e.get("source_type")
        types[t] = types.get(t, 0) + 1
        k = int(e.get("tier", e.get("source_tier", 3)))
        tiers[k] = tiers.get(k, 0) + 1
    return {"types": types, "tiers": dict(sorted(tiers.items()))}


def evidence_rows(b: dict) -> list[dict]:
    rows = []
    for e in b["discovery"].get("evidence", []):
        rows.append({"id": e["id"], "stance": e["stance"], "type": e["source_type"], "tier": e["tier"], "role": e["role"],
                     "date": e["date"], "period": e.get("period") or "", "locator": e.get("locator") or "",
                     "independent": "yes" if e["independent"] else "no", "title": e["title"], "url": e["url"]})
    return rows


def passage_html(item: dict) -> str:
    text, hl = item.get("passage", ""), item.get("highlight", "")
    esc = html.escape(text)
    if hl and hl in text:
        esc = esc.replace(html.escape(hl), f"<mark>{html.escape(hl)}</mark>", 1)
    return esc


def hypothesis_rows(b: dict) -> list[dict]:
    runs = {r["hypothesis_id"]: r for r in b.get("skeptic_runs", [])}
    out = []
    for h in b["plan"]["hypotheses"]:
        r = runs.get(h["id"])
        out.append({"id": h["id"], "angle": h["angle_label"], "statement": h["statement"], "support": h["support"],
                    "coverage": h["coverage"], "rank_score": h["rank_score"], "verdict": r["verdict"] if r else "not reached",
                    "lead": h["id"] == b["discovery"].get("hypothesis_id")})
    return out


def verdict_counts(b: dict) -> dict:
    c = {"company_specific": 0, "mixed": 0, "sector_wide": 0, "insufficient": 0}
    for comp in b["benchmark"].get("comparisons", []):
        c[comp.get("verdict", "insufficient")] = c.get(comp.get("verdict", "insufficient"), 0) + 1
    return c


def benchmark_rows(b: dict) -> list[dict]:
    rows = []
    for c in b["benchmark"].get("comparisons", []):
        co = c.get("company") or {}
        rows.append({"metric": label(c["metric"]), "company direction": co.get("direction", ""),
                     "peers same direction": f"{c.get('peers_same_direction')}/{c.get('peers_total')}",
                     "verdict": c.get("verdict", ""), "note": c.get("note", "")})
    return rows


def timeline_series(b: dict, metric: str) -> dict:
    fr = metric_frame(b, metric, peers=[])
    cp = next((c for c in b["timeline"]["change_points"] if c["metric"] == metric), None)
    return {"frame": fr, "change_point": cp, "events": b["timeline"]["events"]}


def plain_summary(b: dict) -> list[str]:
    d, sc = b["discovery"], b.get("score")
    if not d.get("hypothesis_id"):
        return ["The tool did not find a pattern it could stand behind with the data available.",
                "That is a result too: it says what is missing instead of guessing."]
    out = [f"The tool found a pattern in {b['company']}'s public numbers: {d.get('hypothesis', '').lower()}.",
           f"It checked this against peers and tried to disprove it. Result: {b['skeptic']['verdict']}.",
           f"Confidence is {sc['rating'].lower()} because {len(sc['independent_types'])} independent kinds of source back it up."]
    if sc.get("cap_reason"):
        out.append(f"It is held below Strong because {sc['cap_reason']}.")
    return out


GLOSSARY = {
    "Receivable days": "How many days, on average, customers take to pay. Rising days can mean looser credit to boost sales.",
    "Price share of growth": "How much of sales growth came from higher prices or mix, rather than selling more units.",
    "Triangulation": "Checking the same fact against more than one independent kind of source.",
    "Falsification condition": "A measurable result that would prove the finding wrong.",
    "Sector-wide": "Peers show the same pattern, so it is probably not about this one company.",
    "Proxy": "A stand-in figure used when the real one is not disclosed. It is always labelled.",
}
