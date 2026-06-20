"""Unit tests for risk-aware reorder computation."""
from __future__ import annotations

from decimal import Decimal

from app.reorder.domain.engine import compute_reorder
from app.reorder.domain.models import (
    DemandStatistics,
    ReorderPolicy,
    RiskAdjustment,
    SafetyStockMethod,
    StockPosition,
)
from app.reorder.domain.risk import build_risk_adjustment

D = Decimal


def _policy(**kw):
    base = dict(
        units_per_carton=10, moq=0, lead_time_days=D("7"), review_period_days=D("0"),
        safety_days=D("7"), method=SafetyStockMethod.DAYS_COVER,
    )
    base.update(kw)
    return ReorderPolicy(**base)


def _demand(avg="2"):
    return DemandStatistics(
        avg_daily=D(avg), std_dev_daily=D("0"), sample_days=90, days_with_sales=90,
        total_units=D(avg) * 90,
    )


def _stock(on_hand="5"):
    return StockPosition(on_hand=D(on_hand))


def test_no_risk_is_identity_and_backward_compatible():
    p, d, s = _policy(), _demand(), _stock()
    plain = compute_reorder(p, d, s)
    explicit = compute_reorder(p, d, s, RiskAdjustment())
    assert plain == explicit
    # known baseline: SS=14, ROP=28, recommend 30
    assert plain.safety_stock == D("14.0000")
    assert plain.reorder_point == D("28.0000")
    assert plain.recommended_units == 30
    assert plain.risk_applied is False
    assert plain.risk_score == D("0.0000")
    assert plain.effective_lead_time_days == D("7.0000")
    assert plain.expedite is False


def test_risk_raises_safety_stock_reorder_point_and_quantity():
    risk = build_risk_adjustment(
        overall_risk=D("0.5"), lead_time_risk=D("0.5"), demand_factor=D("1"),
        lead_time_days=D("7"), drivers=["Acme unreliable", "Shanghai congestion"],
    )
    # ss_mult = 1.5, lead_extra = 0.5*7*0.5 = 1.75
    assert risk.safety_stock_multiplier == D("1.5000")
    assert risk.lead_time_extra_days == D("1.7500")

    r = compute_reorder(_policy(), _demand(), _stock(), risk)
    assert r.safety_stock == D("21.0000")          # 14 * 1.5
    assert r.effective_lead_time_days == D("8.7500")  # 7 + 1.75
    assert r.reorder_point == D("38.5000")         # 2*8.75 + 21
    assert r.recommended_units == 40               # vs 30 without risk
    assert r.risk_applied is True
    assert r.risk_score == D("0.5000")
    assert r.expedite is True                      # risk >= 0.4 and should_reorder
    assert "Acme unreliable" in r.reason


def test_manual_reorder_point_override_is_a_floor_plus_risk():
    risk = build_risk_adjustment(
        overall_risk=D("0.5"), lead_time_risk=D("0.5"), demand_factor=D("1"),
        lead_time_days=D("7"), drivers=[],
    )
    r = compute_reorder(_policy(reorder_point_override=D("100")), _demand(), _stock(), risk)
    # 100 + add*lead_extra (2*1.75=3.5) + (21-14)=7  -> 110.5
    assert r.reorder_point == D("110.5000")
    assert r.safety_stock == D("21.0000")


def test_demand_factor_lifts_demand_rate():
    risk = build_risk_adjustment(
        overall_risk=D("0"), lead_time_risk=D("0"), demand_factor=D("1.5"),
        lead_time_days=D("7"), drivers=[],
    )
    r = compute_reorder(_policy(), _demand("2"), _stock(), risk)
    assert r.avg_daily_demand == D("3.0000")       # 2 * 1.5


def test_build_risk_adjustment_clamps_and_maps():
    risk = build_risk_adjustment(
        overall_risk=D("1.5"), lead_time_risk=D("-0.2"), demand_factor=D("1"),
        lead_time_days=D("10"), drivers=["x"],
    )
    assert risk.risk_score == D("1")               # clamped to 1
    assert risk.safety_stock_multiplier == D("2.0000")  # 1 + 1*1
    assert risk.lead_time_extra_days == D("0.0000")     # lead risk clamped to 0
