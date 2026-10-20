"""Task 1.11 (part 1): pair management statements with measurable metrics. Rules are generic
(angle library from the plan) and company-free. Verdict is based on the metric trend over the
recent window; if the needed series is missing the verdict is 'insufficient' (never a guess)."""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from typing import Callable, Optional
from ..schema import MetricSeries
from ..quant.benchmark import trend


@dataclass
class Statement:
    text: str
    evidence_id: str
    period: Optional[str] = None


@dataclass
class Rule:
    name: str
    pattern: re.Pattern
    metric: str
    expected: str          # 'up' | 'down_or_flat' | 'up_or_flat'
    angle: str
    describe: str


RULES: list[Rule] = [
    Rule("volume_led_growth", re.compile(r"volume[- ]led|volume growth|broad[- ]based growth|underlying volume", re.I),
         "volume_growth_yoy", "up", "Growth quality", "volume growth should be positive and rising"),
    Rule("price_not_driving", re.compile(r"not (driven|led) by (price|pricing)|growth is not price", re.I),
         "price_share_of_growth", "down_or_flat", "Growth quality", "price share of growth should be low"),
    Rule("channel_health", re.compile(r"channel (is )?healthy|healthy channel|distributor (health|inventory)|channel inventor", re.I),
         "receivable_days", "down_or_flat", "Working capital", "receivable days should be stable or falling"),
    Rule("inventory_control", re.compile(r"inventor(y|ies) (is |are )?(under control|well managed|optimi[sz]ed|lean)", re.I),
         "inventory_days", "down_or_flat", "Working capital", "inventory days should be stable or falling"),
    Rule("margin_resilience", re.compile(r"margin (resilience|expansion|improvement|is stable|remain(s|ed)? stable)", re.I),
         "gross_margin", "up_or_flat", "Margin and cost", "gross margin should be stable or rising"),
    Rule("premiumisation", re.compile(r"premiumi[sz]ation|premium(ising)? mix|mix improvement", re.I),
         "price_mix_growth_yoy", "up", "Growth quality", "price/mix growth should be positive"),
    Rule("cash_generation", re.compile(r"strong cash (generation|conversion)|cash conversion (is )?(strong|improv)", re.I),
         "cash_conversion_cycle", "down_or_flat", "Working capital", "cash conversion cycle should be stable or shorter"),
]


@dataclass
class SayDoRow:
    statement: str
    evidence_id: str
    rule: str
    angle: str
    expected: str
    metric: str
    verdict: str                # aligned | misaligned | insufficient
    observed_direction: Optional[str]
    relative_change: Optional[float]
    detail: str


def _judge(expected: str, direction: str) -> bool:
    return {"up": direction == "up", "down_or_flat": direction in ("down", "flat"),
            "up_or_flat": direction in ("up", "flat")}[expected]


def evaluate(statements: list[Statement], metrics: dict[str, MetricSeries], window: int = 6,
             rules: Optional[list[Rule]] = None) -> list[SayDoRow]:
    rows: list[SayDoRow] = []
    for st in statements:
        for rule in rules or RULES:
            if not rule.pattern.search(st.text):
                continue
            series = metrics.get(rule.metric)
            t = trend(series.values(), window) if series else None
            if t is None:
                rows.append(SayDoRow(st.text, st.evidence_id, rule.name, rule.angle, rule.expected, rule.metric,
                                     "insufficient", None, None, f"metric '{rule.metric}' missing or too short"))
                continue
            ok = _judge(rule.expected, t["direction"])
            proxy = " (series contains proxy values)" if series.has_proxy else ""
            rows.append(SayDoRow(st.text, st.evidence_id, rule.name, rule.angle, rule.expected, rule.metric,
                                 "aligned" if ok else "misaligned", t["direction"], round(t["relative_change"], 4),
                                 f"{rule.describe}; observed {t['direction']} ({t['relative_change']:+.1%}){proxy}"))
    return rows


def to_dicts(rows: list[SayDoRow]) -> list[dict]:
    return [asdict(r) for r in rows]
