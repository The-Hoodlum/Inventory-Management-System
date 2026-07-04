"""Unit tests for the five-status serialized-unit sale-status machine (pure, no DB)."""
from __future__ import annotations

from app.motorcycles.domain import lifecycle as L


def test_exactly_five_statuses():
    assert L.STATUSES == {L.UNASSEMBLED, L.ASSEMBLED, L.RESERVED, L.ON_HOLD, L.SOLD}
    assert len(L.STATUSES) == 5


def test_legal_transitions():
    legal = {
        (L.UNASSEMBLED, L.ASSEMBLED), (L.UNASSEMBLED, L.ON_HOLD),
        (L.ASSEMBLED, L.RESERVED), (L.ASSEMBLED, L.SOLD), (L.ASSEMBLED, L.ON_HOLD),
        (L.RESERVED, L.SOLD), (L.RESERVED, L.ASSEMBLED),
        (L.ON_HOLD, L.ASSEMBLED), (L.ON_HOLD, L.UNASSEMBLED),
    }
    for old, new in legal:
        assert L.can_transition(old, new), f"{old} -> {new} should be legal"
    # Everything else is illegal.
    for old in L.STATUSES:
        for new in L.STATUSES:
            if (old, new) not in legal:
                assert not L.can_transition(old, new), f"{old} -> {new} should be illegal"


def test_on_hold_cannot_go_straight_to_sold():
    # A held unit must return to assembled before it can sell.
    assert not L.can_transition(L.ON_HOLD, L.SOLD)
    assert not L.can_transition(L.ON_HOLD, L.RESERVED)
    assert L.can_transition(L.ON_HOLD, L.ASSEMBLED)


def test_reserved_can_fall_through_back_to_assembled():
    assert L.can_transition(L.RESERVED, L.ASSEMBLED)


def test_sold_is_terminal():
    assert L.allowed_next(L.SOLD) == []
    assert L.SOLD in L.TERMINAL


def test_rollups_and_origination_sets():
    # POST_SALE (what the sales log counts as a bike sale) is exactly {sold}.
    assert L.POST_SALE == {L.SOLD}
    # On-hand-not-sold-or-reserved.
    assert L.IN_STOCK == {L.UNASSEMBLED, L.ASSEMBLED, L.ON_HOLD}
    assert L.RESERVABLE_FROM == {L.ASSEMBLED}
    assert L.SELLABLE_FROM == {L.ASSEMBLED, L.RESERVED}
    assert L.CUSTOMER_STATUSES == {L.RESERVED, L.SOLD}


def test_allowed_next_is_ordered_and_consistent():
    assert L.allowed_next(L.ASSEMBLED) == [L.RESERVED, L.ON_HOLD, L.SOLD]  # stable _ORDER
    for status in L.STATUSES:
        for candidate in L.allowed_next(status):
            assert L.can_transition(status, candidate)


def test_unknown_status_has_no_transitions():
    assert not L.can_transition("bogus", L.ASSEMBLED)
    assert L.allowed_next("bogus") == []
