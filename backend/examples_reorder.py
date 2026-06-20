"""Runnable, dependency-free demonstration of the reorder engine.

    python examples_reorder.py

Uses only the pure domain core (no database, no FastAPI). Every number printed
is computed by the same code the API uses.
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
from app.reorder.domain.rounding import enforce_order_quantity

LINE = "-" * 78


def _rule_examples() -> None:
    print(LINE)
    print("BUSINESS RULE EXAMPLES (full-carton rounding + MOQ enforcement)")
    print(LINE)

    a = enforce_order_quantity(Decimal("67"), units_per_carton=10, moq=0)
    print(f"FULL CARTON: units_per_carton=10, calculated=67 -> {a.recommended_units} "
          f"({a.cartons} cartons)   [expected 70]")

    b = enforce_order_quantity(Decimal("320"), units_per_carton=1, moq=500)
    print(f"MOQ        : moq=500, calculated=320 -> {b.recommended_units} "
          f"(applied_moq={b.applied_moq})   [expected 500]")

    c = enforce_order_quantity(Decimal("505"), units_per_carton=10, moq=500)
    print(f"COMBINED   : upc=10, moq=500, calculated=505 -> {c.recommended_units} "
          f"({c.cartons} cartons)   [MOQ met, still whole cartons]")
    print()


def _show(title: str, policy: ReorderPolicy, demand: DemandStatistics, stock: StockPosition) -> None:
    r = compute_reorder(policy, demand, stock)
    print(LINE)
    print(title)
    print(LINE)
    print(f"  avg daily demand : {r.avg_daily_demand}   avg monthly : {r.avg_monthly_sales}"
          f"   std/day : {r.std_dev_daily}")
    print(f"  lead time (days) : {r.lead_time_days}   review period : {r.review_period_days}"
          f"   UPC : {r.units_per_carton}   MOQ : {r.moq}")
    print(f"  safety stock     : {r.safety_stock}   [{r.safety_stock_method}]")
    print(f"  reorder point    : {r.reorder_point}   order-up-to : {r.order_up_to_level}")
    print(f"  on hand {r.on_hand} | reserved {r.reserved} | available {r.available} "
          f"| on order {r.on_order} | position {r.inventory_position}")
    print(f"  >> should_reorder = {r.should_reorder}   recommend = {r.recommended_units} units "
          f"({r.recommended_cartons} cartons)   applied_moq = {r.applied_moq}")
    print(f"  {r.reason}")
    print()


def main() -> None:
    _rule_examples()

    days_cover = SafetyStockMethod.DAYS_COVER

    _show(
        "1) HEALTHY STOCK — no order needed",
        ReorderPolicy(units_per_carton=12, moq=0, lead_time_days=Decimal(10),
                      safety_days=Decimal(7), method=days_cover),
        DemandStatistics(avg_daily=Decimal(5), std_dev_daily=Decimal(0),
                         sample_days=90, days_with_sales=90, total_units=Decimal(450)),
        StockPosition(on_hand=Decimal(200)),
    )

    _show(
        "2) BELOW REORDER POINT — order to the target level (review period 14d)",
        ReorderPolicy(units_per_carton=12, moq=0, lead_time_days=Decimal(10),
                      review_period_days=Decimal(14), safety_days=Decimal(7), method=days_cover),
        DemandStatistics(avg_daily=Decimal(5), std_dev_daily=Decimal(0),
                         sample_days=90, days_with_sales=90, total_units=Decimal(450)),
        StockPosition(on_hand=Decimal(40)),
    )

    _show(
        "3) MOQ-BINDING — small need, but supplier MOQ forces a larger order",
        ReorderPolicy(units_per_carton=10, moq=500, lead_time_days=Decimal(7),
                      safety_days=Decimal(5), method=days_cover),
        DemandStatistics(avg_daily=Decimal(2), std_dev_daily=Decimal(0),
                         sample_days=90, days_with_sales=60, total_units=Decimal(180)),
        StockPosition(on_hand=Decimal(5)),
    )

    _show(
        "4) CARTON-BINDING — raw qty rounds up to whole cartons",
        ReorderPolicy(units_per_carton=24, moq=0, lead_time_days=Decimal(10),
                      safety_days=Decimal(7), method=days_cover),
        DemandStatistics(avg_daily=Decimal("3.3"), std_dev_daily=Decimal(0),
                         sample_days=90, days_with_sales=70, total_units=Decimal(297)),
        StockPosition(on_hand=Decimal(20)),
    )

    # Statistical safety stock from a 10-day demand sample [10,12,8,11,9,10,13,7,10,10]
    # total=100, sum_of_squares=1028, window=10.
    _show(
        "5) STATISTICAL SAFETY STOCK — buffers demand variability over lead time",
        ReorderPolicy(units_per_carton=6, moq=0, lead_time_days=Decimal(9),
                      service_level=Decimal("0.95"), method=SafetyStockMethod.STATISTICAL),
        DemandStatistics.from_aggregates(total_units=100, sum_of_squares=1028,
                                         window_days=10, days_with_sales=10),
        StockPosition(on_hand=Decimal(50)),
    )

    _show(
        "6) ZERO DEMAND — nothing sells, nothing on hand: no order",
        ReorderPolicy(units_per_carton=10, safety_days=Decimal(7), method=days_cover),
        DemandStatistics.zero(window_days=90),
        StockPosition(on_hand=Decimal(0)),
    )

    _show(
        "7) ON-ORDER SUPPRESSES REORDER — inbound stock covers the gap",
        ReorderPolicy(units_per_carton=12, lead_time_days=Decimal(10),
                      safety_days=Decimal(7), method=days_cover),
        DemandStatistics(avg_daily=Decimal(5), std_dev_daily=Decimal(0),
                         sample_days=90, days_with_sales=90, total_units=Decimal(450)),
        StockPosition(on_hand=Decimal(40), on_order=Decimal(100)),
    )

    _show(
        "8) RESERVED STOCK REDUCES AVAILABILITY — triggers despite high on-hand",
        ReorderPolicy(units_per_carton=12, lead_time_days=Decimal(10),
                      review_period_days=Decimal(7), safety_days=Decimal(7), method=days_cover),
        DemandStatistics(avg_daily=Decimal(5), std_dev_daily=Decimal(0),
                         sample_days=90, days_with_sales=90, total_units=Decimal(450)),
        StockPosition(on_hand=Decimal(100), reserved=Decimal(80)),
    )

    _show(
        "9) MANUAL REORDER-POINT OVERRIDE — formula ignored in favour of override",
        ReorderPolicy(units_per_carton=12, lead_time_days=Decimal(10), safety_days=Decimal(7),
                      method=days_cover, reorder_point_override=Decimal(50)),
        DemandStatistics(avg_daily=Decimal(5), std_dev_daily=Decimal(0),
                         sample_days=90, days_with_sales=90, total_units=Decimal(450)),
        StockPosition(on_hand=Decimal(60)),
    )


if __name__ == "__main__":
    main()
