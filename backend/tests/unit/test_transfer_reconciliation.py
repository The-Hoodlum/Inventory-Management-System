"""Transfer reconciliation + lifecycle domain logic (pure, no DB).

Covers the spec's data-integrity rule:  received + missing + damaged = issued + extra
and the new transfer statuses / issue+receive outcomes.
"""
from __future__ import annotations

from app.order_requests.domain import status as S


# --------------------------- reconciliation invariant ---------------------- #
def test_spec_examples_balanced():
    # Issued 10, Received 10 -> VALID
    assert S.is_balanced(10, 0, 10, 0, 0)
    assert S.reconcile_variance(10, 0, 10, 0, 0) == 0
    # Issued 10, Received 8, Missing 1, Damaged 1 -> VALID
    assert S.is_balanced(10, 0, 8, 1, 1)
    # Issued 10, Received 12, Extra 2 -> VALID
    assert S.is_balanced(10, 2, 12, 0, 0)


def test_spec_example_invalid():
    # Issued 5, Received 5, Missing 7 -> INVALID (5 != 12)
    assert not S.is_balanced(5, 0, 5, 7, 0)
    assert S.reconcile_variance(5, 0, 5, 7, 0) == -7


def test_variance_sign():
    # Over-accounted (received+missing+damaged exceeds issued+extra) -> negative variance.
    assert S.reconcile_variance(10, 0, 9, 0, 0) == 1   # under-accounted by 1
    assert S.reconcile_variance(10, 0, 11, 0, 0) == -1  # over-accounted by 1
    assert S.is_balanced(0, 0, 0, 0, 0)


# ------------------------------- transitions ------------------------------- #
def test_draft_and_submit():
    assert S.can_transition(S.DRAFT, S.PENDING)
    assert S.can_transition(S.DRAFT, S.CANCELLED)
    assert not S.can_transition(S.DRAFT, S.APPROVED)


def test_partial_issue_and_in_transit():
    assert S.can_transition(S.APPROVED, S.PARTIALLY_ISSUED)
    assert S.can_transition(S.APPROVED, S.IN_TRANSIT)
    assert S.can_transition(S.PARTIALLY_ISSUED, S.ISSUED)
    assert S.can_transition(S.PARTIALLY_ISSUED, S.IN_TRANSIT)
    # Once any stock has been issued the request can no longer be cancelled.
    assert not S.can_transition(S.PARTIALLY_ISSUED, S.CANCELLED)
    assert not S.can_transition(S.IN_TRANSIT, S.CANCELLED)


def test_receive_then_complete():
    assert S.can_transition(S.ISSUED, S.RECEIVED)
    assert S.can_transition(S.IN_TRANSIT, S.RECEIVED)
    assert S.can_transition(S.IN_TRANSIT, S.PARTIALLY_RECEIVED)
    assert S.can_transition(S.PARTIALLY_RECEIVED, S.RECEIVED)
    assert S.can_transition(S.RECEIVED, S.COMPLETED)
    # legacy one-shot issued -> completed is still allowed
    assert S.can_transition(S.ISSUED, S.COMPLETED)
    assert not S.can_transition(S.RECEIVED, S.ISSUED)  # received is past issuing


# ----------------------------- outcome helpers ----------------------------- #
def test_issue_outcome():
    # Fully issued transfer -> in_transit; consumption -> issued; partial -> partially_issued.
    assert S.issue_outcome([(10, 10)], is_transfer=True) == S.IN_TRANSIT
    assert S.issue_outcome([(10, 10)], is_transfer=False) == S.ISSUED
    assert S.issue_outcome([(6, 10)], is_transfer=True) == S.PARTIALLY_ISSUED
    assert S.issue_outcome([(10, 10), (4, 10)], is_transfer=False) == S.PARTIALLY_ISSUED


def test_receive_outcome():
    # (accounted, issued+extra) pairs. All accounted -> received; some short -> partial.
    assert S.receive_outcome([(10, 10)]) == S.RECEIVED
    assert S.receive_outcome([(10, 10), (0, 5)]) == S.PARTIALLY_RECEIVED


def test_transfer_types_present():
    assert "internal_transfer" in S.PURPOSES
    assert "damaged_replacement" in S.PURPOSES
    assert "branch_transfer" in S.PURPOSES
    assert len(S.PURPOSES) >= 8
