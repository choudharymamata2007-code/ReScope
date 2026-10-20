"""Task 1.2 (part 2): detect the sub-sector archetype from industry labels and business wording.
Rules are generic vocabulary, not company names. An optional LLM fallback (Member 2's wrapper) is
used only when the rule confidence is low."""
from __future__ import annotations
import re
from typing import Callable, Optional

ARCHETYPES: dict[str, list[str]] = {
    "packaged_staples": [
        "fast moving consumer goods", "fmcg", "packaged food", "packaged foods", "personal care", "home care", "household products",
        "beverages", "edible oil", "soap", "detergent", "biscuit", "confectionery", "dairy", "tea", "coffee",
        "snacks", "staples", "foods", "hygiene", "tobacco", "spices", "noodles", "oral care"],
    "discretionary_durables": [
        "automobile", "two-wheeler", "passenger vehicle", "appliances", "consumer durables", "durables",
        "apparel", "footwear", "jewellery", "paints", "consumer electronics", "furniture", "luxury",
        "watches", "premium", "white goods", "air conditioner", "textile"],
    "organised_retail": [
        "consumer services", "retail", "stores", "supermarket", "hypermarket", "same-store", "like-for-like", "omnichannel",
        "e-commerce", "fashion retail", "store network", "footfall", "quick commerce", "marketplace",
        "department store", "franchise stores"],
}
ARCHETYPE_LABELS = {
    "packaged_staples": "Packaged staples",
    "discretionary_durables": "Discretionary / durables",
    "organised_retail": "Organised retail",
}


def detect_archetype(texts: list[str], industry: Optional[str] = None,
                     llm_fallback: Optional[Callable[[list[str], Optional[str]], str]] = None,
                     min_confidence: float = 0.4) -> tuple[str, float, list[str]]:
    """Return (archetype, confidence 0-1, matched terms)."""
    blob = " ".join(texts + ([industry] if industry else [])).lower()
    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}
    for arch, terms in ARCHETYPES.items():
        hits = []
        for t in terms:
            n = len(re.findall(r"\b" + re.escape(t) + r"\b", blob))
            if n:
                hits.append(t)
                scores[arch] = scores.get(arch, 0.0) + min(n, 5) * (2.0 if industry and t in industry.lower() else 1.0)
        matched[arch] = hits
    if not scores:
        best, conf = "unclassified", 0.0
    else:
        best = max(scores, key=scores.get)
        total = sum(scores.values())
        conf = round(scores[best] / total * min(1.0, scores[best] / 6.0), 3)
    if conf < min_confidence and llm_fallback is not None:
        try:
            guess = llm_fallback(texts, industry)
            if guess in ARCHETYPES:
                return guess, max(conf, 0.5), matched.get(guess, [])
        except Exception:
            pass
    return best, conf, matched.get(best, [])
