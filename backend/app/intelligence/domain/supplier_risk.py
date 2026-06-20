"""Pure supplier-risk scoring from delivery performance.

Turns observed supplier performance — on-time delivery, lead-time variability,
and fill rate — into a 0..1 risk score with explainable components and reasons.
This is the one intelligence category computable entirely from internal data
(purchase orders + receipts), so it is fully functional today.

    late_risk     = 1 - on_time_rate
    fill_risk     = 1 - fill_rate
    variance_risk = coefficient of variation of lead time (stdev / mean), capped at 1

Components with no data are dropped and the remaining weights renormalised, so a
supplier with partial history still gets a sensible score (with lower confidence,
which the provider sets from the sample size).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
ONE = Decimal("1")
_Q4 = Decimal("0.0001")

_WEIGHTS = {"late": Decimal("0.4"), "fill": Decimal("0.3"), "variance": Decimal("0.3")}


def _q(value: Decimal) -> Decimal:
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


def _clamp01(v: Decimal) -> Decimal:
    return max(ZERO, min(ONE, v))


@dataclass(frozen=True)
class SupplierMetrics:
    on_time_rate: float | None          # 0..1
    avg_lead_time_days: float | None
    lead_time_stdev_days: float | None
    fill_rate: float | None             # 0..1
    received_po_count: int = 0


@dataclass(frozen=True)
class SupplierRiskResult:
    risk_score: Decimal                  # 0..1
    reliability: Decimal                 # 1 - risk_score
    components: dict[str, Decimal] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def supplier_risk(m: SupplierMetrics) -> SupplierRiskResult:
    components: dict[str, Decimal] = {}
    reasons: list[str] = []

    if m.on_time_rate is not None:
        late = _clamp01(ONE - Decimal(str(m.on_time_rate)))
        components["late"] = _q(late)
        if late >= Decimal("0.2"):
            reasons.append(f"On-time delivery {round(m.on_time_rate * 100)}%")

    if m.fill_rate is not None:
        fill = _clamp01(ONE - Decimal(str(m.fill_rate)))
        components["fill"] = _q(fill)
        if fill >= Decimal("0.1"):
            reasons.append(f"Fill rate {round(m.fill_rate * 100)}%")

    if (
        m.avg_lead_time_days is not None
        and m.lead_time_stdev_days is not None
        and m.avg_lead_time_days > 0
    ):
        cov = Decimal(str(m.lead_time_stdev_days)) / Decimal(str(m.avg_lead_time_days))
        variance = _clamp01(cov)
        components["variance"] = _q(variance)
        if variance >= Decimal("0.3"):
            reasons.append(
                f"Lead time {round(m.avg_lead_time_days)}d ±{round(m.lead_time_stdev_days)}d (volatile)"
            )

    if not components:
        # No performance signal yet — neutral, low-information score.
        return SupplierRiskResult(risk_score=ZERO, reliability=ONE, components={}, reasons=["No delivery history"])

    weight_total = sum((_WEIGHTS[k] for k in components), ZERO)
    risk = sum((components[k] * _WEIGHTS[k] for k in components), ZERO) / weight_total
    risk = _q(_clamp01(risk))
    return SupplierRiskResult(
        risk_score=risk,
        reliability=_q(ONE - risk),
        components=components,
        reasons=reasons,
    )
