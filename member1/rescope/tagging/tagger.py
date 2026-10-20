"""Task 1.4: classify source type and tier, parse Indian fiscal periods and dates, and build
Evidence objects with a stable id and origin hash."""
from __future__ import annotations
import datetime as dt
import hashlib
import re
from typing import Optional
from urllib.parse import urlparse
from ..schema import Evidence, Role, SourceType
from .dedupe import origin_hash

# Generic, company-neutral domain rules (suffix match). Verify and extend as needed.
DOMAIN_RULES: list[tuple[str, SourceType, int]] = [
    ("bseindia.com", SourceType.filing, 1),
    ("nseindia.com", SourceType.filing, 1),
    ("sebi.gov.in", SourceType.filing, 1),
    ("mospi.gov.in", SourceType.gov_macro, 2),
    ("rbi.org.in", SourceType.gov_macro, 2),
    ("data.gov.in", SourceType.gov_macro, 2),
    ("pib.gov.in", SourceType.gov_macro, 2),
    ("worldbank.org", SourceType.gov_macro, 2),
    ("gst.gov.in", SourceType.gov_macro, 2),
    ("archive.org", SourceType.alt_data, 4),
    ("reddit.com", SourceType.community, 5),
    ("twitter.com", SourceType.community, 5),
    ("x.com", SourceType.community, 5),
    ("quora.com", SourceType.community, 5),
]
KEYWORD_RULES: list[tuple[re.Pattern, SourceType, int]] = [
    (re.compile(r"annual[\s_-]*report|integrated[\s_-]*report|\bbrsr\b", re.I), SourceType.annual_report, 1),
    (re.compile(r"transcript|earnings[\s_-]*call|conference[\s_-]*call|analyst[\s_-]*call", re.I), SourceType.transcript, 3),
    (re.compile(r"investor[\s_-]*presentation|presentation|investor[\s_-]*deck|earnings[\s_-]*deck", re.I), SourceType.presentation, 3),
    (re.compile(r"quarterly[\s_-]*result|financial[\s_-]*result|results?\s+for\s+the\s+quarter|unaudited", re.I), SourceType.results, 1),
]


def host_of(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def classify_source(url: str, title: str = "", hint: Optional[SourceType] = None) -> tuple[SourceType, int]:
    """Return (source_type, tier). Content keywords beat generic domain rules for filings sites."""
    blob = f"{url} {title}"
    for pat, st, tier in KEYWORD_RULES:
        if pat.search(blob):
            return st, tier
    host = host_of(url)
    for suffix, st, tier in DOMAIN_RULES:
        if host == suffix or host.endswith("." + suffix):
            return st, tier
    if hint:
        return hint, {SourceType.news: 4, SourceType.industry: 2, SourceType.alt_data: 4}.get(hint, 3)
    return SourceType.news, 4


_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], 1)}
_MONTH_ABBR = {k[:3]: v for k, v in _MONTHS.items()}
_QUARTER_END = {6: 1, 9: 2, 12: 3, 3: 4}      # month of quarter end -> fiscal quarter (April-March FY)


def fiscal_period_for_date(d: dt.date) -> str:
    """Quarter that ENDS on/near the given date, e.g. 30 Sep 2025 -> 'Q2 FY26'."""
    q = _QUARTER_END.get(d.month)
    if q is None:                                  # mid-quarter date: map to the quarter it falls in
        q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[d.month]
    fy_end_year = d.year + (1 if d.month >= 4 else 0)
    return f"Q{q} FY{str(fy_end_year)[-2:]}"


def parse_date(text: str) -> Optional[dt.date]:
    """Parse '30 September 2025', 'September 30, 2025', '2025-09-30', '30/09/2025'."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", text)
    if m:
        try:
            return dt.date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", text)
    if m and m[2].lower()[:3] in _MONTH_ABBR:
        try:
            return dt.date(int(m[3]), _MONTH_ABBR[m[2].lower()[:3]], int(m[1]))
        except ValueError:
            pass
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", text)
    if m and m[1].lower()[:3] in _MONTH_ABBR:
        try:
            return dt.date(int(m[3]), _MONTH_ABBR[m[1].lower()[:3]], int(m[2]))
        except ValueError:
            pass
    return None


def parse_period(text: str) -> Optional[str]:
    """Normalise to 'Qn FYyy'. Accepts 'Q2 FY26', 'Q2FY2026', '2QFY26', 'quarter ended 30 September 2025',
    'three months ended June 30, 2025'. Returns 'FYyy' for full-year phrases, else None."""
    m = re.search(r"\bQ([1-4])\s*[-/ ]?\s*FY\s*'?(\d{2,4})\b", text, re.I) or \
        re.search(r"\b([1-4])Q\s*FY\s*'?(\d{2,4})\b", text, re.I)
    if m:
        return f"Q{m[1]} FY{m[2][-2:]}"
    m = re.search(r"(?:quarter|three months|3 months|period)\s+ended\s+(.{6,30}?\d{4})", text, re.I)
    if m:
        d = parse_date(m[1])
        if d:
            return fiscal_period_for_date(d)
    m = re.search(r"\bFY\s*'?(\d{4})\s*[-/]\s*(\d{2,4})\b", text, re.I)
    if m:
        return f"FY{m[2][-2:]}"
    m = re.search(r"\b(?:year ended|financial year)\s+(?:31\s+March\s+)?(\d{4})", text, re.I)
    if m:
        return f"FY{m[1][-2:]}"
    m = re.search(r"\bFY\s*'?(\d{2})\b", text, re.I)
    if m:
        return f"FY{m[1]}"
    return None


def make_evidence(*, title: str, text: str, url: str, entity: str, role: Role,
                  locator: Optional[str] = None, date: Optional[dt.date] = None,
                  period: Optional[str] = None, hint: Optional[SourceType] = None,
                  source_type: Optional[SourceType] = None, tier: Optional[int] = None,
                  publisher: Optional[str] = None) -> Evidence:
    st, t = classify_source(url, title, hint)
    if source_type is not None:
        st = source_type
        t = tier if tier is not None else t
    elif tier is not None:
        t = tier
    date = date or parse_date(f"{title} {text[:400]}")
    period = period or parse_period(f"{title} {text[:600]}") or (fiscal_period_for_date(date) if date else None)
    ev_id = hashlib.sha1(f"{url}|{locator}|{entity}|{title}".encode()).hexdigest()[:16]
    return Evidence(id=ev_id, title=title.strip()[:300], text=text.strip(), url=url, source_type=st,
                    source_tier=t, date=date, entity=entity, role=role, period=period, locator=locator,
                    origin_hash=origin_hash(text), publisher=publisher or host_of(url))
