"""Supplier scorecard (pure) — internal delivery performance blended with
active intelligence into one explainable, gradeable supplier view.

Reuses the existing pure pieces rather than reimplementing them:
  * ``supplier_risk`` for the internal performance risk (on-time / variance / fill),
  * ``scoring.combine_severities`` (probabilistic-OR) to blend performance risk
    with intelligence risk so a supplier/country signal lowers the score.

No I/O, no framework — the service feeds it metrics, history, the internal risk
result, and an intelligence-risk number, and gets back a scorecard to persist.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.intelligence.domain.scoring import combine_severities
from app.intelligence.domain.supplier_risk import SupplierMetrics, SupplierRiskResult

ZERO = Decimal("0")
ONE = Decimal("1")
_Q4 = Decimal("0.0001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


def _dec(value) -> Decimal | None:
    return None if value is None else _q(Decimal(str(value)))


def _clamp01(value: Decimal) -> Decimal:
    return max(ZERO, min(ONE, value))


def grade_for(risk: Decimal) -> str:
    """Letter grade from blended risk (lower risk = better grade)."""
    if risk < Decimal("0.10"):
        return "A"
    if risk < Decimal("0.25"):
        return "B"
    if risk < Decimal("0.45"):
        return "C"
    if risk < Decimal("0.65"):
        return "D"
    return "F"


@dataclass(frozen=True)
class SupplierHistory:
    po_count: int = 0
    received_po_count: int = 0
    total_spend: Decimal = ZERO
    last_order_at: dt.datetime | None = None


@dataclass(frozen=True)
class SupplierScorecard:
    supplier_name: str
    on_time_rate: Decimal | None
    avg_lead_time_days: Decimal | None
    lead_time_stdev_days: Decimal | None
    lead_time_accuracy: Decimal | None      # 1 - lead-time coefficient of variation
    fill_rate: Decimal | None
    delivery_performance: Decimal | None     # on-time delivery rate
    reliability: Decimal                     # 1 - blended risk
    performance_risk: Decimal                # internal (delivery history)
    intelligence_risk: Decimal               # active supplier/country signals
    risk_score: Decimal                      # blended overall
    grade: str
    po_count: int
    received_po_count: int
    total_spend: Decimal
    last_order_at: dt.datetime | None
    drivers: list[str] = field(default_factory=list)


def build_scorecard(
    *,
    supplier_name: str,
    metrics: SupplierMetrics,
    history: SupplierHistory,
    internal: SupplierRiskResult,
    intelligence_risk: Decimal = ZERO,
    intel_drivers: list[str] | None = None,
) -> SupplierScorecard:
    performance_risk = _q(_clamp01(Decimal(internal.risk_score)))
    intel_risk = _q(_clamp01(Decimal(intelligence_risk)))
    overall = combine_severities([performance_risk, intel_risk])  # quantised

    lead_time_accuracy: Decimal | None = None
    if (
        metrics.avg_lead_time_days
        and metrics.lead_time_stdev_days is not None
        and metrics.avg_lead_time_days > 0
    ):
        cov = Decimal(str(metrics.lead_time_stdev_days)) / Decimal(str(metrics.avg_lead_time_days))
        lead_time_accuracy = _q(_clamp01(ONE - cov))

    return SupplierScorecard(
        supplier_name=supplier_name,
        on_time_rate=_dec(metrics.on_time_rate),
        avg_lead_time_days=_dec(metrics.avg_lead_time_days),
        lead_time_stdev_days=_dec(metrics.lead_time_stdev_days),
        lead_time_accuracy=lead_time_accuracy,
        fill_rate=_dec(metrics.fill_rate),
        delivery_performance=_dec(metrics.on_time_rate),
        reliability=_q(ONE - overall),
        performance_risk=performance_risk,
        intelligence_risk=intel_risk,
        risk_score=overall,
        grade=grade_for(overall),
        po_count=history.po_count,
        received_po_count=history.received_po_count,
        total_spend=_q(Decimal(history.total_spend or 0)),
        last_order_at=history.last_order_at,
        drivers=list(internal.reasons) + list(intel_drivers or []),
    )
