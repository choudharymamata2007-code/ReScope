"""Task 2.5: claim extraction. Short, dated, source-linked claims; a claim without a URL is dropped.
Rule-based by default; a model may propose claims but each must quote the passage exactly."""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from typing import Optional

from . import llm
from .common import get, period_end

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])")
TOPICS = {
    "volume": ["volume", "volumes", "units", "offtake"],
    "price": ["price", "pricing", "realisation", "realization", "premium", "price/mix"],
    "receivables": ["receivable", "receivables", "debtor", "distributor days", "payment cycle", "credit period"],
    "inventory": ["inventory", "inventories", "channel stock", "stock levels"],
    "margin": ["margin", "margins", "input cost", "cost pressure"],
    "demand": ["demand", "consumption", "growth", "sales"],
    "distribution": ["distributor", "distributors", "channel", "quick commerce", "rural", "modern trade"],
}
UP = ["rose", "rise", "rising", "increase", "increases", "increased", "higher", "lengthened", "expanded", "improved",
      "accelerated", "strong", "robust", "broad-based", "premium", "growth"]
DOWN = ["fell", "fall", "falling", "decline", "declined", "lower", "shortened", "contracted", "weak", "weaker",
        "slowed", "slowdown", "eroded", "pressure", "negative",
        "softened", "softening", "weakened", "dropped", "shrank"]
# "stable / under control" counts as DOWN for stress metrics such as receivables and inventory;
# topic-aware direction is applied in direction_for_topic.
STRESS_TOPICS = {"receivables", "inventory"}
ASSERTIVE = re.compile(r"\b(we|our|management)\b", re.I)


@dataclass
class Claim:
    text: str
    url: str
    evidence_id: str
    entity: str
    role: str
    source_type: str
    topic: str
    direction: Optional[str]
    period: Optional[str] = None
    date: Optional[str] = None
    locator: Optional[str] = None
    tier: int = 3
    independent: bool = True
    quote: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def topic_of(sentence: str) -> Optional[str]:
    s = sentence.lower()
    hits = {t: sum(1 for k in ks if k in s) for t, ks in TOPICS.items()}
    best = max(hits, key=hits.get)
    return best if hits[best] else None


def direction_of(sentence: str, topic: Optional[str]) -> Optional[str]:
    """'up' or 'down' for the metric named by the topic. For stress topics (receivables, inventory) the
    wording 'stable' or 'under control' is a claim of NOT rising, which we record as 'down'."""
    s = sentence.lower()
    up = sum(1 for w in UP if re.search(r"\b" + re.escape(w) + r"\b", s))
    down = sum(1 for w in DOWN if re.search(r"\b" + re.escape(w) + r"\b", s))
    if topic in STRESS_TOPICS:
        if re.search(r"\b(healthy|stable|steady|under control|controlled|normal)\b", s):
            return "down"
        up = sum(1 for w in ("rose", "rise", "rising", "increase", "increased", "higher", "lengthened", "longer", "build", "stretched") if w in s)
        down = sum(1 for w in ("fell", "declined", "lower", "shortened", "reduced") if w in s)
    if up == down:
        return None
    return "up" if up > down else "down"


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text or "") if s.strip()]


def extract_claims(evidence: list, use_llm: bool = True) -> list[Claim]:
    out: list[Claim] = []
    seen: set[tuple[str, str]] = set()
    for ev in evidence:
        url = (get(ev, "url") or "").strip()
        if not url:
            continue  # rule: no URL, no claim
        base = dict(url=url, evidence_id=str(get(ev, "id", "")), entity=get(ev, "entity", ""),
                    role=get(ev, "role", "company"), source_type=get(ev, "source_type", ""),
                    period=get(ev, "period"), date=str(get(ev, "date")) if get(ev, "date") else
                    (str(period_end(get(ev, "period"))) if period_end(get(ev, "period")) else None),
                    locator=get(ev, "locator"), tier=int(get(ev, "source_tier", 3) or 3),
                    independent=bool(get(ev, "independent", True)))
        text = get(ev, "text", "") or ""
        cands = [(c, c) for c in (get(ev, "claims") or [])]
        cands += [(s, s) for s in sentences(text) if 25 <= len(s) <= 320]
        if use_llm:
            o = llm.try_call("claims", {"passage": text[:3000], "entity": base["entity"],
                                        "period": base["period"] or ""}, {"claims": list})
            for c in (o or {}).get("claims", []):
                q = str(c.get("quote", ""))
                if q and norm(q) in norm(text):  # model claims must quote the passage exactly
                    cands.append((str(c.get("text", q)), q))
        for claim_text, quote in cands:
            tp = topic_of(claim_text)
            has_signal = re.search(r"\d", claim_text) or ASSERTIVE.search(claim_text) or direction_of(claim_text, tp)
            if not tp or not has_signal:
                continue
            key = (base["evidence_id"], norm(claim_text))
            if key in seen:
                continue
            seen.add(key)
            out.append(Claim(text=claim_text.strip(), topic=tp, direction=direction_of(claim_text, tp),
                             quote=quote.strip(), **base))
    return out
