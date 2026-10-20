"""Task 1.10: cluster claims and count independent source types per cluster.
Embeddings: sentence-transformers if installed, otherwise a TF-IDF fallback (no download needed).
Peer and industry evidence counts as independent of the company; syndicated copies are merged."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional
import numpy as np
from ..schema import Evidence, Role
from ..tagging.dedupe import mark_independence


@dataclass
class ClaimRef:
    text: str
    evidence_id: str


def get_embedder(prefer: str = "auto") -> Callable[[list[str]], np.ndarray]:
    """Returns f(list[str]) -> L2-normalised matrix."""
    if prefer in ("auto", "sbert"):
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2")
            return lambda xs: model.encode(xs, normalize_embeddings=True)
        except Exception:
            if prefer == "sbert":
                raise

    def tfidf(xs: list[str]) -> np.ndarray:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import normalize
        if not xs:
            return np.zeros((0, 1))
        try:
            X = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True).fit_transform(xs)
        except ValueError:
            try:
                X = TfidfVectorizer(ngram_range=(1, 2), analyzer="char_wb").fit_transform(xs)
            except ValueError:
                return np.zeros((len(xs), 1))
        return normalize(X).toarray()
    return tfidf


def cluster_claims(claims: list[ClaimRef], embed: Optional[Callable] = None, threshold: float = 0.45) -> list[list[int]]:
    """Single-link clustering by cosine similarity over claim texts (union-find)."""
    if not claims:
        return []
    E = (embed or get_embedder())([c.text for c in claims])
    sim = E @ E.T
    parent = list(range(len(claims)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            if sim[i, j] >= threshold:
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(claims)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


@dataclass
class ClusterSummary:
    representative: str
    claim_texts: list[str]
    evidence_ids: list[str]
    independent_evidence_ids: list[str]
    independent_source_types: list[str]
    independent_count: int
    has_outside_company: bool
    roles: list[str]
    meets_triangulation: bool          # >=2 independent source types AND >=1 outside the company's own communication
    flags: list[str] = field(default_factory=list)


def corroboration_map(claims: list[ClaimRef], evidence: list[Evidence], embed: Optional[Callable] = None,
                      threshold: float = 0.45, min_types: int = 2) -> list[ClusterSummary]:
    by_id = {e.id: e for e in mark_independence(evidence)}
    out: list[ClusterSummary] = []
    for cluster in cluster_claims(claims, embed, threshold):
        ids = list(dict.fromkeys(claims[i].evidence_id for i in cluster))
        evs = [by_id[i] for i in ids if i in by_id]
        indep = [e for e in evs if e.independent]
        types = sorted({e.source_type.value for e in indep})
        outside = any(e.role in (Role.peer, Role.industry) or e.source_type.value in ("gov_macro", "news", "industry", "alt_data")
                      for e in indep)
        flags = sorted({f for e in evs for f in e.flags})
        out.append(ClusterSummary(
            representative=max((claims[i].text for i in cluster), key=len), claim_texts=[claims[i].text for i in cluster],
            evidence_ids=ids, independent_evidence_ids=[e.id for e in indep], independent_source_types=types,
            independent_count=len(indep), has_outside_company=outside, roles=sorted({e.role.value for e in indep}),
            meets_triangulation=len(types) >= min_types and outside, flags=flags))
    return sorted(out, key=lambda c: (-c.independent_count, c.representative))


def to_dicts(summaries: list[ClusterSummary]) -> list[dict]:
    return [asdict(s) for s in summaries]
