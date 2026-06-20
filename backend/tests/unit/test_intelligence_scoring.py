"""Unit tests for intelligence risk aggregation."""
from __future__ import annotations

from decimal import Decimal

from app.intelligence.domain.scoring import (
    ScopedAdjustment,
    assess,
    combine_risk_factor,
)

D = Decimal


def _adj(category, severity, factor="1", conf="0.8", headline="h"):
    return ScopedAdjustment(category=category, severity=D(severity), demand_factor=D(factor),
                            confidence=D(conf), headline=headline)


def test_no_observations_is_zero_risk_full_confidence():
    a = assess([])
    assert a.risk_score == D("0")
    assert a.demand_factor == D("1")
    assert a.confidence == D("1")
    assert a.actions == []


def test_single_observation_risk_and_category_breakdown():
    a = assess([_adj("supplier", "0.5", conf="0.9", headline="Acme unreliable")])
    assert a.risk_score == D("0.5000")
    assert a.by_category["supplier"] == D("0.5000")
    assert a.confidence == D("0.9000")
    assert any("Supplier reliability" in x for x in a.actions)
    assert a.drivers == ["Acme unreliable"]


def test_risk_uses_probabilistic_or():
    # two independent 0.5 risks -> 1 - 0.5*0.5 = 0.75
    a = assess([_adj("freight", "0.5"), _adj("port", "0.5")])
    assert a.risk_score == D("0.7500")


def test_demand_factor_is_product():
    a = assess([_adj("trade", "0.1", factor="1.2"), _adj("commodity", "0.1", factor="1.5")])
    assert a.demand_factor == D("1.8000")  # 1.2 * 1.5


def test_high_overall_risk_adds_global_action_first():
    a = assess([_adj("port", "0.6"), _adj("freight", "0.5")])
    assert a.risk_score >= D("0.5")
    assert a.actions[0].startswith("Elevated overall supply risk")


def test_combine_risk_factor_helper():
    risk, factor = combine_risk_factor([_adj("a", "0.5", factor="1.1"), _adj("b", "0.5", factor="2.0")])
    assert risk == D("0.7500")
    assert factor == D("2.2000")
