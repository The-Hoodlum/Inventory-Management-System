"""Unit tests for inventory-aging FIFO reconstruction (pure domain, no DB).

Deliberately dependency-light (no ``import pytest``) so they run both under the
project's pytest suite and a plain runner. Movements are supplied pre-ordered by
(product, warehouse, created_at), exactly as the repository's query returns them.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.reports.compute import BUCKETS, aging_from_movements, bucket_label

NOW = dt.datetime(2025, 6, 1, 12, 0, tzinfo=dt.timezone.utc)
P = uuid.UUID("11111111-1111-1111-1111-111111111111")
P2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
W1 = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
W2 = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def days_ago(n: int) -> dt.datetime:
    return NOW - dt.timedelta(days=n)


def _buckets(result):
    return {b.label: b for b in result.buckets}


# --------------------------- bucket boundaries --------------------------- #
def test_bucket_label_boundaries():
    assert bucket_label(0) == "0-30"
    assert bucket_label(30) == "0-30"
    assert bucket_label(31) == "31-60"
    assert bucket_label(60) == "31-60"
    assert bucket_label(61) == "61-90"
    assert bucket_label(90) == "61-90"
    assert bucket_label(91) == "90+"
    assert bucket_label(365) == "90+"


def test_buckets_constant_shape():
    labels = [b[0] for b in BUCKETS]
    assert labels == ["0-30", "31-60", "61-90", "90+"]
    assert BUCKETS[-1][2] is None  # 90+ is open-ended


# ------------------------------ empty input ------------------------------ #
def test_empty_movements():
    r = aging_from_movements([], {}, NOW)
    assert r.items == []
    for b in r.buckets:
        assert b.qty == Decimal("0")
        assert b.cost_value == Decimal("0")


# ------------------------------ FIFO basics ------------------------------ #
def test_fifo_consumes_oldest_layer_first():
    movements = [
        (P, W1, Decimal("10"), days_ago(100)),  # old layer
        (P, W1, Decimal("5"), days_ago(10)),    # recent layer
        (P, W1, Decimal("-8"), days_ago(5)),    # issue: eats oldest first
    ]
    r = aging_from_movements(movements, {P: Decimal("3")}, NOW)
    assert len(r.items) == 1
    it = r.items[0]
    assert it.on_hand == Decimal("7")               # 2 old + 5 recent
    assert it.bucket_qty["90+"] == Decimal("2")
    assert it.bucket_qty["0-30"] == Decimal("5")
    assert it.bucket_qty["31-60"] == Decimal("0")
    assert it.cost_value == Decimal("21")           # 7 * 3
    assert it.oldest_received_at == days_ago(100)

    b = _buckets(r)
    assert b["90+"].qty == Decimal("2") and b["90+"].cost_value == Decimal("6")
    assert b["0-30"].qty == Decimal("5") and b["0-30"].cost_value == Decimal("15")


def test_partial_consume_spans_layers():
    movements = [
        (P, W1, Decimal("10"), days_ago(80)),  # 61-90
        (P, W1, Decimal("10"), days_ago(40)),  # 31-60
        (P, W1, Decimal("-15"), days_ago(1)),  # consume 10 + 5
    ]
    r = aging_from_movements(movements, {P: Decimal("2")}, NOW)
    it = r.items[0]
    assert it.on_hand == Decimal("5")
    assert it.bucket_qty["31-60"] == Decimal("5")
    assert it.bucket_qty["61-90"] == Decimal("0")
    assert it.cost_value == Decimal("10")


def test_over_issue_floors_to_zero_and_drops_item():
    movements = [
        (P, W1, Decimal("5"), days_ago(10)),
        (P, W1, Decimal("-9"), days_ago(1)),  # more than on hand
    ]
    r = aging_from_movements(movements, {P: Decimal("4")}, NOW)
    assert r.items == []
    for b in r.buckets:
        assert b.qty == Decimal("0")


def test_positive_adjustment_is_a_fresh_layer():
    # A positive adjustment (e.g. found stock) ages from its own timestamp.
    movements = [(P, W1, Decimal("4"), days_ago(2))]
    r = aging_from_movements(movements, {P: Decimal("2")}, NOW)
    it = r.items[0]
    assert it.on_hand == Decimal("4")
    assert it.bucket_qty["0-30"] == Decimal("4")
    assert it.cost_value == Decimal("8")


# --------------------------- transfer semantics --------------------------- #
def test_transfer_relayers_stock_at_destination_date():
    # Source keeps the old age; transferred units re-age from the transfer date.
    rows = [
        (P, W1, Decimal("10"), days_ago(100)),  # source inbound (old)
        (P, W1, Decimal("-3"), days_ago(2)),    # transfer_out from source
        (P, W2, Decimal("3"), days_ago(2)),     # transfer_in to destination
    ]
    rows.sort(key=lambda m: (str(m[0]), str(m[1]), m[3]))  # mimic repo ordering
    r = aging_from_movements(rows, {P: Decimal("1")}, NOW)
    by_wh = {it.warehouse_id: it for it in r.items}
    assert by_wh[W1].on_hand == Decimal("7")
    assert by_wh[W1].bucket_qty["90+"] == Decimal("7")
    assert by_wh[W2].on_hand == Decimal("3")
    assert by_wh[W2].bucket_qty["0-30"] == Decimal("3")


# ----------------------------- multi product ----------------------------- #
def test_items_sorted_by_cost_value_desc():
    rows = [
        (P, W1, Decimal("1"), days_ago(5)),     # value 1 * 2 = 2
        (P2, W1, Decimal("10"), days_ago(5)),   # value 10 * 5 = 50
    ]
    rows.sort(key=lambda m: (str(m[0]), str(m[1]), m[3]))
    r = aging_from_movements(rows, {P: Decimal("2"), P2: Decimal("5")}, NOW)
    assert [it.product_id for it in r.items] == sorted(
        [P, P2], key=lambda pid: {P: 2, P2: 50}[pid], reverse=True
    )
    assert r.items[0].cost_value == Decimal("50")
