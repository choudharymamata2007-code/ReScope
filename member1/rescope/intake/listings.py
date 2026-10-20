"""Task 1.2 (part 1): load the exchange equity list and match a free-text company name to it.
No company is named anywhere in this file; the universe comes from a CSV (downloaded from the
exchange and cached, or supplied locally)."""
from __future__ import annotations
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import pandas as pd
from rapidfuzz import fuzz, process
from .. import config
from ..http import Fetcher

SUFFIXES = re.compile(r"\b(limited|ltd|india|pvt|private|company|co|corporation|corp|inc|the|of)\b\.?", re.I)


def normalise_name(name: str) -> str:
    n = re.sub(r"[^\w\s&]", " ", name.lower())
    n = SUFFIXES.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


@dataclass
class ListedCompany:
    name: str
    symbol: str
    isin: Optional[str] = None
    bse_code: Optional[str] = None
    industry: Optional[str] = None
    sector: Optional[str] = None
    norm: str = ""


_COLS = {
    "name": ["name of company", "company name", "name", "company"],
    "symbol": ["symbol", "nse symbol", "ticker"],
    "isin": ["isin number", "isin code", "isin"],
    "bse_code": ["security code", "bse code", "scrip code"],
    "industry": ["industry", "industry group"],
    "sector": ["sector", "sector name"],
}


def _pick(df: pd.DataFrame, key: str) -> Optional[str]:
    lowered = {c.strip().lower(): c for c in df.columns}
    for cand in _COLS[key]:
        if cand in lowered:
            return lowered[cand]
    return None


def parse_listing_csv(content: bytes | str) -> list[ListedCompany]:
    raw = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    df = pd.read_csv(io.StringIO(raw), dtype=str).fillna("")
    cols = {k: _pick(df, k) for k in _COLS}
    if not cols["name"] or not cols["symbol"]:
        raise ValueError("listing CSV needs company-name and symbol columns")
    out = []
    for _, r in df.iterrows():
        g = lambda k: (r[cols[k]].strip() or None) if cols[k] else None
        c = ListedCompany(name=g("name") or "", symbol=g("symbol") or "", isin=g("isin"),
                          bse_code=g("bse_code"), industry=g("industry"), sector=g("sector"))
        c.norm = normalise_name(c.name)
        if c.name and c.symbol:
            out.append(c)
    return out


def merge_sector_info(universe: list[ListedCompany], other: list[ListedCompany]) -> list[ListedCompany]:
    """Copy industry/sector from a second list (e.g. an index constituents file) onto the universe."""
    by_sym = {c.symbol: c for c in other}
    for c in universe:
        o = by_sym.get(c.symbol)
        if o:
            c.industry = c.industry or o.industry
            c.sector = c.sector or o.sector
    return universe


def load_universe(path: Path | str | None = None, fetcher: Optional[Fetcher] = None,
                  url: Optional[str] = None) -> list[ListedCompany]:
    """Load from a local CSV if given, otherwise download (and cache) the exchange list."""
    if path:
        return parse_listing_csv(Path(path).read_bytes())
    f = fetcher or Fetcher()
    res = f.get(url or config.URLS["exchange_equity_list_csv"], ttl=30 * 86400)
    if not res.ok:
        raise RuntimeError(f"could not download listing (HTTP {res.status}); pass a local CSV path instead")
    return parse_listing_csv(res.content)


@dataclass
class Match:
    company: ListedCompany
    score: float


def match_company(query: str, universe: list[ListedCompany], limit: int = 5) -> list[Match]:
    """Fuzzy-match by symbol (exact) then by normalised name."""
    q = query.strip()
    for c in universe:
        if c.symbol.lower() == q.lower():
            return [Match(c, 100.0)]
    nq = normalise_name(q)
    choices = {i: c.norm for i, c in enumerate(universe)}
    res = process.extract(nq, choices, scorer=fuzz.WRatio, limit=limit)
    return [Match(universe[idx], float(score)) for _, score, idx in res]
