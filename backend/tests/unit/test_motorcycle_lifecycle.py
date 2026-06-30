"""Unit tests for the motorcycle serialized-unit lifecycle state machine (pure)."""
from __future__ import annotations

from app.motorcycles.domain import lifecycle as L


def test_happy_path_transitions_are_legal():
    # received -> (skip assembly) -> inspected -> reserved -> sold -> delivered -> registered -> warranty
    assert L.can_transition(L.RECEIVED, L.INSPECTED)
    assert L.can_transition(L.INSPECTED, L.RESERVED)
    assert L.can_transition(L.RESERVED, L.SOLD)
    assert L.can_transition(L.SOLD, L.DELIVERED)
    assert L.can_transition(L.DELIVERED, L.REGISTERED)
    assert L.can_transition(L.REGISTERED, L.WARRANTY_ACTIVE)


def test_full_assembly_chain_is_legal():
    assert L.can_transition(L.RECEIVED, L.ASSEMBLY_REQUIRED)
    assert L.can_transition(L.ASSEMBLY_REQUIRED, L.IN_ASSEMBLY)
    assert L.can_transition(L.IN_ASSEMBLY, L.ASSEMBLED)
    assert L.can_transition(L.ASSEMBLED, L.INSPECTED)


def test_inspected_can_sell_directly_skipping_reserve():
    assert L.can_transition(L.INSPECTED, L.SOLD)


def test_reserved_can_be_released_back_to_inspected():
    assert L.can_transition(L.RESERVED, L.INSPECTED)


def test_illegal_transitions_are_rejected():
    assert not L.can_transition(L.RECEIVED, L.SOLD)         # must be inspected first
    assert not L.can_transition(L.RECEIVED, L.RESERVED)     # must be inspected first
    assert not L.can_transition(L.SOLD, L.RESERVED)         # cannot un-sell
    assert not L.can_transition(L.DELIVERED, L.SOLD)        # no going back
    assert not L.can_transition(L.SOLD, L.CANCELLED)        # cannot cancel a sold unit


def test_terminal_states_have_no_successors():
    assert L.allowed_next(L.WARRANTY_ACTIVE) == []
    assert L.allowed_next(L.CANCELLED) == []
    for s in (L.WARRANTY_ACTIVE, L.CANCELLED):
        assert s in L.TERMINAL


def test_cancel_allowed_only_before_sold():
    for s in (L.RECEIVED, L.ASSEMBLY_REQUIRED, L.IN_ASSEMBLY, L.ASSEMBLED, L.INSPECTED, L.RESERVED):
        assert L.can_transition(s, L.CANCELLED), s
    for s in (L.SOLD, L.DELIVERED, L.REGISTERED, L.WARRANTY_ACTIVE):
        assert not L.can_transition(s, L.CANCELLED), s


def test_allowed_next_is_ordered_and_consistent():
    nxt = L.allowed_next(L.INSPECTED)
    assert set(nxt) == {L.RESERVED, L.SOLD, L.CANCELLED}
    # reserve/sell convenience sets line up with the graph
    assert L.INSPECTED in L.RESERVABLE_FROM and L.RESERVED in L.RESERVABLE_FROM
    assert L.INSPECTED in L.SELLABLE_FROM
