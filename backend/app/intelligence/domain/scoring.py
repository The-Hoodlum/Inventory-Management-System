"""Pure risk-aggregation for supply-chain intelligence.

Combines a set of scoped intelligence observations into a single, explainable
assessment: an overall supply-risk score, a composite demand factor, a
confidence score, a per-category breakdown, and rule-based recommended actions.

Risk aggregation uses the probabilistic-OR (complement product):

    risk = 1 - Π (1 - severity_i)

which stays bounded in [0, 1], rises monotonically as risks accumulate, and
never lets one extreme value silently dominate or overflow. The demand factor is
the product of each observation's multiplicative factor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
ONE = Decimal("1")
_Q4 = Decimal("0.0001")

# Risk band at/above which a category triggers a recommended action.
_ACTION_THRESHOLD = Decimal("0.25")
_HIGH_RISK = Decimal("0.5")

_CATEGORY_ACTIONS: dict[str, str] = {
    "freight": "Freight costs/capacity under pressure — consolidate shipments, lock rates, or bring orders forward.",
    "port": "Port congestion / vessel delays — add buffer to lead times and consider alternate ports or routings.",
    "commodity": "Input commodity prices moving — bring forward purchasing, hedge, or review selling prices.",
    "trade": "Trade / tariff change — review duty exposure and evaluate alternate sourcing countries.",
    "supplier": "Supplier reliability is degraded — diversify sourcing and raise safety stock for affected items.",
    "geopolitical": "Geopolitical disruption — qualify backup suppliers and increase safety stock on exposed lines.",
}


def _q(value: Decimal) -> Decimal:
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ScopedAdjustment:
    """A single observation reduced to its decision-relevant numbers."""

    category: str
    severity: Decimal            # 0..1 risk contribution
    demand_factor: Decimal       # multiplicative demand effect (1 = none)
    confidence: Decimal          # 0..1
    headline: str


@dataclass(frozen=True)
class RiskAssessment:
    risk_score: Decimal                      # 0..1
    demand_factor: Decimal                   # composite multiplicative
    confidence: Decimal                      # 0..1
    by_category: dict[str, Decimal] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
    drivers: list[str] = field(default_factory=list)


def _combine_severity(severities: list[Decimal]) -> Decimal:
    product = ONE
    for s in severities:
        s = max(ZERO, min(ONE, s))
        product *= (ONE - s)
    return ONE - product


def combine_severities(severities: list[Decimal]) -> Decimal:
    """Probabilistic-OR combine of raw severities (used for category sub-scores)."""
    return _q(_combine_severity(severities))


def combine_risk_factor(adjustments: list[ScopedAdjustment]) -> tuple[Decimal, Decimal]:
    """Merge adjustments into a single (risk_score, demand_factor) pair — used by
    the forecast-signal bridge to collapse all matching intelligence into one
    SignalAdjustment for the pipeline."""
    risk = _combine_severity([a.severity for a in adjustments])
    factor = ONE
    for a in adjustments:
        factor *= a.demand_factor
    return _q(risk), _q(factor)


def assess(observations: list[ScopedAdjustment]) -> RiskAssessment:
    """Aggregate observations into an explainable risk assessment."""
    if not observations:
        # No known risks → zero risk, no demand change, full confidence.
        return RiskAssessment(risk_score=ZERO, demand_factor=ONE, confidence=ONE)

    by_cat_sev: dict[str, list[Decimal]] = {}
    demand_factor = ONE
    for obs in observations:
        by_cat_sev.setdefault(obs.category, []).append(obs.severity)
        demand_factor *= obs.demand_factor

    by_category = {cat: _q(_combine_severity(sevs)) for cat, sevs in by_cat_sev.items()}
    risk_score = _combine_severity([o.severity for o in observations])

    # Confidence: severity-weighted mean (more severe signals matter more); falls
    # back to a simple mean when every severity is zero.
    weight_sum = sum((o.severity for o in observations), ZERO)
    if weight_sum > 0:
        confidence = sum((o.confidence * o.severity for o in observations), ZERO) / weight_sum
    else:
        confidence = sum((o.confidence for o in observations), ZERO) / Decimal(len(observations))

    # Recommended actions: per-category over threshold, plus a global one if high.
    actions: list[str] = []
    for cat, risk in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True):
        if risk >= _ACTION_THRESHOLD and cat in _CATEGORY_ACTIONS:
            actions.append(_CATEGORY_ACTIONS[cat])
    if risk_score >= _HIGH_RISK:
        actions.insert(0, "Elevated overall supply risk — review reorder points and increase safety stock on exposed items.")

    drivers = [o.headline for o in sorted(observations, key=lambda o: o.severity, reverse=True)[:5]]

    return RiskAssessment(
        risk_score=_q(risk_score),
        demand_factor=_q(demand_factor),
        confidence=_q(min(ONE, max(ZERO, confidence))),
        by_category=by_category,
        actions=actions,
        drivers=drivers,
    )
