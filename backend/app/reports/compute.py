"""Pure report computations — standard library only (no pydantic / SQLAlchemy).

Isolating the math here keeps it unit-testable without a database or web stack:
the service layer fetches rows, calls these functions, and wraps the plain
results into API schemas.

Inventory aging reconstructs remaining stock layers from the signed movement
ledger (FIFO: oldest inbound units are consumed first) and buckets the units
still on hand by age. Supplier performance derives on-time delivery, lead time
and fill rate from purchase orders, their lifecycle timestamps, and receipts.
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby

# (label, min_days, max_days|None) — the 90+ band is open-ended.
BUCKETS: list[tuple[str, int, int | None]] = [
    ("0-30", 0, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("90+", 91, None),
]

NON_FILL_STATUSES = ("draft", "cancelled", "rejected")


def bucket_label(age_days: int) -> str:
    if age_days <= 30:
        return "0-30"
    if age_days <= 60:
        return "31-60"
    if age_days <= 90:
        return "61-90"
    return "90+"


# ------------------------------ inventory aging ----------------------------- #
@dataclass
class AgingBucketCalc:
    label: str
    min_days: int
    max_days: int | None
    qty: Decimal
    cost_value: Decimal


@dataclass
class AgingItemCalc:
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    on_hand: Decimal
    cost_value: Decimal
    oldest_received_at: dt.datetime | None
    bucket_qty: dict[str, Decimal]


@dataclass
class AgingResult:
    buckets: list[AgingBucketCalc]
    items: list[AgingItemCalc]


def aging_from_movements(
    movements: Iterable[tuple[uuid.UUID, uuid.UUID, Decimal, dt.datetime]],
    costs: dict[uuid.UUID, Decimal],
    as_of: dt.datetime,
) -> AgingResult:
    """Replay signed movements per (product, warehouse) and age the remaining
    on-hand units. ``movements`` MUST already be ordered by
    (product_id, warehouse_id, created_at)."""
    items: list[AgingItemCalc] = []
    totals: dict[str, dict[str, Decimal]] = {
        label: {"qty": Decimal("0"), "value": Decimal("0")} for label, _, _ in BUCKETS
    }

    for (product_id, wh_id), group in groupby(movements, key=lambda m: (m[0], m[1])):
        layers: deque[list] = deque()  # each entry: [remaining_qty, received_at]
        for _pid, _wid, qty, created_at in group:
            if qty > 0:
                layers.append([qty, created_at])
            elif qty < 0:
                need = -qty
                while need > 0 and layers:
                    head = layers[0]
                    take = head[0] if head[0] <= need else need
                    head[0] -= take
                    need -= take
                    if head[0] <= 0:
                        layers.popleft()

        if not layers:
            continue

        cost = costs.get(product_id, Decimal("0"))
        per_bucket: dict[str, Decimal] = {label: Decimal("0") for label, _, _ in BUCKETS}
        on_hand = Decimal("0")
        cost_value = Decimal("0")
        oldest: dt.datetime | None = None

        for qty, date in layers:
            if qty <= 0:
                continue
            age = (as_of - date).days
            label = bucket_label(age if age >= 0 else 0)
            per_bucket[label] += qty
            on_hand += qty
            cost_value += qty * cost
            totals[label]["qty"] += qty
            totals[label]["value"] += qty * cost
            if oldest is None or date < oldest:
                oldest = date

        items.append(
            AgingItemCalc(
                product_id=product_id,
                warehouse_id=wh_id,
                on_hand=on_hand,
                cost_value=cost_value,
                oldest_received_at=oldest,
                bucket_qty=per_bucket,
            )
        )

    items.sort(key=lambda it: it.cost_value, reverse=True)
    buckets = [
        AgingBucketCalc(
            label=label,
            min_days=min_days,
            max_days=max_days,
            qty=totals[label]["qty"],
            cost_value=totals[label]["value"],
        )
        for label, min_days, max_days in BUCKETS
    ]
    return AgingResult(buckets=buckets, items=items)


# --------------------------- supplier performance --------------------------- #
@dataclass
class SupplierPerfCalc:
    supplier_id: uuid.UUID
    po_count: int
    received_po_count: int
    on_time_po_count: int
    on_time_rate: float | None
    avg_lead_time_days: float | None
    fill_rate: float | None
    last_order_at: dt.datetime | None


def supplier_performance(
    supplier_ids: list[uuid.UUID],
    pos: Iterable[tuple[uuid.UUID, uuid.UUID, str, dt.date | None, dt.datetime]],
    line_totals: dict[uuid.UUID, tuple[Decimal, Decimal]],
    timestamps: dict[uuid.UUID, dict[str, dt.datetime]],
) -> dict[uuid.UUID, SupplierPerfCalc]:
    """Aggregate per-supplier delivery metrics. ``pos`` rows are
    (po_id, supplier_id, status, expected_date, created_at); ``line_totals`` maps
    po_id -> (ordered_qty, received_qty); ``timestamps`` maps po_id -> {sent, received}."""
    agg: dict[uuid.UUID, dict] = {
        sid: {
            "po_count": 0,
            "received": 0,
            "on_time": 0,
            "expected_received": 0,
            "lead": [],
            "ordered": Decimal("0"),
            "filled": Decimal("0"),
            "last_order": None,
        }
        for sid in supplier_ids
    }

    for po_id, supplier_id, status, expected_date, created_at in pos:
        a = agg.get(supplier_id)
        if a is None:  # PO references a supplier not in the set (e.g. removed)
            continue
        a["po_count"] += 1
        if a["last_order"] is None or created_at > a["last_order"]:
            a["last_order"] = created_at

        if status not in NON_FILL_STATUSES:
            ordered, filled = line_totals.get(po_id, (Decimal("0"), Decimal("0")))
            a["ordered"] += ordered
            a["filled"] += filled

        if status == "received":
            a["received"] += 1
            received_at = timestamps.get(po_id, {}).get("received")
            if received_at is not None:
                sent_at = timestamps.get(po_id, {}).get("sent")
                base = sent_at or created_at
                lead = (received_at - base).days
                if lead >= 0:
                    a["lead"].append(lead)
                if expected_date is not None:
                    a["expected_received"] += 1
                    if received_at.date() <= expected_date:
                        a["on_time"] += 1

    out: dict[uuid.UUID, SupplierPerfCalc] = {}
    for sid in supplier_ids:
        a = agg[sid]
        on_time_rate = a["on_time"] / a["expected_received"] if a["expected_received"] else None
        avg_lead = sum(a["lead"]) / len(a["lead"]) if a["lead"] else None
        fill_rate = float(a["filled"] / a["ordered"]) if a["ordered"] > 0 else None
        out[sid] = SupplierPerfCalc(
            supplier_id=sid,
            po_count=a["po_count"],
            received_po_count=a["received"],
            on_time_po_count=a["on_time"],
            on_time_rate=on_time_rate,
            avg_lead_time_days=avg_lead,
            fill_rate=fill_rate,
            last_order_at=a["last_order"],
        )
    return out
