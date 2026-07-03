"""Pure aggregation for the unified sales log — standard library only (no DB /
pydantic). Buckets spare-part and motorcycle sale *events* into daily / weekly /
monthly periods, split by type.

NO DOUBLE COUNT: the two revenue streams are disjoint by construction — a spare
part's value is an ``invoice_lines`` row; a motorcycle's value is on the unit
(``price_charged``), never an invoice line. The parts source additionally excludes
motorcycle-linked invoices (see ``app/sales/repository.py``). So every sale is
counted exactly once, and the pure math here only ever ADDS an event to one period
bucket and one type component.

This is the ONE shared aggregation reused by the sales-log report and any dashboard
sales KPI: feed it events, pick a granularity + type filter, get period rows + totals.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

# Sale-event kinds (a component within a period).
PARTS = "parts"
MOTO_NEW = "motorcycle_new"
MOTO_HISTORICAL = "motorcycle_historical"

KIND_LABELS = {
    PARTS: "Spare Parts",
    MOTO_NEW: "Motorcycles",
    MOTO_HISTORICAL: "Motorcycles (historical)",
}

# Granularities.
DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
GRANULARITIES = frozenset({DAILY, WEEKLY, MONTHLY})

# Type filters (which kinds are included).
TYPE_ALL = "all"
TYPE_PARTS = "parts"
TYPE_MOTORCYCLES = "motorcycles"
TYPE_FILTERS = frozenset({TYPE_ALL, TYPE_PARTS, TYPE_MOTORCYCLES})

_KINDS_BY_TYPE = {
    TYPE_ALL: frozenset({PARTS, MOTO_NEW, MOTO_HISTORICAL}),
    TYPE_PARTS: frozenset({PARTS}),
    TYPE_MOTORCYCLES: frozenset({MOTO_NEW, MOTO_HISTORICAL}),
}


@dataclass(frozen=True)
class SaleEvent:
    """One atomic sale contribution on a given day. ``units`` is quantity for parts
    and 1 per unit for motorcycles; ``revenue`` is the line total / price charged."""
    day: dt.date
    kind: str
    units: Decimal
    revenue: Decimal


@dataclass
class _Bucket:
    start: dt.date
    end: dt.date
    label: str
    units: dict[str, Decimal] = field(default_factory=dict)
    revenue: dict[str, Decimal] = field(default_factory=dict)


def _period_bounds(day: dt.date, granularity: str) -> tuple[dt.date, dt.date, str]:
    if granularity == DAILY:
        return day, day, day.isoformat()
    if granularity == WEEKLY:
        start = day - dt.timedelta(days=day.weekday())  # Monday
        end = start + dt.timedelta(days=6)
        iso = day.isocalendar()
        return start, end, f"{iso.year}-W{iso.week:02d}"
    if granularity == MONTHLY:
        start = day.replace(day=1)
        end = _month_end(day)
        return start, end, f"{day.year}-{day.month:02d}"
    raise ValueError(f"Unknown granularity {granularity!r}")


def _month_end(day: dt.date) -> dt.date:
    if day.month == 12:
        return day.replace(day=31)
    return day.replace(month=day.month + 1, day=1) - dt.timedelta(days=1)


def build_sales_log(
    events: list[SaleEvent], *, granularity: str, type_filter: str = TYPE_ALL
) -> tuple[list[dict], dict]:
    """Bucket ``events`` into periods (newest first) filtered to ``type_filter``.

    Returns ``(rows, totals)`` as plain dicts (the service wraps them into schemas):
      row   = {period_start, period_end, label, units, revenue, components:[{type,label,units,revenue}]}
      total = {units, revenue, by_kind:{kind:{units,revenue}}}
    """
    if granularity not in GRANULARITIES:
        raise ValueError(f"Unknown granularity {granularity!r}")
    if type_filter not in TYPE_FILTERS:
        raise ValueError(f"Unknown type filter {type_filter!r}")
    kinds = _KINDS_BY_TYPE[type_filter]

    buckets: dict[dt.date, _Bucket] = {}
    for e in events:
        if e.kind not in kinds:
            continue
        start, end, label = _period_bounds(e.day, granularity)
        b = buckets.get(start)
        if b is None:
            b = buckets[start] = _Bucket(start=start, end=end, label=label)
        b.units[e.kind] = b.units.get(e.kind, Decimal("0")) + e.units
        b.revenue[e.kind] = b.revenue.get(e.kind, Decimal("0")) + e.revenue

    rows: list[dict] = []
    grand_units = Decimal("0")
    grand_rev = Decimal("0")
    by_kind: dict[str, dict[str, Decimal]] = {}
    for start in sorted(buckets, reverse=True):
        b = buckets[start]
        components = []
        row_units = Decimal("0")
        row_rev = Decimal("0")
        for kind in (PARTS, MOTO_NEW, MOTO_HISTORICAL):
            if kind not in kinds or kind not in b.units:
                continue
            u = b.units.get(kind, Decimal("0"))
            r = b.revenue.get(kind, Decimal("0"))
            components.append({"type": kind, "label": KIND_LABELS[kind], "units": u, "revenue": r})
            row_units += u
            row_rev += r
            k = by_kind.setdefault(kind, {"units": Decimal("0"), "revenue": Decimal("0")})
            k["units"] += u
            k["revenue"] += r
        rows.append({
            "period_start": b.start, "period_end": b.end, "label": b.label,
            "units": row_units, "revenue": row_rev, "components": components,
        })
        grand_units += row_units
        grand_rev += row_rev

    totals = {"units": grand_units, "revenue": grand_rev, "by_kind": by_kind}
    return rows, totals
