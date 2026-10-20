"""Task 1.8: pure metric functions. No LLM, no I/O. Every function returns None (never a guess)
when its inputs are missing, so the caller can label proxies or lower the coverage score."""
from __future__ import annotations
from typing import Optional
from .. import config


def _ok(*xs) -> bool:
    return all(x is not None and x == x for x in xs)       # not None and not NaN


def growth(prev: Optional[float], curr: Optional[float]) -> Optional[float]:
    """Fractional growth, e.g. 0.12 for +12%."""
    if not _ok(prev, curr) or prev == 0:
        return None
    return curr / prev - 1.0


def price_volume_split(revenue_prev: Optional[float], revenue_curr: Optional[float],
                       volume_prev: Optional[float], volume_curr: Optional[float]) -> Optional[dict]:
    """Split revenue growth into volume and price/mix effects using revenue = price x volume.
    (1+g_rev) = (1+g_vol)(1+g_price). volume_effect = g_vol; price_mix_effect = g_rev - g_vol
    (includes the cross term), so the two always add up to total growth."""
    g_rev = growth(revenue_prev, revenue_curr)
    g_vol = growth(volume_prev, volume_curr)
    if g_rev is None or g_vol is None:
        return None
    g_price = (1 + g_rev) / (1 + g_vol) - 1 if (1 + g_vol) != 0 else None
    out = {"revenue_growth": g_rev, "volume_growth": g_vol, "price_mix_growth": g_price,
           "volume_effect": g_vol, "price_mix_effect": g_rev - g_vol, "is_proxy": False}
    out["price_share_of_growth"] = (out["price_mix_effect"] / g_rev) if abs(g_rev) > 1e-9 else None
    return out


def proxy_volume_from_deflator(revenue_growth: Optional[float], price_inflation: Optional[float]) -> Optional[dict]:
    """LABELLED PROXY when volume is not disclosed: deflate revenue growth by a relevant price index
    (e.g. a CPI sub-index). Result is flagged is_proxy=True and must lower the coverage score."""
    if not _ok(revenue_growth, price_inflation) or (1 + price_inflation) == 0:
        return None
    real = (1 + revenue_growth) / (1 + price_inflation) - 1
    return {"revenue_growth": revenue_growth, "volume_growth": real, "price_mix_growth": price_inflation,
            "volume_effect": real, "price_mix_effect": revenue_growth - real, "is_proxy": True,
            "price_share_of_growth": ((revenue_growth - real) / revenue_growth) if abs(revenue_growth) > 1e-9 else None}


def days_ratio(balance: Optional[float], flow: Optional[float], days: float) -> Optional[float]:
    if not _ok(balance, flow) or flow == 0:
        return None
    return balance / flow * days


def receivable_days(receivables: Optional[float], revenue: Optional[float], days: float = config.DAYS_IN_QUARTER) -> Optional[float]:
    """Trade receivables / revenue for the period x days in the period (91.25 for a quarter, 365 for a year)."""
    return days_ratio(receivables, revenue, days)


def inventory_days(inventory: Optional[float], cogs: Optional[float], days: float = config.DAYS_IN_QUARTER) -> Optional[float]:
    return days_ratio(inventory, cogs, days)


def payable_days(payables: Optional[float], cogs: Optional[float], days: float = config.DAYS_IN_QUARTER) -> Optional[float]:
    return days_ratio(payables, cogs, days)


def average_balance(open_bal: Optional[float], close_bal: Optional[float]) -> Optional[float]:
    return (open_bal + close_bal) / 2 if _ok(open_bal, close_bal) else None


def cash_conversion_cycle(dso: Optional[float], dio: Optional[float], dpo: Optional[float]) -> Optional[float]:
    return dso + dio - dpo if _ok(dso, dio, dpo) else None


def gross_margin(revenue: Optional[float], cogs: Optional[float]) -> Optional[float]:
    return (revenue - cogs) / revenue if _ok(revenue, cogs) and revenue != 0 else None


def operating_cash_conversion(cfo: Optional[float], ebitda: Optional[float]) -> Optional[float]:
    return cfo / ebitda if _ok(cfo, ebitda) and ebitda != 0 else None


def mix_shares(components: dict[str, Optional[float]]) -> Optional[dict[str, float]]:
    vals = {k: v for k, v in components.items() if _ok(v)}
    total = sum(vals.values())
    if not vals or total == 0:
        return None
    return {k: v / total for k, v in vals.items()}
