"""Map a supply-risk picture onto reorder-policy adjustments (pure).

Takes plain numbers (so the reorder domain stays independent of the intelligence
module) and produces a ``RiskAdjustment`` the engine understands:

  safety_stock_multiplier = 1 + ss_sensitivity * overall_risk
        higher overall risk → carry more buffer stock.

  lead_time_extra_days     = lead_sensitivity * lead_time_days * lead_time_risk
        risks that delay supply (freight, port, geopolitical) stretch the
        effective lead time, which raises the reorder point and pulls orders
        forward.

Both reduce to no-op when the risks are zero.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.reorder.domain.models import ONE, ZERO, RiskAdjustment

# Defaults (tunable per tenant/policy later).
SS_SENSITIVITY = Decimal("1.0")     # risk 1.0 ⇒ 2× safety stock
LEAD_SENSITIVITY = Decimal("0.5")   # full lead-time risk ⇒ +50% lead time
EXPEDITE_THRESHOLD = Decimal("0.4") # overall risk at/above which to flag expedite

_Q4 = Decimal("0.0001")


def _clamp01(v: Decimal) -> Decimal:
    return max(ZERO, min(ONE, v))


def build_risk_adjustment(
    *,
    overall_risk: Decimal,
    lead_time_risk: Decimal,
    demand_factor: Decimal,
    lead_time_days: Decimal,
    drivers: list[str],
    ss_sensitivity: Decimal = SS_SENSITIVITY,
    lead_sensitivity: Decimal = LEAD_SENSITIVITY,
) -> RiskAdjustment:
    overall = _clamp01(Decimal(overall_risk))
    lead_r = _clamp01(Decimal(lead_time_risk))
    ss_mult = (ONE + ss_sensitivity * overall).quantize(_Q4, rounding=ROUND_HALF_UP)
    lead_extra = (lead_sensitivity * Decimal(lead_time_days) * lead_r).quantize(
        _Q4, rounding=ROUND_HALF_UP
    )
    return RiskAdjustment(
        risk_score=overall,
        safety_stock_multiplier=ss_mult,
        lead_time_extra_days=lead_extra,
        demand_factor=Decimal(demand_factor),
        drivers=list(drivers),
    )


def should_expedite(overall_risk: Decimal) -> bool:
    return Decimal(overall_risk) >= EXPEDITE_THRESHOLD
