"""Task 1.7: origin hashing, near-duplicate / syndication detection, independence flags and
temporal-consistency flags. Copies, syndicated articles, same-publisher items and
statement-only news must not be counted as independent sources."""
from __future__ import annotations
import datetime as dt
import hashlib
import re
from collections import defaultdict
from typing import Iterable, Optional
from ..schema import Evidence, SourceType

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
STATEMENT_ONLY = re.compile(
    r"\b(said in a statement|according to a (press release|company statement)|"
    r"press release|in a regulatory filing|told reporters|company said)\b", re.I)


def normalise(text: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", text.lower())).strip()


def origin_hash(text: str) -> str:
    """Hash of the normalised text; identical copies collapse to the same hash."""
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()[:20]


def shingles(text: str, k: int = 5) -> set[int]:
    toks = normalise(text).split()
    if len(toks) < k:
        return {hash(" ".join(toks))} if toks else set()
    return {hash(" ".join(toks[i:i + k])) for i in range(len(toks) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def near_duplicate(text_a: str, text_b: str, threshold: float = 0.6) -> bool:
    return jaccard(shingles(text_a), shingles(text_b)) >= threshold


def group_syndicated(items: list[Evidence], threshold: float = 0.6) -> list[list[int]]:
    """Union-find over indices: returns clusters (lists of indices) of near-duplicate items."""
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    sh = [shingles(e.text) for e in items]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            same_hash = items[i].origin_hash and items[i].origin_hash == items[j].origin_hash
            if same_hash or jaccard(sh[i], sh[j]) >= threshold:
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(items)):
        groups[find(i)].append(i)
    return list(groups.values())


def _publisher(e: Evidence) -> str:
    if e.publisher:
        return e.publisher.lower()
    m = re.match(r"https?://([^/]+)", e.url)
    host = m.group(1).lower() if m else e.url
    return host[4:] if host.startswith("www.") else host


def mark_independence(items: list[Evidence], threshold: float = 0.6) -> list[Evidence]:
    """Return copies with `independent` and `flags` set.

    - Within a near-duplicate cluster only the earliest item stays independent; others get 'syndicated'.
    - A second item from the same publisher about the same period gets 'same_publisher'.
    - News that only repeats a company statement gets 'company_statement_only'.
    """
    out = [e.model_copy(deep=True) for e in items]
    for cluster in group_syndicated(out, threshold):
        if len(cluster) > 1:
            cluster.sort(key=lambda i: (out[i].date or dt.date.max, out[i].fetched_at))
            for i in cluster[1:]:
                out[i].independent = False
                if "syndicated" not in out[i].flags:
                    out[i].flags.append("syndicated")
    seen: dict[tuple, int] = {}
    for i, e in enumerate(out):
        key = (_publisher(e), e.period, e.entity)
        if key in seen and e.independent:
            e.independent = False
            e.flags.append("same_publisher")
        else:
            seen.setdefault(key, i)
        if e.source_type == SourceType.news and STATEMENT_ONLY.search(e.text):
            e.flags.append("company_statement_only")
            e.independent = False
    return out


def check_temporal_consistency(evidence: Evidence, event_date: Optional[dt.date]) -> Optional[str]:
    """Flag a source dated before the event it claims to confirm."""
    if evidence.date and event_date and evidence.date < event_date:
        flag = "dated_before_event"
        if flag not in evidence.flags:
            evidence.flags.append(flag)
        return flag
    return None


def independent_sources(items: Iterable[Evidence]) -> list[Evidence]:
    return [e for e in mark_independence(list(items)) if e.independent]
