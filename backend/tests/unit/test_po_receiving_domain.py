"""Unit tests for goods-receipt computation (pure domain, no DB)."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.procurement.domain.exceptions import ReceiptError
from app.procurement.domain.receiving import LineState, apply_receipt
from app.procurement.domain.states import POStatus


def _line(ordered, received=0):
    return LineState(
        line_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        ordered_qty=Decimal(str(ordered)),
        already_received=Decimal(str(received)),
    )


def test_full_receipt_marks_received():
    line = _line(1000)
    out = apply_receipt([line], {line.line_id: Decimal(1000)})
    assert out.fully_received is True
    assert out.resulting_status is POStatus.RECEIVED
    assert out.total_received_now == Decimal(1000)
    assert out.lines[0].new_received_total == Decimal(1000)
    assert out.lines[0].fully_received is True


def test_partial_receipt_marks_partially_received():
    line = _line(1000)
    out = apply_receipt([line], {line.line_id: Decimal(600)})
    assert out.fully_received is False
    assert out.resulting_status is POStatus.PARTIALLY_RECEIVED
    assert out.lines[0].new_received_total == Decimal(600)
    assert line.remaining == Decimal(1000)  # state object itself is unchanged


def test_second_receipt_completes_the_line():
    line = _line(1000, received=600)
    assert line.remaining == Decimal(400)
    out = apply_receipt([line], {line.line_id: Decimal(400)})
    assert out.fully_received is True
    assert out.resulting_status is POStatus.RECEIVED
    assert out.lines[0].new_received_total == Decimal(1000)


def test_multi_line_one_complete_one_partial_is_partial():
    a = _line(100)
    b = _line(50)
    out = apply_receipt([a, b], {a.line_id: Decimal(100), b.line_id: Decimal(20)})
    assert out.fully_received is False
    assert out.resulting_status is POStatus.PARTIALLY_RECEIVED
    assert out.total_received_now == Decimal(120)


def test_multi_line_all_complete_is_received():
    a = _line(100)
    b = _line(50, received=50)  # already complete
    out = apply_receipt([a, b], {a.line_id: Decimal(100)})
    assert out.fully_received is True
    assert out.resulting_status is POStatus.RECEIVED


def test_over_receipt_raises():
    line = _line(1000, received=600)
    with pytest.raises(ReceiptError):
        apply_receipt([line], {line.line_id: Decimal(500)})  # only 400 remaining


def test_unknown_line_raises():
    line = _line(10)
    with pytest.raises(ReceiptError):
        apply_receipt([line], {uuid.uuid4(): Decimal(1)})


def test_zero_quantity_raises():
    line = _line(10)
    with pytest.raises(ReceiptError):
        apply_receipt([line], {line.line_id: Decimal(0)})


def test_negative_quantity_raises():
    line = _line(10)
    with pytest.raises(ReceiptError):
        apply_receipt([line], {line.line_id: Decimal(-5)})


def test_empty_receipt_raises():
    line = _line(10)
    with pytest.raises(ReceiptError):
        apply_receipt([line], {})
