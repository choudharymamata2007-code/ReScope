"""Task 1.11 (part 2): detect metrics that management stopped reporting, renamed, or redefined
between periods. Works from presentation/transcript/results text grouped by period."""
from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from typing import Optional
from ..schema import Evidence, SourceType
from ..quant.series import sort_periods

_TERM = re.compile(r"\b((?:[A-Za-z][A-Za-z\-/]{2,}\s){0,3}[A-Za-z][A-Za-z\-/]{2,})\s+"
                   r"(growth|share|days|margin|ratio|mix|penetration|volumes?|market share|contribution)\b", re.I)
_REDEF = re.compile(r"\b(restated|re-?classified|revised definition|now (?:defined|reported|presented)|"
                    r"changed? (?:the )?(?:definition|methodology)|no longer (?:report|disclos|provid)\w*|"
                    r"discontinu\w+ (?:the )?(?:disclosure|reporting))\b", re.I)
STOP = {"the", "our", "and", "for", "with", "this", "that", "year", "quarter", "over", "strong", "double"}


def extract_terms(text: str) -> set[str]:
    out = set()
    for m in _TERM.finditer(text):
        words = [w for w in m.group(1).lower().split() if w not in STOP]
        if words:
            out.add(" ".join(words[-2:] + [m.group(2).lower()]))
    return out


@dataclass
class DisclosureChange:
    kind: str                       # dropped | renamed | redefinition_language
    term: str
    last_seen: Optional[str]
    first_missing: Optional[str]
    similar_to: Optional[str] = None
    evidence_ids: Optional[list[str]] = None
    detail: str = ""


def detect_disclosure_changes(evidence: list[Evidence], min_prior_periods: int = 2,
                              doc_types: tuple[SourceType, ...] = (SourceType.presentation, SourceType.results,
                                                                   SourceType.transcript)) -> list[DisclosureChange]:
    by_period: dict[str, set[str]] = defaultdict(set)
    redef: dict[str, list[Evidence]] = defaultdict(list)
    for e in evidence:
        if e.source_type not in doc_types or not e.period or not e.period.startswith("Q"):
            continue
        by_period[e.period] |= extract_terms(e.text)
        if _REDEF.search(e.text):
            redef[e.period].append(e)
    periods = sort_periods(list(by_period))
    out: list[DisclosureChange] = []
    if len(periods) >= min_prior_periods + 1:
        latest, prior = periods[-1], periods[:-1]
        counts: dict[str, int] = defaultdict(int)
        for p in prior:
            for t in by_period[p]:
                counts[t] += 1
        new_terms = by_period[latest] - set(counts)
        for term, n in sorted(counts.items()):
            if n >= min_prior_periods and term not in by_period[latest]:
                last_seen = next(p for p in reversed(prior) if term in by_period[p])
                sim = max(((SequenceMatcher(None, term, nt).ratio(), nt) for nt in new_terms), default=(0, None))
                if sim[0] >= 0.7:
                    out.append(DisclosureChange("renamed", term, last_seen, latest, sim[1],
                                                detail=f"'{term}' (reported {n} of {len(prior)} prior periods) replaced by '{sim[1]}'"))
                else:
                    out.append(DisclosureChange("dropped", term, last_seen, latest,
                                                detail=f"'{term}' reported in {n} of {len(prior)} prior periods but absent in {latest}"))
    for p in periods:
        for e in redef.get(p, []):
            m = _REDEF.search(e.text)
            out.append(DisclosureChange("redefinition_language", m.group(0).lower(), p, None, None, [e.id],
                                        f"wording suggests a change in how metrics are reported ({e.locator or 'text'})"))
    return out


def to_dicts(changes: list[DisclosureChange]) -> list[dict]:
    return [asdict(c) for c in changes]
