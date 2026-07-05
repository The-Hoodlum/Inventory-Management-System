"""Unit tests for the stock_replay import target's pure timeline helpers + registration."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.imports.domain.registry import get_importer
from app.imports.targets.stock_replay import (
    KIND_ADJUSTMENT,
    KIND_RECEIPT,
    KIND_RETURN,
    KIND_SALE,
    KIND_TRANSFER,
    first_shortfall,
    normalize_type,
    parse_timestamp,
    sort_key,
)


def _ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s).replace(tzinfo=dt.UTC)


def test_normalize_type_maps_all_the_wordings():
    assert normalize_type("Sale") == KIND_SALE
    assert normalize_type("SOLD") == KIND_SALE
    assert normalize_type("Purchase") == KIND_RECEIPT
    assert normalize_type("GRN") == KIND_RECEIPT
    assert normalize_type("Customer Return") == KIND_RETURN
    assert normalize_type("Adjustment") == KIND_ADJUSTMENT
    assert normalize_type("Transfer") == KIND_TRANSFER
    assert normalize_type("nonsense") is None
    assert normalize_type("") is None


def test_parse_timestamp_accepts_date_and_datetime():
    assert parse_timestamp("2026-02-03") == (_ts("2026-02-03T00:00:00"), True)
    assert parse_timestamp("2026-02-03 14:30") == (_ts("2026-02-03T14:30:00"), True)
    assert parse_timestamp("03/02/2026 14:30") == (_ts("2026-02-03T14:30:00"), True)
    assert parse_timestamp("") == (None, False)
    assert parse_timestamp("not-a-date") == (None, False)


def test_sort_key_is_chronological_then_row_order():
    entries = [
        {"row_number": 5, "ts": _ts("2026-02-02")},
        {"row_number": 2, "ts": _ts("2026-02-01")},
        {"row_number": 9, "ts": _ts("2026-02-02")},  # tie with row 5 -> row order breaks it
    ]
    ordered = sorted(entries, key=sort_key)
    assert [e["row_number"] for e in ordered] == [2, 5, 9]


def test_first_shortfall_none_when_receipts_precede_sales():
    # A(loc) starts empty; receipt 10 then sale 4 then sale 6 -> never negative.
    timeline = [
        {"row_number": 1, "ts": _ts("2026-02-01"), "kind": KIND_RECEIPT, "qty": Decimal(10), "loc": "A", "to_loc": None},
        {"row_number": 2, "ts": _ts("2026-02-02"), "kind": KIND_SALE, "qty": Decimal(4), "loc": "A", "to_loc": None},
        {"row_number": 3, "ts": _ts("2026-02-03"), "kind": KIND_SALE, "qty": Decimal(6), "loc": "A", "to_loc": None},
    ]
    assert first_shortfall(timeline, {}) is None


def test_first_shortfall_catches_a_sale_before_its_receipt():
    # Sale of 6 while only 5 on hand (receipt comes later) -> the sale row is the culprit.
    timeline = [
        {"row_number": 7, "ts": _ts("2026-02-02"), "kind": KIND_SALE, "qty": Decimal(6), "loc": "A", "to_loc": None},
        {"row_number": 8, "ts": _ts("2026-02-03"), "kind": KIND_RECEIPT, "qty": Decimal(50), "loc": "A", "to_loc": None},
    ]
    hit = first_shortfall(timeline, {"A": Decimal(5)})
    assert hit is not None
    row_number, ts, loc = hit
    assert row_number == 7 and loc == "A" and ts == _ts("2026-02-02")


def test_first_shortfall_handles_transfer_and_signed_adjustment():
    # Transfer 3 from A to B (A has 5) ok; then adjustment -4 on A (1 left) -> negative.
    timeline = [
        {"row_number": 1, "ts": _ts("2026-02-01"), "kind": KIND_TRANSFER, "qty": Decimal(3), "loc": "A", "to_loc": "B"},
        {"row_number": 2, "ts": _ts("2026-02-02"), "kind": KIND_ADJUSTMENT, "qty": Decimal(-4), "loc": "A", "to_loc": None},
    ]
    hit = first_shortfall(timeline, {"A": Decimal(5)})
    assert hit is not None and hit[0] == 2


def test_importer_is_registered_and_atomic():
    imp = get_importer("stock_replay")
    assert getattr(imp, "atomic", False) is True
    required = {f.name for f in imp.fields if f.required}
    assert required == {"row_type", "timestamp", "product", "warehouse", "quantity"}
    qty = next(f for f in imp.fields if f.name == "quantity")
    assert qty.signed is True  # adjustments may be negative
