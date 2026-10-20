"""Task 2.8: skeptic agent. For the leading hypothesis: write predictions, call Member 1's
find_disconfirming hook, run the company-vs-sector test from the benchmark, classify
survived / weakened / rejected. At most 2 rounds; round 2 sends queries back to collection."""
from __future__ import annotations
from typing import Callable, Optional

from . import llm
from .claims import Claim, extract_claims
from .common import MetricBook, label, get

METRIC_TOPIC = {"receivable_days": "receivables", "cash_conversion_cycle": "receivables", "inventory_days": "inventory",
                "volume_growth_yoy": "volume", "price_mix_growth_yoy": "price", "price_share_of_growth": "price",
                "gross_margin": "margin", "revenue_growth_yoy": "demand"}
OUTSIDE_TYPES = {"news", "gov_macro", "industry", "alt_data"}
OPPOSITE = {"up": "down", "down": "up"}


def _expected_direction(expect: str) -> Optional[str]:
    base = expect.split("_")[0]
    return base if base in OPPOSITE else None


def sector_verdict(benchmark: Optional[dict], metric: Optional[str]) -> dict:
    for c in (benchmark or {}).get("comparisons", []):
        if c.get("metric") == metric:
            total = c.get("peers_total") or 0
            if total < 2:  # one peer cannot separate a company story from a sector story
                return {"verdict": "insufficient", "peers_same_direction": c.get("peers_same_direction"),
                        "peers_total": total, "note": f"only {total} peer(s) with data"}
            return {"verdict": c.get("verdict", "insufficient"), "peers_same_direction": c.get("peers_same_direction"),
                    "peers_total": total, "note": c.get("note", "")}
    return {"verdict": "insufficient", "peers_same_direction": None, "peers_total": 0,
            "note": "no benchmark for this metric"}


def predictions(hyp: dict) -> list[str]:
    out = []
    for r in hyp["results"]:
        if r.get("available"):
            out.append(f"If this is right, {label(r['metric'])} should keep moving {r['expect'].replace('_', ' ')}.")
    out.append("If this is company-specific, most peers should NOT show the same pattern.")
    return out


def counter_queries(hyp: dict, archetype: str) -> list[str]:
    qs = []
    for r in hyp["results"]:
        if r.get("available"):
            d = _expected_direction(r["expect"])
            opp = {"up": "fell improved", "down": "rose improved"}.get(d or "up")
            qs.append(f"{label(r['metric'])} {opp} {archetype.replace('_', ' ')}")
    return qs


def is_independent(c: Claim) -> bool:
    return c.independent and (c.role in ("peer", "industry") or c.source_type in OUTSIDE_TYPES)


def scan_counter(hyp: dict, claims: list[Claim]) -> list[dict]:
    """Claims on the hypothesis' topics that point the opposite way to what the hypothesis predicts."""
    wanted = {}
    for r in hyp["results"]:
        d = _expected_direction(r.get("expect", "")) if r.get("available") else None
        if d:
            wanted[METRIC_TOPIC.get(r["metric"], "")] = d
    out, seen = [], set()
    for c in claims:
        d = wanted.get(c.topic)
        if d and c.direction == OPPOSITE[d] and (c.evidence_id, c.text) not in seen:
            seen.add((c.evidence_id, c.text))
            out.append({"text": c.text, "url": c.url, "locator": c.locator, "period": c.period,
                        "role": c.role, "source_type": c.source_type, "independent": is_independent(c),
                        "evidence_id": c.evidence_id, "topic": c.topic})
    return out


def decide(hyp: dict, sector: dict, counter: list[dict], coverage: Optional[dict] = None) -> tuple[str, list[str]]:
    n_ind = sum(1 for c in counter if c["independent"])
    reasons = []
    if hyp["support"] < 0.5:
        return "rejected", ["the numbers do not show the pattern the hypothesis predicts"]
    if n_ind >= 2:
        return "rejected", [f"{n_ind} independent sources contradict it"]
    verdict = "survived"
    sv = sector["verdict"]
    if sv == "sector_wide":
        verdict, reasons = "weakened", ["peers show the same pattern, so it looks sector-wide"]
    elif sv == "mixed":
        verdict, reasons = "weakened", ["peers partly show the same pattern"]
    elif sv == "insufficient":
        verdict, reasons = "weakened", ["the company-vs-sector test could not be run (too few peers or no data)"]
    if n_ind == 1:
        verdict = "weakened"
        reasons.append("one independent source points the other way")
    if coverage is not None and not coverage.get("sufficient", True):
        verdict = "weakened"
        reasons.append("data coverage is thin")
    if hyp["coverage"] < 0.67:
        verdict = "weakened"
        reasons.append("only part of the hypothesis could be tested with disclosed metrics")
    if verdict == "survived":
        reasons = ["no independent counter-evidence found; most peers did not follow the same pattern"]
    return verdict, reasons


def run_skeptic(hyp: dict, book: MetricBook, benchmark: Optional[dict], claims: list[Claim], archetype: str,
                coverage: Optional[dict] = None, find_disconfirming: Optional[Callable] = None, collect_more: Optional[Callable] = None,
                max_rounds: int = 2, entity: str = "") -> dict:
    core = hyp["metrics"][0] if hyp.get("metrics") else None
    sector = sector_verdict(benchmark, core)
    rounds, pool, warnings = [], list(claims), []
    queries = counter_queries(hyp, archetype)
    verdict, reasons, counter = "rejected", [], []
    for rnd in range(1, max_rounds + 1):
        if find_disconfirming is not None:
            try:
                found = find_disconfirming({"id": hyp["id"], "statement": hyp["statement"],
                                            "queries": queries, "metrics": hyp.get("metrics", [])},
                                           entity, book.peers)
                pool += extract_claims(list(found or []), use_llm=False)
            except Exception as e:  # a failing source is recorded, never raised
                warnings.append(f"disconfirming search failed in round {rnd}: {e}")
        counter = scan_counter(hyp, pool)
        verdict, reasons = decide(hyp, sector, counter, coverage)
        rounds.append({"round": rnd, "predictions": predictions(hyp), "queries": queries,
                       "counter_found": len(counter), "independent_counter": sum(c["independent"] for c in counter),
                       "sector": sector["verdict"], "verdict": verdict, "reasons": reasons})
        if verdict != "weakened" or collect_more is None or rnd == max_rounds:
            break
        try:  # send the query list back to Member 1's collectors for one more round
            more = collect_more(queries)
            pool += extract_claims(list(more or []), use_llm=False)
        except Exception as e:
            warnings.append(f"collection request failed: {e}")
            break
    return {"hypothesis_id": hyp["id"], "verdict": verdict, "reasons": reasons, "sector": sector,
            "rounds": rounds, "counter_evidence": counter, "warnings": warnings}
