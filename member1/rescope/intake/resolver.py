"""Task 1.2 (part 3): peers and the single entry point `resolve_company(name)`.
Peers come from sector classification and from names mentioned in the annual-report
competition text, then are confirmed by filings availability (injectable callable)."""
from __future__ import annotations
import re
from typing import Callable, Optional
from ..schema import CompanyProfile, PeerRef
from .archetype import detect_archetype
from .listings import ListedCompany, match_company, normalise_name

MIN_PEERS, MAX_PEERS = 3, 6
AMBIGUOUS_GAP = 8.0       # top-two score gap below this is flagged as ambiguous
MIN_MATCH_SCORE = 70.0


def find_mentions(text: str, universe: list[ListedCompany], exclude_symbol: str) -> set[str]:
    """Symbols of listed companies whose normalised name appears in free text (competition section)."""
    t = " " + normalise_name(text) + " "
    out = set()
    for c in universe:
        if c.symbol == exclude_symbol or len(c.norm) < 4:
            continue
        if f" {c.norm} " in t:
            out.add(c.symbol)
    return out


_NOT_A_PEER = re.compile(
    r"\b(financial|finance|securities|broking|brokers?|capital markets?|bank|banking|insurance|assurance|asset management|"
    r"mutual fund|investments?|wealth|research|ratings?|advisors?|advisory|consult\w*|credit)\b|^(crisil|icra)\b", re.I)


def is_not_a_peer(name: str) -> bool:
    """Brokers, rating agencies, banks and research houses are named in company documents as authors or lenders,
    not as business competitors."""
    return bool(_NOT_A_PEER.search(name))


def mention_keys(c: ListedCompany) -> set[str]:
    """Names a document might use for this company: the full normalised name and its first two words
    ('sample brand' for 'Sample Brand Products'). Very short keys are ignored to avoid false matches."""
    toks = c.norm.split()
    keys = {c.norm}
    if len(toks) >= 2 and len(" ".join(toks[:2])) >= 8:
        keys.add(" ".join(toks[:2]))
    return {k for k in keys if len(k) >= 5}


def co_mentioned(docs: dict[str, str], universe: list[ListedCompany], exclude_symbols: set[str],
                 min_docs: int = 2) -> list[tuple[ListedCompany, int]]:
    """Listed companies named in at least `min_docs` different documents about the target (competitors are
    usually named in annual reports, presentations, analyst notes and calls). Ranked by number of documents."""
    padded = [" " + normalise_name(t) + " " for t in docs.values()]
    out = []
    for c in universe:
        if c.symbol in exclude_symbols:
            continue
        keys = mention_keys(c)
        n = sum(1 for t in padded if any(f" {k} " in t for k in keys))
        if n >= min_docs:
            out.append((c, n))
    return sorted(out, key=lambda x: (-x[1], x[0].name))


def resolve_peers(target: ListedCompany, universe: list[ListedCompany], competition_text: str = "",
                  has_filings: Optional[Callable[[ListedCompany], bool]] = None,
                  k: int = MAX_PEERS) -> list[PeerRef]:
    mentioned = find_mentions(competition_text, universe, target.symbol) if competition_text else set()
    key = (target.industry or target.sector or "").strip().lower()
    cands: dict[str, PeerRef] = {}
    for c in universe:
        if c.symbol == target.symbol:
            continue
        same = bool(key) and key in {(c.industry or "").strip().lower(), (c.sector or "").strip().lower()}
        ment = c.symbol in mentioned
        if not (same or ment):
            continue
        score = (2.0 if ment else 0.0) + (1.0 if same else 0.0)
        reason = " and ".join(r for r, ok in (("named in annual-report competition text", ment),
                                              ("same industry classification", same)) if ok)
        avail = has_filings(c) if has_filings else True
        cands[c.symbol] = PeerRef(name=c.name, symbol=c.symbol, reason=reason, mentioned_in_report=ment,
                                  filings_available=avail, score=score + (0.5 if avail else -2.0))
    ranked = sorted(cands.values(), key=lambda p: (-p.score, p.name))
    usable = [p for p in ranked if p.filings_available]
    return (usable or ranked)[:k]


def resolve_company(name: str, universe: list[ListedCompany], business_text: list[str] | None = None,
                    competition_text: str = "",
                    has_filings: Optional[Callable[[ListedCompany], bool]] = None,
                    llm_fallback=None) -> CompanyProfile:
    """Entry point: free-text name -> CompanyProfile (symbols, sector, archetype, peers, warnings)."""
    if not name or not name.strip():
        raise ValueError("company name is required")
    matches = match_company(name, universe)
    if not matches:
        raise LookupError(f"no listed company found for '{name}'")
    top = matches[0]
    warnings: list[str] = []
    if top.score < MIN_MATCH_SCORE:
        warnings.append(f"low name-match score ({top.score:.0f}); confirm the company before running")
    if len(matches) > 1 and top.score < 100 and top.score - matches[1].score < AMBIGUOUS_GAP:
        warnings.append("ambiguous name; close alternatives: " + ", ".join(m.company.name for m in matches[1:3]))
    c = top.company
    arch, conf, terms = detect_archetype(business_text or [], c.industry or c.sector, llm_fallback)
    if arch == "unclassified":
        warnings.append("archetype could not be determined from available text")
    peers = resolve_peers(c, universe, competition_text, has_filings)
    if len(peers) < MIN_PEERS:
        warnings.append(f"only {len(peers)} peers found; benchmark will carry a thin-coverage warning")
    return CompanyProfile(input_name=name, name=c.name, nse_symbol=c.symbol, bse_code=c.bse_code, isin=c.isin,
                          sector=c.sector, industry=c.industry, archetype=arch, archetype_confidence=conf,
                          archetype_terms=terms, match_score=top.score, peers=peers, warnings=warnings)
