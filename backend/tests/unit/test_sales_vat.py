"""VAT math — exclusive (parts add 16% on top) vs inclusive (bikes extract from gross),
mixed-document consistency, and the freeze guarantee. Pure domain (no DB)."""
from __future__ import annotations

from decimal import Decimal

from app.sales.domain import pricing

_2DP = Decimal("0.01")


def test_exclusive_part_adds_vat_on_top():
    # A K100 part -> net 100, VAT 16, gross 116.
    a = pricing.line_amounts(1, 100, 0, 16, pricing.EXCLUSIVE)
    assert a["net"] == Decimal("100.0000")
    assert a["vat"] == Decimal("16.0000")
    assert a["line_total"] == Decimal("116.0000")   # payable (gross)


def test_exclusive_part_qty_and_discount():
    # 2 x 100 less 10% -> net 180, VAT 28.8, gross 208.8.
    a = pricing.line_amounts(2, 100, 10, 16, pricing.EXCLUSIVE)
    assert a["net"] == Decimal("180.0000")
    assert a["vat"] == Decimal("28.8000")
    assert a["line_total"] == Decimal("208.8000")


def test_inclusive_bike_extracts_vat_customer_pays_gross():
    # A 20,000 (ZMW) bike is VAT-INCLUSIVE: extract, do NOT add. Customer pays 20,000.
    a = pricing.line_amounts(1, 20000, 0, 16, pricing.INCLUSIVE)
    assert a["line_total"] == Decimal("20000.0000")            # pays 20,000, NOT 23,200
    assert a["net"].quantize(_2DP) == Decimal("17241.38")
    assert a["vat"].quantize(_2DP) == Decimal("2758.62")
    # net + vat == gross exactly (no leakage).
    assert a["net"] + a["vat"] == a["line_total"]


def test_mixed_document_lines_sum_to_totals():
    # One part (exclusive) + one bike-style line (inclusive) — each by its own treatment,
    # and the lines sum EXACTLY to the document totals.
    lines = [
        {"qty": 1, "unit_price": 100, "discount_pct": 0, "tax_pct": 16, "treatment": pricing.EXCLUSIVE},
        {"qty": 1, "unit_price": 20000, "discount_pct": 0, "tax_pct": 16, "treatment": pricing.INCLUSIVE},
    ]
    per_line = [pricing.line_amounts(x["qty"], x["unit_price"], 0, 16, x["treatment"]) for x in lines]
    t = pricing.document_totals(lines)
    assert t["net_total"] == sum(a["net"] for a in per_line)
    assert t["tax_total"] == sum(a["vat"] for a in per_line)
    assert t["grand_total"] == sum(a["line_total"] for a in per_line)
    # grand == net + vat (treatment-agnostic invariant).
    assert t["grand_total"] == t["net_total"] + t["tax_total"]


def test_zero_rate_leaves_gross_equal_net():
    a = pricing.line_amounts(1, 100, 0, 0, pricing.EXCLUSIVE)
    assert a["net"] == a["line_total"] == Decimal("100.0000") and a["vat"] == Decimal("0.0000")
    b = pricing.line_amounts(1, 100, 0, 0, pricing.INCLUSIVE)
    assert b["net"] == b["line_total"] == Decimal("100.0000") and b["vat"] == Decimal("0.0000")


def test_frozen_rate_is_what_drives_amounts_not_current_rate():
    # A document stores the RATE it was created with; recomputing from that frozen rate
    # always yields the same amounts, regardless of any later tenant-rate change. (The
    # service persists net/vat + vat_rate on the line; this is the math it freezes.)
    frozen_pct = Decimal("16")
    a = pricing.line_amounts(1, 100, 0, frozen_pct, pricing.EXCLUSIVE)
    # Later the tenant moves to 20% — the OLD doc still recomputes from its frozen 16%.
    assert pricing.line_amounts(1, 100, 0, frozen_pct, pricing.EXCLUSIVE) == a
    assert a["vat"] == Decimal("16.0000")
