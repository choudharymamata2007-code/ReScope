"""Management-stated volume growth, read from transcripts, presentations and analyst notes.

Volume is the metric companies rarely put in a table, but management often states it ('underlying volume
growth of 4%'). This module extracts such statements WITH their source and quarter, and feeds them to the
series builder as 'stated' (never 'computed') values.

Safety rules:
  - a quarter is used only if the sentence itself names it ('Q3 FY26') or the document's own period is a quarter;
    annual figures ('4% in FY26') are kept as claims but never put into a quarterly series
  - the best-tier sources win (company transcripts/presentations before analyst notes)
  - if sources for the same quarter disagree by more than `conflict_pp` percentage points, NO value is used
    for that quarter and the conflict is reported (some transcript summaries contradict each other)
"""
from __future__ import annotations
import datetime as dt
import re
from dataclasses import dataclass, asdict, field
from statistics import mean
from typing import Optional
import pandas as pd
from ..schema import Evidence
from ..tagging.tagger import fiscal_period_for_date, parse_date, parse_period
from .series import sort_periods

VOL_RE = re.compile(
    r"(?P<kind>underlying\s+volume\s+growth|volume\s+growth|\bUVG\b|volume\s+(?:decline[ds]?|degrowth|de-growth))"
    r"\s*(?:\([^)]*\))?\s*(?:of|at|was|is|by|stood\s+at|:)?\s*(?P<sign>-|\u2212)?\s*(?P<val>\d+(?:\.\d+)?)\s*%", re.I)
SALES_RE = re.compile(
    r"(?P<kind>underlying\s+sales\s+growth|\bUSG\b|domestic\s+(?:sales|revenue)\s+growth|like[- ]for[- ]like\s+(?:sales\s+)?growth)"
    r"\s*(?:\([^)]*\))?\s*(?:of|at|was|is|by|stood\s+at|:)?\s*(?P<sign>-|\u2212)?\s*(?P<val>\d+(?:\.\d+)?)\s*%", re.I)
_Q = re.compile(r"^Q[1-4] FY\d{2}$")
_SOURCES = {"transcript", "presentation", "results", "news", "annual_report"}


@dataclass
class VolumeClaim:
    value: float                 # fraction, e.g. 0.04
    period: Optional[str]        # 'Q3 FY26' | 'FY26' (annual) | None
    basis: str                   # quarter | annual | unknown
    text: str
    evidence_id: str
    url: str
    locator: Optional[str]
    source_type: str
    tier: int
    flags: list[str] = field(default_factory=list)
    kind: str = "volume"         # volume | sales (management-stated sales growth, only kept next to a volume figure)
    inferred: bool = False       # quarter inferred from the document title or a call date, not stated in the sentence


def reported_quarter(call_date: dt.date) -> Optional[str]:
    """Results calls report the quarter that just ended: the latest quarter end before the call (within 150 days)."""
    ends = [dt.date(y, m, d) for y in (call_date.year - 1, call_date.year) for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))]
    prior = [e for e in ends if e < call_date and (call_date - e).days <= 150]
    return fiscal_period_for_date(max(prior)) if prior else None


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence (or line) containing text[start:end]; a claim may only borrow its quarter from its own sentence."""
    left = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    rights = [i for i in (text.find(". ", end), text.find("\n", end)) if i != -1]
    return text[(left + 1) if left != -1 else 0:(min(rights) + 1) if rights else len(text)]


def extract_volume_claims(evidence: list[Evidence]) -> list[VolumeClaim]:
    """Volume claims, plus 'sales' claims from sentences that ALSO state a volume figure (so segment-level
    numbers such as 'Home Care ... USG at 3%' are not mistaken for group sales growth)."""
    out: list[VolumeClaim] = []
    for e in evidence:
        if e.source_type.value not in _SOURCES:
            continue
        for kind, rx in (("volume", VOL_RE), ("sales", SALES_RE)):
            for mt in rx.finditer(e.text):
                window = _sentence(e.text, mt.start(), mt.end())
                if kind == "sales" and not VOL_RE.search(window):
                    continue
                val = float(mt.group("val")) / 100.0
                if mt.group("sign") or mt.group("kind").lower().startswith("volume d"):
                    val = -abs(val)
                period, inferred = parse_period(window), False          # 1) only the claim's own sentence
                if period is None and "table" not in (e.locator or ""):  # 2) never for table cells: columns are ambiguous
                    title_p = parse_period(e.title or "")
                    if title_p and _Q.match(title_p):                    #    quarter named in the document title
                        period, inferred = title_p, True
                    elif e.source_type.value == "transcript":            # 3) a results call reports the quarter that just ended
                        call = parse_date(e.title or "") or parse_date(e.url or "")
                        rq = reported_quarter(call) if call else None
                        if rq:
                            period, inferred = rq, True
                basis = "quarter" if period and _Q.match(period) else ("annual" if period else "unknown")
                out.append(VolumeClaim(val, period, basis, mt.group(0).strip()[:200], e.id, e.url, e.locator,
                                       e.source_type.value, e.source_tier, list(e.flags), kind, inferred))
    return out


def _apply_stated(raw: pd.DataFrame, claims: list[VolumeClaim], kind: str, column: str, label: str,
                  conflict_pp: float) -> pd.DataFrame:
    notes = list(raw.attrs.get("notes", [])) if raw is not None else []
    by_period: dict[str, list[VolumeClaim]] = {}
    for c in claims:
        if c.basis == "quarter" and c.kind == kind:
            by_period.setdefault(c.period, []).append(c)
    df = raw.copy() if raw is not None and not raw.empty else pd.DataFrame()
    for period in sort_periods(list(by_period)):
        cs = by_period[period]
        best = min((c.tier, c.inferred) for c in cs)               # best tier first, stated beats inferred
        top = [c for c in cs if (c.tier, c.inferred) == best]
        spread = (max(c.value for c in cs) - min(c.value for c in cs)) * 100
        if spread > conflict_pp:
            notes.append(f"{label} for {period}: sources disagree ({spread:.1f} percentage points); not used")
            continue
        if period not in df.index:
            df.loc[period, column] = float("nan")
        first = top[0]
        df.at[period, column] = round(mean(c.value for c in top), 4)
        df.at[period, f"loc_{column}"] = f"{first.url}#{first.locator}"
        df.at[period, f"ev_{column}"] = first.evidence_id
    if not df.empty:
        df = df.loc[sort_periods(list(df.index))]
    df.attrs["notes"] = notes
    return df


def apply_stated_volume(raw: pd.DataFrame, claims: list[VolumeClaim], conflict_pp: float = 1.0) -> pd.DataFrame:
    """Add a 'volume_growth' column (with loc_/ev_ pointers) for quarters whose claims agree."""
    return _apply_stated(raw, claims, "volume", "volume_growth", "volume growth", conflict_pp)


def apply_stated_sales(raw: pd.DataFrame, claims: list[VolumeClaim], conflict_pp: float = 1.0) -> pd.DataFrame:
    """Add a 'sales_growth' column (management-stated, same sentence as a volume figure)."""
    return _apply_stated(raw, claims, "sales", "sales_growth", "stated sales growth", conflict_pp)


def claims_to_dicts(claims: list[VolumeClaim]) -> list[dict]:
    return [asdict(c) for c in claims]
