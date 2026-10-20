"""Task 2.7: contradiction finder.
Pass 1: claim pairs on the same topic and entity with opposite direction (NLI cross-encoder if installed,
        otherwise topic and polarity overlap).
Pass 2: a judge confirms; it must quote BOTH passages (model if available, otherwise the claim quotes).
Also: management statements that conflict with computed numbers (from Member 1's say-vs-do table)."""
from __future__ import annotations
import re
from typing import Callable, Optional

from . import llm
from .claims import Claim, norm

_NLI = None


def nli_contradiction_prob(a: str, b: str) -> Optional[float]:
    """DeBERTa NLI cross-encoder when sentence-transformers and the model are available; else None."""
    global _NLI
    if _NLI is False:
        return None
    try:
        if _NLI is None:
            from sentence_transformers import CrossEncoder  # type: ignore
            _NLI = CrossEncoder("cross-encoder/nli-deberta-v3-base")
        import numpy as np
        logits = _NLI.predict([(a, b)])[0]
        e = np.exp(logits - np.max(logits))
        return float((e / e.sum())[0])  # label order for this model: contradiction, entailment, neutral
    except Exception:
        _NLI = False
        return None


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", s.lower())}


def overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / max(1, len(ta | tb))


def find_claim_conflicts(claims: list[Claim], min_overlap: float = 0.10, max_pairs: int = 60,
                         nli: Callable = nli_contradiction_prob) -> list[dict]:
    found: list[dict] = []
    for i, a in enumerate(claims):
        for b in claims[i + 1:]:
            if a.evidence_id == b.evidence_id or a.entity != b.entity or a.topic != b.topic:
                continue
            if not a.direction or not b.direction or a.direction == b.direction:
                continue
            ov = overlap(a.text, b.text)
            p = nli(a.text, b.text)
            if p is not None:
                if p < 0.6:
                    continue
            elif ov < min_overlap:
                continue
            judged = judge(a, b)
            if judged:
                found.append({"kind": "claim_pair", "topic": a.topic, "entity": a.entity,
                              "quote_a": judged["quote_a"], "quote_b": judged["quote_b"],
                              "url_a": a.url, "url_b": b.url, "locator_a": a.locator, "locator_b": b.locator,
                              "period_a": a.period, "period_b": b.period, "evidence_ids": [a.evidence_id, b.evidence_id],
                              "detail": judged.get("reason", f"opposite direction on {a.topic}"),
                              "nli": p, "overlap": round(ov, 3), "judge": judged["by"]})
            if len(found) >= max_pairs:
                return found
    return found


def judge(a: Claim, b: Claim) -> Optional[dict]:
    o = llm.try_call("judge", {"claim_a": a.text, "claim_b": b.text},
                     {"contradiction": bool, "quote_a": str, "quote_b": str})
    if o is not None:
        qa, qb = o.get("quote_a", ""), o.get("quote_b", "")
        if o["contradiction"] and norm(qa) in norm(a.text) and norm(qb) in norm(b.text):
            return {"quote_a": qa, "quote_b": qb, "reason": o.get("reason", ""), "by": "llm"}
        return None  # judge said no, or did not quote both passages exactly
    return {"quote_a": a.quote or a.text, "quote_b": b.quote or b.text,
            "reason": f"two sources point opposite ways on {a.topic}", "by": "rules"}


def claims_vs_numbers(say_vs_do: list[dict], evidence: list[dict]) -> list[dict]:
    by_id = {str(e.get("id")): e for e in evidence}
    out = []
    for r in say_vs_do or []:
        if r.get("verdict") != "misaligned":
            continue
        ev = by_id.get(str(r.get("evidence_id")), {})
        if not ev.get("url"):
            continue
        out.append({"kind": "management_vs_numbers", "topic": r.get("angle", ""), "entity": ev.get("entity", ""),
                    "quote_a": r.get("statement", ""), "quote_b": r.get("detail", ""),
                    "url_a": ev["url"], "url_b": None, "locator_a": ev.get("locator"), "locator_b": None,
                    "period_a": ev.get("period"), "period_b": None, "evidence_ids": [r.get("evidence_id")],
                    "metric": r.get("metric"), "detail": r.get("detail", ""), "nli": None, "overlap": None,
                    "judge": "computed"})
    return out


def find_contradictions(claims: list[Claim], say_vs_do: list[dict], evidence: list[dict]) -> list[dict]:
    return claims_vs_numbers(say_vs_do, evidence) + find_claim_conflicts(claims)
