"""Unit tests for the full-carton and MOQ rules (pure domain, no DB/async)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.reorder.domain.exceptions import InvalidPolicyError
from app.reorder.domain.rounding import enforce_order_quantity, round_up_to_carton


# ----------------------- the two documented business rules ----------------------- #
def test_full_carton_rule_example():
    # units_per_carton=10, calculated=67 -> 70 (never partial cartons)
    oq = enforce_order_quantity(Decimal("67"), units_per_carton=10, moq=0)
    assert oq.recommended_units == 70
    assert oq.cartons == 7
    assert oq.applied_moq is False


def test_moq_rule_example():
    # moq=500, calculated=320 -> 500 (always respect MOQ)
    oq = enforce_order_quantity(Decimal("320"), units_per_carton=1, moq=500)
    assert oq.recommended_units == 500
    assert oq.applied_moq is True


# ------------------------------- round_up_to_carton ------------------------------- #
@pytest.mark.parametrize(
    "qty,upc,expected",
    [
        (67, 10, 70),
        (70, 10, 70),   # exact multiple unchanged
        (71, 10, 80),
        (60, 12, 60),
        (1, 12, 12),
        (5, 1, 5),
        (0, 10, 0),     # nothing rounds to nothing
    ],
)
def test_round_up_to_carton(qty, upc, expected):
    assert round_up_to_carton(Decimal(qty), upc) == expected


# ------------------------------- enforce_order_quantity --------------------------- #
def test_carton_rounding_with_decimal_raw():
    oq = enforce_order_quantity(Decimal("36.1"), units_per_carton=24, moq=0)
    assert oq.recommended_units == 48
    assert oq.cartons == 2
    assert oq.cartoned_units == 48


def test_moq_above_cartoned_is_applied_and_kept_whole_cartons():
    # raw rounds to 12, but MOQ 500 (not a multiple of 12) -> next carton multiple 504
    oq = enforce_order_quantity(Decimal("10"), units_per_carton=12, moq=500)
    assert oq.recommended_units == 504
    assert oq.cartons == 42
    assert oq.applied_moq is True


def test_moq_not_binding_when_cartoned_already_exceeds_it():
    # raw 505 -> cartoned 510 (>= MOQ 500): MOQ does not raise it further
    oq = enforce_order_quantity(Decimal("505"), units_per_carton=10, moq=500)
    assert oq.recommended_units == 510
    assert oq.cartons == 51
    assert oq.applied_moq is False


@pytest.mark.parametrize("raw", [Decimal("0"), Decimal("-5")])
def test_non_positive_raw_never_orders_even_with_moq(raw):
    oq = enforce_order_quantity(raw, units_per_carton=10, moq=500)
    assert oq.recommended_units == 0
    assert oq.cartons == 0
    assert oq.applied_moq is False


def test_invalid_units_per_carton_raises():
    with pytest.raises(InvalidPolicyError):
        enforce_order_quantity(Decimal("10"), units_per_carton=0, moq=0)
    with pytest.raises(InvalidPolicyError):
        round_up_to_carton(Decimal("10"), 0)


def test_negative_moq_raises():
    with pytest.raises(InvalidPolicyError):
        enforce_order_quantity(Decimal("10"), units_per_carton=10, moq=-1)
