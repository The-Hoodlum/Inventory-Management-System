"""Unit tests for the serialized-unit lifecycle state machine (pure, no DB)."""
from __future__ import annotations

from app.motorcycles.domain import lifecycle as L


def test_happy_path_with_assembly_is_legal():
    chain = [
        L.RECEIVED, L.ASSEMBLY_REQUIRED, L.IN_ASSEMBLY, L.ASSEMBLED, L.INSPECTED,
        L.RESERVED, L.SOLD, L.DELIVERED, L.REGISTERED, L.WARRANTY_ACTIVE,
    ]
    for old, new in zip(chain, chain[1:], strict=False):
        assert L.can_transition(old, new), f"{old} -> {new} should be legal"


def test_defined_skips_are_legal():
    # A unit needing no assembly goes straight received -> inspected.
    assert L.can_transition(L.RECEIVED, L.INSPECTED)
    # Inspected can sell directly, skipping the reservation.
    assert L.can_transition(L.INSPECTED, L.SOLD)


def test_reserved_can_be_released_back_to_inspected():
    assert L.can_transition(L.RESERVED, L.INSPECTED)


def test_illegal_transitions_are_rejected():
    assert not L.can_transition(L.RECEIVED, L.SOLD)          # cannot sell an un-inspected unit
    assert not L.can_transition(L.RECEIVED, L.DELIVERED)     # cannot skip the whole middle
    assert not L.can_transition(L.SOLD, L.INSPECTED)         # cannot un-sell
    assert not L.can_transition(L.DELIVERED, L.RESERVED)     # no going back after delivery
    assert not L.can_transition(L.INSPECTED, L.IN_ASSEMBLY)  # cannot re-enter assembly


def test_cancel_allowed_only_before_sold():
    for s in (L.RECEIVED, L.ASSEMBLY_REQUIRED, L.IN_ASSEMBLY, L.ASSEMBLED, L.INSPECTED, L.RESERVED):
        assert L.can_transition(s, L.CANCELLED), f"{s} should be cancellable"
    for s in (L.SOLD, L.DELIVERED, L.REGISTERED, L.WARRANTY_ACTIVE):
        assert not L.can_transition(s, L.CANCELLED), f"{s} must not be cancellable"


def test_terminal_states_have_no_successors():
    assert L.allowed_next(L.WARRANTY_ACTIVE) == []
    assert L.allowed_next(L.CANCELLED) == []
    assert L.WARRANTY_ACTIVE in L.TERMINAL and L.CANCELLED in L.TERMINAL


def test_allowed_next_is_ordered_and_consistent():
    nxt = L.allowed_next(L.RECEIVED)
    assert nxt == [L.ASSEMBLY_REQUIRED, L.INSPECTED, L.CANCELLED]  # stable order
    # allowed_next agrees with can_transition for every status.
    for status in L.STATUSES:
        for candidate in L.allowed_next(status):
            assert L.can_transition(status, candidate)


def test_unknown_status_has_no_transitions():
    assert not L.can_transition("bogus", L.INSPECTED)
    assert L.allowed_next("bogus") == []
