"""Sales pricing/total math + document status machines (pure, no DB)."""
from __future__ import annotations

from decimal import Decimal

from app.sales.domain import pricing
from app.sales.domain import status as S


# ------------------------------- pricing ----------------------------------- #
def test_line_amounts_discount_and_tax():
    a = pricing.line_amounts(2, 100, discount_pct=10, tax_pct=16)
    # gross 200, discount 20, net 180, tax 28.8, total 208.8
    assert a["gross"] == Decimal("200.0000")
    assert a["discount"] == Decimal("20.0000")
    assert a["net"] == Decimal("180.0000")
    assert a["tax"] == Decimal("28.8000")
    assert a["line_total"] == Decimal("208.8000")


def test_line_amounts_no_discount_no_tax():
    assert pricing.line_total(3, 50) == Decimal("150.0000")


def test_document_totals_aggregate():
    lines = [
        {"qty": 2, "unit_price": 100, "discount_pct": 10, "tax_pct": 16},  # total 208.8
        {"qty": 1, "unit_price": 50, "discount_pct": 0, "tax_pct": 0},      # total 50
    ]
    t = pricing.document_totals(lines)
    assert t["subtotal"] == Decimal("250.0000")       # 200 + 50
    assert t["discount_total"] == Decimal("20.0000")
    assert t["tax_total"] == Decimal("28.8000")
    assert t["grand_total"] == Decimal("258.8000")    # 208.8 + 50


# ------------------------------- statuses ---------------------------------- #
def test_quote_transitions():
    assert S.quote_can_transition(S.Q_DRAFT, S.Q_SENT)
    assert S.quote_can_transition(S.Q_SENT, S.Q_ACCEPTED)
    assert S.quote_can_transition(S.Q_SENT, S.Q_REJECTED)
    assert not S.quote_can_transition(S.Q_REJECTED, S.Q_ACCEPTED)  # terminal
    assert S.Q_DRAFT in S.QUOTE_CONVERTIBLE and S.Q_ACCEPTED in S.QUOTE_CONVERTIBLE


def test_so_delivery_outcome():
    assert S.so_delivery_outcome([(10, 10), (5, 5)]) == S.SO_DELIVERED
    assert S.so_delivery_outcome([(4, 10), (5, 5)]) == S.SO_PARTIALLY_DELIVERED


def test_so_lifecycle_sets():
    assert S.SO_DRAFT in S.SO_CANCELLABLE
    assert S.SO_CONFIRMED in S.SO_CANCELLABLE and S.SO_CONFIRMED in S.SO_DELIVERABLE
    assert S.SO_DELIVERED not in S.SO_CANCELLABLE  # too late once delivered


def test_invoice_status_after_payment():
    assert S.invoice_status_after_payment(100, 0) == S.INV_SENT
    assert S.invoice_status_after_payment(100, 40) == S.INV_PARTIALLY_PAID
    assert S.invoice_status_after_payment(100, 100) == S.INV_PAID
    assert S.invoice_status_after_payment(100, 100.0001) == S.INV_PAID  # rounding tolerance


def test_credit_note_transitions():
    assert S.cn_can_transition(S.CN_DRAFT, S.CN_APPROVED)
    assert S.cn_can_transition(S.CN_APPROVED, S.CN_APPLIED)
    assert S.cn_can_transition(S.CN_DRAFT, S.CN_CANCELLED)
    assert not S.cn_can_transition(S.CN_DRAFT, S.CN_APPLIED)   # must approve first
    assert not S.cn_can_transition(S.CN_APPLIED, S.CN_CANCELLED)  # terminal
    assert "damaged" in S.RETURN_REASONS and "warranty" in S.RETURN_REASONS
