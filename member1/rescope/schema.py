"""Shared data contract (Task 1.1). Field names match the plan's contract; the extra optional
fields (publisher, flags, independent) are additive and have defaults, so Member 2's code
that only reads the contract fields keeps working."""
from __future__ import annotations
import datetime as dt
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    filing = "filing"
    results = "results"
    presentation = "presentation"
    transcript = "transcript"
    annual_report = "annual_report"
    news = "news"
    gov_macro = "gov_macro"
    industry = "industry"
    alt_data = "alt_data"
    community = "community"


class Role(str, Enum):
    company = "company"
    peer = "peer"
    industry = "industry"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Evidence(BaseModel):
    id: str
    title: str
    text: str
    url: str
    source_type: SourceType
    source_tier: int = Field(ge=1, le=5)
    date: Optional[dt.date] = None
    fetched_at: dt.datetime = Field(default_factory=_now)
    entity: str
    role: Role
    period: Optional[str] = None          # e.g. "Q2 FY26"
    locator: Optional[str] = None         # e.g. "p.12" or "p.12 table 2" or "series:cpi_food"
    origin_hash: str = ""
    claims: list[str] = Field(default_factory=list)
    # additive fields
    publisher: Optional[str] = None
    independent: bool = True
    flags: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def _url_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("every evidence item needs a URL (claims without a source are dropped)")
        return v.strip()


class PeerRef(BaseModel):
    name: str
    symbol: Optional[str] = None
    reason: str = ""
    mentioned_in_report: bool = False
    filings_available: bool = True
    score: float = 0.0


class CompanyProfile(BaseModel):
    input_name: str
    name: str
    nse_symbol: Optional[str] = None
    bse_code: Optional[str] = None
    isin: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    archetype: str = "unclassified"
    archetype_confidence: float = 0.0
    archetype_terms: list[str] = Field(default_factory=list)
    match_score: float = 0.0
    peers: list[PeerRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    resolved_at: dt.datetime = Field(default_factory=_now)


class MetricPoint(BaseModel):
    period: str
    value: Optional[float] = None
    unit: str = ""
    locator: Optional[str] = None
    evidence_id: Optional[str] = None
    is_proxy: bool = False
    note: str = ""


class MetricSeries(BaseModel):
    name: str
    entity: str
    role: Role
    unit: str = ""
    points: list[MetricPoint] = Field(default_factory=list)

    @property
    def has_proxy(self) -> bool:
        return any(p.is_proxy for p in self.points)

    def values(self) -> list[float]:
        return [p.value for p in self.points if p.value is not None]

    def periods(self) -> list[str]:
        return [p.period for p in self.points if p.value is not None]

    def to_frame(self):
        import pandas as pd
        return pd.DataFrame([p.model_dump() for p in self.points])


class CollectorResult(BaseModel):
    """What every collector returns: items plus errors, so one failing source never stops a run."""
    source: str
    items: list[Evidence] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    used_fallback: bool = False
