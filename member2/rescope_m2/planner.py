"""Task 2.3: angle planner and hypothesis generator.

Generic angle library (no company names). Hypotheses are TESTED in code against the metric series, so the
ranking reflects what the numbers show, not what a model prefers. A model may add extra hypotheses; they are
accepted only when every metric they name exists in the data."""
from __future__ import annotations
from typing import Optional

from . import llm
from .common import MetricBook, label, trend

ALL = None  # applies to every archetype

ANGLES = [
    {"id": "growth_quality", "label": "Growth quality", "archetypes": ALL, "templates": [
        {"id": "price_led", "statement": "Reported growth is increasingly price-led while underlying volume weakens",
         "tests": [{"metric": ["volume_growth_yoy"], "expect": "down"},
                   {"metric": ["price_share_of_growth", "price_mix_growth_yoy"], "expect": "up"}],
         "matters": ["Price-led growth is harder to sustain than volume-led growth and can hide weakening demand."]}]},
    {"id": "working_capital", "label": "Working capital", "archetypes": ALL, "templates": [
        {"id": "channel_stretch",
         "statement": "Growth is being supported by looser distributor credit: receivable days rise while volume growth fades",
         "tests": [{"metric": ["receivable_days"], "expect": "up"},
                   {"metric": ["volume_growth_yoy", "revenue_growth_yoy"], "expect": "down"}],
         "matters": ["Receivable days are in the filings before they reach the news, so lenders and suppliers can see stretch early.",
                     "A volume-led growth story should not need longer payment terms."]},
        {"id": "inventory_buildup", "statement": "Inventory is building faster than sales",
         "tests": [{"metric": ["inventory_days"], "expect": "up"},
                   {"metric": ["revenue_growth_yoy", "volume_growth_yoy"], "expect": "down_or_flat"}],
         "matters": ["Inventory piling up ahead of weaker sales often precedes discounting and margin pressure."]},
        {"id": "cash_cycle", "statement": "The cash conversion cycle is lengthening",
         "tests": [{"metric": ["cash_conversion_cycle"], "expect": "up"},
                   {"metric": ["receivable_days", "inventory_days"], "expect": "up"}],
         "matters": ["A longer cash cycle ties up more money for the same sales."]}]},
    {"id": "margin_cost", "label": "Margin and cost", "archetypes": ALL, "templates": [
        {"id": "margin_squeeze", "statement": "Gross margin is eroding even though growth is reported as healthy",
         "tests": [{"metric": ["gross_margin"], "expect": "down"},
                   {"metric": ["revenue_growth_yoy"], "expect": "up_or_flat"}],
         "matters": ["Growth that costs margin changes how durable the earnings are."]}]},
    {"id": "distribution_shift", "label": "Distribution shift", "archetypes": ["packaged_staples"], "templates": [
        {"id": "mix_shift", "statement": "Sales are shifting between channels or segments",
         "tests": [{"metric": ["mix_*"], "expect": "up"}],
         "matters": ["A shift in channel or segment mix changes margins and receivable risk."]}]},
    {"id": "retail_productivity", "label": "Retail productivity",
     "archetypes": ["organised_retail", "discretionary_durables"], "templates": [
        {"id": "growth_bought", "statement": "Growth is being bought with inventory and margin",
         "tests": [{"metric": ["revenue_growth_yoy"], "expect": "up_or_flat"},
                   {"metric": ["inventory_days"], "expect": "up"},
                   {"metric": ["gross_margin"], "expect": "down"}],
         "matters": ["Rising inventory with falling margin can mean sales are being pushed, not pulled."]}]},
]

FALLBACK_ARCHETYPE_ANGLES = {"unclassified": None}


def _resolve(book: MetricBook, entity: str, alternatives: list[str]) -> Optional[str]:
    for alt in alternatives:
        if alt.endswith("*"):
            for m in book.metric_names(entity):
                if m.startswith(alt[:-1]) and len(book.values(entity, m)) >= 4:
                    return m
        elif len(book.values(entity, alt)) >= 4:
            return alt
    return None


def _score_test(direction: str, expect: str) -> float:
    if direction == "insufficient":
        return 0.0
    if expect.endswith("_or_flat"):
        want = expect.split("_")[0]
        return 1.0 if direction in (want, "flat") else 0.0
    if direction == expect:
        return 1.0
    return 0.25 if direction == "flat" else 0.0


def test_hypothesis(h: dict, book: MetricBook) -> dict:
    """Resolve each test to an available metric, measure its trend, and score the hypothesis."""
    results, wsum, total = [], 0.0, 0.0
    for t in h["tests"]:
        m = _resolve(book, book.company, t["metric"])
        if m is None:
            results.append({"metric": None, "wanted": t["metric"], "expect": t["expect"], "available": False})
            continue
        tr = trend(book.values(book.company, m))
        s = _score_test(tr["direction"], t["expect"])
        results.append({"metric": m, "expect": t["expect"], "available": True, "direction": tr["direction"],
                        "first": tr["first"], "last": tr["last"], "score": s,
                        "is_proxy": book.has_proxy(book.company, m)})
        wsum += 1
        total += s
    avail = [r for r in results if r["available"]]
    coverage = len(avail) / len(results) if results else 0.0
    support = total / wsum if wsum else 0.0
    # the first test defines the hypothesis: without its metric the hypothesis cannot be judged
    core_missing = bool(results) and not results[0]["available"]
    status = "untestable" if (not avail or core_missing) else ("partial" if len(avail) < len(results) else "testable")
    if status == "untestable":
        support = 0.0
    mag = sum(min(abs(trend(book.values(book.company, r["metric"]))["relative_change"] or 0), 2.0) for r in avail)
    return {**h, "results": results, "support": round(support, 3), "coverage": round(coverage, 3),
            "status": status, "rank_score": round(support * (0.6 + 0.4 * coverage) + 0.01 * min(mag, 3), 4),
            "metrics": [r["metric"] for r in avail]}


def _open_exploration(book: MetricBook, benchmark: Optional[dict]) -> Optional[dict]:
    """One open-ended hypothesis: the metric where the company diverges most from its peers."""
    best = None
    for c in (benchmark or {}).get("comparisons", []):
        co = c.get("company") or {}
        if c.get("verdict") == "company_specific" and co.get("direction") in ("up", "down"):
            size = abs(co.get("relative_change") or 0)
            if best is None or size > best[0]:
                best = (size, c["metric"], co["direction"])
    if not best:
        return None
    _, metric, d = best
    return {"id": "open_divergence", "angle": "open_exploration", "angle_label": "Open exploration",
            "statement": f"{label(metric)} has moved {d} while peers have not followed",
            "tests": [{"metric": [metric], "expect": d}],
            "matters": ["A company moving against its peers points to something specific to the company."]}


def _llm_hypotheses(archetype: str, book: MetricBook, missing: list[str]) -> list[dict]:
    """Optional model-written hypotheses; accepted only if every named metric exists in the data."""
    avail = book.metric_names()
    out = llm.try_call("planner", {
        "archetype": archetype, "angles": ", ".join(a["label"] for a in ANGLES),
        "available_metrics": ", ".join(avail), "missing_metrics": ", ".join(missing) or "none"},
        {"hypotheses": list})
    hyps = []
    for i, h in enumerate((out or {}).get("hypotheses", [])[:3]):
        try:
            tests = [{"metric": [p["metric"]], "expect": p["direction"]} for p in h["predicts"]
                     if p["metric"] in avail and p["direction"] in ("up", "down")]
            if tests and h.get("statement"):
                hyps.append({"id": f"llm_{i}", "angle": "open_exploration", "angle_label": "Open exploration",
                             "statement": str(h["statement"]), "tests": tests, "matters": []})
        except (KeyError, TypeError):
            continue
    return hyps


def build_plan(profile: dict, book: MetricBook, benchmark: Optional[dict] = None,
               expected_metrics: Optional[list[str]] = None, use_llm: bool = True) -> dict:
    """Return the research plan: ranked, tested hypotheses plus the metrics Member 1's collectors still need."""
    arch = profile.get("archetype", "unclassified")
    candidates = []
    for a in ANGLES:
        if a["archetypes"] is None or arch in a["archetypes"] or arch == "unclassified":
            for t in a["templates"]:
                candidates.append({**t, "angle": a["id"], "angle_label": a["label"]})
    oe = _open_exploration(book=book, benchmark=benchmark)
    core_metrics = {m for c in candidates for m in c["tests"][0]["metric"]}
    if oe and oe["tests"][0]["metric"][0] not in core_metrics:  # skip if an angle already covers that metric
        candidates.append(oe)
    expected = expected_metrics or ["revenue_growth_yoy", "volume_growth_yoy", "price_mix_growth_yoy",
                                    "receivable_days", "inventory_days", "gross_margin"]
    missing = [m for m in expected if m not in book.metric_names()]
    if use_llm:
        candidates += _llm_hypotheses(arch, book, missing)
    tested = [test_hypothesis(h, book) for h in candidates]
    ranked = sorted(tested, key=lambda h: (h["status"] == "untestable", -h["rank_score"]))
    for i, h in enumerate(ranked, 1):
        h["rank"] = i
    keep = [h for h in ranked if h["status"] != "untestable"][:5]
    untestable = [h for h in ranked if h["status"] == "untestable"]
    return {"archetype": arch, "angles_considered": sorted({h["angle_label"] for h in ranked}),
            "hypotheses": keep, "untestable": untestable,
            "collect_requests": [{"metric": m, "reason": "needed by at least one hypothesis"} for m in missing],
            "missing_metrics": missing}
