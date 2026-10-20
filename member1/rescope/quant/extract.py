"""Task 1.8: pull quarterly figures out of results tables. Heuristic by design: it matches row
labels with generic regexes, reads period headers, and returns every number together with the
locator of the table it came from. Always cross-check with series.cross_check before trusting."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional
from ..tagging.tagger import parse_period

# canonical metric -> regexes for row labels (generic accounting vocabulary)
LABELS: dict[str, list[str]] = {
    "revenue": [r"revenue from operations", r"net sales", r"total revenue from operations", r"sales and other operating income"],
    "cogs": [r"cost of (materials|goods) (consumed|sold)", r"cost of goods sold", r"cost of sales",
             r"purchases? of stock[- ]in[- ]trade"],
    "receivables": [r"trade receivables", r"sundry debtors", r"accounts receivable"],
    "inventory": [r"^inventories", r"inventory\b", r"stock[- ]in[- ]trade$"],
    "payables": [r"trade payables", r"sundry creditors", r"accounts payable"],
    "volume": [r"volume growth", r"sales volume", r"tonnage", r"underlying volume", r"\bUVG\b", r"volumes? \(.*\)"],
    "ebitda": [r"\bebitda\b", r"operating profit"],
    "cfo": [r"net cash (flow )?(from|generated from) operating activities", r"cash flow from operations"],
}


def parse_number(s: str) -> Optional[float]:
    """'1,234.5' -> 1234.5 ; '(12.3)' -> -12.3 ; '-' or '' -> None ; '12.3%' -> 12.3"""
    if s is None:
        return None
    t = s.strip()
    t = re.sub(r"^(?:INR|Rs\.?|₹)\s*", "", t, flags=re.I)
    t = t.replace(",", "").replace("%", "").strip()
    if t in ("", "-", "—", "–", "NA", "N/A", "nil", "Nil", "none", "None"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


@dataclass
class ExtractedRow:
    metric: str
    label: str
    values: dict[str, Optional[float]]      # period -> value ('col0', 'col1' ... if headers have no period)
    locator: str
    evidence_id: Optional[str] = None


def _header_periods(table: list[list[str]]) -> list[Optional[str]]:
    for row in table[:4]:
        periods = [parse_period(c) if c else None for c in row]
        if sum(p is not None for p in periods) >= 2:
            return periods
    return []


def extract_rows(table: list[list[str]], locator: str, evidence_id: Optional[str] = None) -> list[ExtractedRow]:
    """Find rows whose first non-empty cell matches a known metric label."""
    out = []
    periods = _header_periods(table)
    for row in table:
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        label = next((c for c in cells if c), "")
        for metric, pats in LABELS.items():
            if any(re.search(p, label, re.I) for p in pats):
                nums = [parse_number(c) for c in cells[cells.index(label) + 1:]]
                vals: dict[str, Optional[float]] = {}
                for i, v in enumerate(nums):
                    key = periods[cells.index(label) + 1 + i] if periods and cells.index(label) + 1 + i < len(periods) else None
                    vals[key or f"col{i}"] = v
                if any(v is not None for v in vals.values()):
                    out.append(ExtractedRow(metric, label, vals, locator, evidence_id))
                break
    return out


def parse_table_text(text: str) -> list[list[str]]:
    """Evidence text for tables is stored as 'a | b | c' rows; rebuild the grid."""
    return [[c.strip() for c in line.split("|")] for line in text.splitlines() if "|" in line]


def extract_from_evidence(items) -> list[ExtractedRow]:
    """Run over stored Evidence whose locator mentions 'table'."""
    rows: list[ExtractedRow] = []
    for ev in items:
        if ev.locator and "table" in ev.locator:
            rows += extract_rows(parse_table_text(ev.text), f"{ev.url}#{ev.locator}", ev.id)
    return rows


_VOL_PHRASE = re.compile(r"(?:underlying\s+)?(?:volume|UVG)[^.%\n]{0,40}?(-?\d+(?:\.\d+)?)\s*%", re.I)


def extract_volume_growth_from_text(text: str) -> Optional[float]:
    """Pick 'volume growth of 3%' style statements from presentations/transcripts (returns percent as fraction).
    The caller must still attach the locator of the page it came from."""
    m = _VOL_PHRASE.search(text)
    if not m:
        return None
    v = float(m.group(1)) / 100.0
    window = text[max(0, m.start() - 40): m.end()].lower()
    return -abs(v) if re.search(r"declin|fell|fall|drop|decreas|down", window) else v
