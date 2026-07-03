"""Unit tests for the pure unified-sales-log aggregation (no DB).

Covers the correctness rules from the spec: daily / weekly / monthly bucketing,
type isolation, NO DOUBLE COUNT (every event counted once; total == parts + bikes),
and that imported-historical motorcycle sales appear and stay distinguishable.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.reports import sales_log as SL


def _ev(day: str, kind: str, units, revenue) -> SL.SaleEvent:
    return SL.SaleEvent(day=dt.date.fromisoformat(day), kind=kind,
                        units=Decimal(str(units)), revenue=Decimal(str(revenue)))


# A mixed set spanning two ISO weeks (W27 Mon 2026-06-29..Sun 07-05) and July.
MIXED = [
    _ev("2026-06-29", SL.PARTS, 3, 300),          # Mon, W27
    _ev("2026-07-01", SL.PARTS, 2, 200),          # Wed, W27
    _ev("2026-07-01", SL.MOTO_NEW, 1, 1500),      # Wed, W27
    _ev("2026-07-03", SL.MOTO_HISTORICAL, 1, 900),  # Fri, W27
    _ev("2026-07-06", SL.PARTS, 1, 100),          # Mon, W28 / July
    _ev("2026-07-06", SL.MOTO_NEW, 1, 1600),      # Mon, W28 / July
]


def _by_label(rows):
    return {r["label"]: r for r in rows}


def test_daily_buckets_and_no_double_count():
    rows, totals = SL.build_sales_log(MIXED, granularity=SL.DAILY, type_filter=SL.TYPE_ALL)
    days = _by_label(rows)
    # One row per distinct day.
    assert set(days) == {"2026-06-29", "2026-07-01", "2026-07-03", "2026-07-06"}
    # 2026-07-01: parts 200 + a bike 1500 = 1700, units 2+1 = 3.
    assert days["2026-07-01"]["revenue"] == Decimal("1700")
    assert days["2026-07-01"]["units"] == Decimal("3")
    # Grand totals == the plain sum of every event, once.
    assert totals["revenue"] == Decimal("4600")   # 300+200+1500+900+100+1600
    assert totals["units"] == Decimal("9")         # 3+2+1+1+1+1
    # Newest first.
    assert [r["label"] for r in rows] == ["2026-07-06", "2026-07-03", "2026-07-01", "2026-06-29"]


def test_weekly_buckets_group_by_iso_week_monday():
    rows, _ = SL.build_sales_log(MIXED, granularity=SL.WEEKLY, type_filter=SL.TYPE_ALL)
    weeks = _by_label(rows)
    assert set(weeks) == {"2026-W27", "2026-W28"}
    # W27 gathers 06-29, 07-01 (x2), 07-03 => 300+200+1500+900 = 2900.
    assert weeks["2026-W27"]["revenue"] == Decimal("2900")
    assert weeks["2026-W27"]["period_start"] == dt.date(2026, 6, 29)
    assert weeks["2026-W27"]["period_end"] == dt.date(2026, 7, 5)
    # W28 gathers 07-06 => 100 + 1600 = 1700.
    assert weeks["2026-W28"]["revenue"] == Decimal("1700")


def test_monthly_buckets():
    rows, totals = SL.build_sales_log(MIXED, granularity=SL.MONTHLY, type_filter=SL.TYPE_ALL)
    months = _by_label(rows)
    assert set(months) == {"2026-06", "2026-07"}
    assert months["2026-06"]["revenue"] == Decimal("300")
    assert months["2026-06"]["period_end"] == dt.date(2026, 6, 30)
    assert months["2026-07"]["revenue"] == Decimal("4300")  # everything except 06-29
    assert totals["revenue"] == Decimal("4600")


def test_type_filter_isolates_streams():
    _, parts = SL.build_sales_log(MIXED, granularity=SL.MONTHLY, type_filter=SL.TYPE_PARTS)
    _, bikes = SL.build_sales_log(MIXED, granularity=SL.MONTHLY, type_filter=SL.TYPE_MOTORCYCLES)
    # Parts-only excludes every motorcycle event, and vice versa.
    assert parts["revenue"] == Decimal("600")     # 300+200+100
    assert SL.MOTO_NEW not in parts["by_kind"] and SL.MOTO_HISTORICAL not in parts["by_kind"]
    assert bikes["revenue"] == Decimal("4000")    # 1500+900+1600
    assert SL.PARTS not in bikes["by_kind"]
    # The two partitions reconstitute the whole — no double count, nothing dropped.
    assert parts["revenue"] + bikes["revenue"] == Decimal("4600")


def test_historical_motorcycles_appear_and_stay_distinguishable():
    rows, totals = SL.build_sales_log(MIXED, granularity=SL.MONTHLY, type_filter=SL.TYPE_ALL)
    # Historical bikes are tracked as their own kind, separate from new-unit sales.
    assert totals["by_kind"][SL.MOTO_HISTORICAL]["revenue"] == Decimal("900")
    assert totals["by_kind"][SL.MOTO_HISTORICAL]["units"] == Decimal("1")
    assert totals["by_kind"][SL.MOTO_NEW]["revenue"] == Decimal("3100")  # 1500+1600
    # The July row breaks down into all three components.
    july = _by_label(rows)["2026-07"]
    kinds = {c["type"] for c in july["components"]}
    assert kinds == {SL.PARTS, SL.MOTO_NEW, SL.MOTO_HISTORICAL}


def test_empty_and_bad_inputs():
    rows, totals = SL.build_sales_log([], granularity=SL.DAILY, type_filter=SL.TYPE_ALL)
    assert rows == [] and totals["revenue"] == Decimal("0") and totals["units"] == Decimal("0")
    for bad in ("hourly", "yearly", ""):
        try:
            SL.build_sales_log(MIXED, granularity=bad, type_filter=SL.TYPE_ALL)
            raise AssertionError(f"expected ValueError for granularity {bad!r}")
        except ValueError:
            pass
