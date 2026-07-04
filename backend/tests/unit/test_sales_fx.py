"""Unit tests for the USD->ZMW freeze math (pure; no DB).

Covers: 2-dp ROUND_HALF_UP conversion; per-line ZMW summing exactly to the document
ZMW total (so lines == total); and the invoice ZMW balance helper (payable minus ZMW
payments minus rate-converted credit)."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.sales.domain import pricing
from app.sales.service import SalesService


def test_to_zmw_rounds_half_up_2dp():
    assert pricing.to_zmw(Decimal("100"), Decimal("20")) == Decimal("2000.00")
    assert pricing.to_zmw(Decimal("10.005"), Decimal("1")) == Decimal("10.01")   # half up
    assert pricing.to_zmw(Decimal("1.234"), Decimal("20")) == Decimal("24.68")    # 24.680 -> 24.68
    assert pricing.to_zmw(Decimal("0"), Decimal("20")) == Decimal("0.00")


def test_freeze_line_zmw_sets_lines_and_sums_to_total():
    rate = Decimal("20.5")
    lines = [SimpleNamespace(line_total=Decimal(v)) for v in ("100.00", "33.33", "0.01", "1250.75")]
    total = SalesService._freeze_line_zmw(rate, lines)
    # Each line stamped with its own rounded ZMW.
    for ln in lines:
        assert ln.line_total_zmw == pricing.to_zmw(ln.line_total, rate)
    # Document total is exactly the sum of the rounded line ZMW — lines == total.
    assert total == sum(ln.line_total_zmw for ln in lines)


def test_invoice_balance_zmw():
    inv = SimpleNamespace(
        grand_total_zmw=Decimal("2000.00"), amount_paid=Decimal("500.00"),
        credit_total=Decimal("10.00"), fx_rate=Decimal("20"),  # credit 10 USD -> 200 ZMW
    )
    assert SalesService._credit_zmw(inv) == Decimal("200.00")
    assert SalesService._invoice_balance_zmw(inv) == Decimal("1300.00")  # 2000 - 500 - 200
