"""Scenario tests for the reorder engine (pure domain, no DB/async).

These mirror the worked examples in examples_reorder.py / REORDER_ENGINE.md and
lock in the engine's behaviour across the required situations.
"""
from __future__ import annotations

from decimal import Decimal

from app.reorder.domain.engine import compute_reorder
from app.reorder.domain.models import (
    DemandStatistics,
    ReorderPolicy,
    SafetyStockMethod,
    StockPosition,
)

DC = SafetyStockMethod.DAYS_COVER


def _steady_demand(avg: str | int) -> DemandStatistics:
    return DemandStatistics(
        avg_daily=Decimal(avg),
        std_dev_daily=Decimal(0),
        sample_days=90,
        days_with_sales=90,
        total_units=Decimal(avg) * Decimal(90),
    )


def test_healthy_stock_no_order():
    r = compute_reorder(
        ReorderPolicy(units_per_carton=12, lead_time_days=Decimal(10), safety_days=Decimal(7), method=DC),
        _steady_demand(5),
        StockPosition(on_hand=Decimal(200)),
    )
    assert r.reorder_point == Decimal("85")          # 5*10 + 5*7
    assert r.should_reorder is False
    assert r.recommended_units == 0


def test_below_reorder_point_orders_to_target():
    r = compute_reorder(
        ReorderPolicy(units_per_carton=12, lead_time_days=Decimal(10),
                      review_period_days=Decimal(14), safety_days=Decimal(7), method=DC),
        _steady_demand(5),
        StockPosition(on_hand=Decimal(40)),
    )
    assert r.reorder_point == Decimal("85")
    assert r.order_up_to_level == Decimal("155")      # 5*(10+14) + 35
    assert r.should_reorder is True
    assert r.raw_order_qty == Decimal("115")          # 155 - 40
    assert r.recommended_units == 120                 # ceil(115/12)=10 -> 120
    assert r.recommended_cartons == 10
    assert r.applied_moq is False


def test_moq_binding():
    r = compute_reorder(
        ReorderPolicy(units_per_carton=10, moq=500, lead_time_days=Decimal(7), safety_days=Decimal(5), method=DC),
        _steady_demand(2),
        StockPosition(on_hand=Decimal(5)),
    )
    assert r.should_reorder is True
    assert r.recommended_units == 500
    assert r.recommended_cartons == 50
    assert r.applied_moq is True


def test_carton_binding():
    r = compute_reorder(
        ReorderPolicy(units_per_carton=24, lead_time_days=Decimal(10), safety_days=Decimal(7), method=DC),
        _steady_demand("3.3"),
        StockPosition(on_hand=Decimal(20)),
    )
    assert r.reorder_point == Decimal("56.1")         # 3.3*10 + 3.3*7
    assert r.recommended_units == 48                  # ceil(36.1/24)=2 -> 48
    assert r.recommended_cartons == 2
    assert r.applied_moq is False


def test_statistical_safety_stock():
    # demand sample [10,12,8,11,9,10,13,7,10,10]: total=100, sum_sq=1028, window=10
    demand = DemandStatistics.from_aggregates(
        total_units=100, sum_of_squares=1028, window_days=10, days_with_sales=10
    )
    assert demand.avg_daily == Decimal("10")
    assert demand.std_dev_daily.quantize(Decimal("0.0001")) == Decimal("1.6733")

    r = compute_reorder(
        ReorderPolicy(units_per_carton=6, lead_time_days=Decimal(9),
                      service_level=Decimal("0.95"), method=SafetyStockMethod.STATISTICAL),
        demand,
        StockPosition(on_hand=Decimal(50)),
    )
    assert r.safety_stock == Decimal("8.2573")        # 1.6449 * 1.6733 * sqrt(9)
    assert r.reorder_point == Decimal("98.2573")
    assert r.recommended_units == 54                  # ceil(48.2573/6)=9 -> 54
    assert "statistical" in r.safety_stock_method


def test_zero_demand_zero_stock_no_order():
    r = compute_reorder(
        ReorderPolicy(units_per_carton=10, safety_days=Decimal(7), method=DC),
        DemandStatistics.zero(window_days=90),
        StockPosition(on_hand=Decimal(0)),
    )
    assert r.reorder_point == Decimal("0")
    assert r.recommended_units == 0                   # at ROP but gap is zero


def test_on_order_suppresses_reorder():
    r = compute_reorder(
        ReorderPolicy(units_per_carton=12, lead_time_days=Decimal(10), safety_days=Decimal(7), method=DC),
        _steady_demand(5),
        StockPosition(on_hand=Decimal(40), on_order=Decimal(100)),
    )
    assert r.inventory_position == Decimal("140")
    assert r.should_reorder is False
    assert r.recommended_units == 0


def test_reserved_reduces_availability_and_triggers():
    r = compute_reorder(
        ReorderPolicy(units_per_carton=12, lead_time_days=Decimal(10),
                      review_period_days=Decimal(7), safety_days=Decimal(7), method=DC),
        _steady_demand(5),
        StockPosition(on_hand=Decimal(100), reserved=Decimal(80)),
    )
    assert r.available == Decimal("20")
    assert r.should_reorder is True
    assert r.recommended_units == 108                 # target 120, gap 100 -> ceil(100/12)=9 -> 108


def test_reorder_point_override_wins():
    r = compute_reorder(
        ReorderPolicy(units_per_carton=12, lead_time_days=Decimal(10), safety_days=Decimal(7),
                      method=DC, reorder_point_override=Decimal(50)),
        _steady_demand(5),
        StockPosition(on_hand=Decimal(60)),
    )
    assert r.reorder_point == Decimal("50")           # formula (85) ignored
    assert r.should_reorder is False


def test_safety_stock_override_wins():
    r = compute_reorder(
        ReorderPolicy(units_per_carton=12, lead_time_days=Decimal(10), safety_days=Decimal(7),
                      method=DC, safety_stock_override=Decimal(99)),
        _steady_demand(5),
        StockPosition(on_hand=Decimal(1000)),
    )
    assert r.safety_stock == Decimal("99")
    assert r.safety_stock_method == "override"
    assert r.reorder_point == Decimal("149")          # 5*10 + 99


def test_order_up_to_never_below_reorder_point():
    # review_period=0 and a high ROP override: S must be clamped up to ROP.
    r = compute_reorder(
        ReorderPolicy(units_per_carton=10, lead_time_days=Decimal(5), safety_days=Decimal(0),
                      method=DC, reorder_point_override=Decimal(1000)),
        _steady_demand(2),
        StockPosition(on_hand=Decimal(0)),
    )
    assert r.reorder_point == Decimal("1000")
    assert r.order_up_to_level >= r.reorder_point
    assert r.should_reorder is True
    assert r.recommended_units >= 1000
