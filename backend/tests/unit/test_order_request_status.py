"""Order-request status workflow + line math (pure)."""
from __future__ import annotations

from app.order_requests.domain import status as S


def test_allowed_transitions():
    assert S.can_transition(S.PENDING, S.APPROVED)
    assert S.can_transition(S.PENDING, S.PARTIALLY_APPROVED)
    assert S.can_transition(S.PENDING, S.REJECTED)
    assert S.can_transition(S.APPROVED, S.ISSUED)
    assert S.can_transition(S.PARTIALLY_APPROVED, S.ISSUED)


def test_disallowed_transitions():
    assert not S.can_transition(S.PENDING, S.ISSUED)        # must approve first
    assert not S.can_transition(S.ISSUED, S.APPROVED)       # terminal
    assert not S.can_transition(S.REJECTED, S.APPROVED)     # terminal
    assert not S.can_transition(S.APPROVED, S.REJECTED)     # already approved


def test_clamp_approved_bounds():
    assert S.clamp_approved(8, 5) == 5      # cannot approve more than requested
    assert S.clamp_approved(-3, 5) == 0     # not negative
    assert S.clamp_approved(4, 5) == 4


def test_approval_outcome():
    assert S.approval_outcome([(5, 5), (10, 10)]) == S.APPROVED          # all full
    assert S.approval_outcome([(6, 10), (5, 5)]) == S.PARTIALLY_APPROVED  # one short
    assert S.approval_outcome([(0, 10), (0, 5)]) == S.REJECTED            # nothing


def test_outstanding():
    assert S.outstanding(10, 6) == 4
    assert S.outstanding(5, 5) == 0
    assert S.outstanding(5, 7) == 0  # never negative


def test_issued_completes_only_via_explicit_step():
    assert S.can_transition(S.ISSUED, S.COMPLETED)      # issued -> completed
    assert not S.can_transition(S.COMPLETED, S.ISSUED)  # completed is terminal
    assert not S.can_transition(S.COMPLETED, S.CANCELLED)
    assert S.COMPLETED in S.STATUSES


def test_cancel_allowed_before_issue_only():
    assert S.can_transition(S.PENDING, S.CANCELLED)
    assert S.can_transition(S.APPROVED, S.CANCELLED)
    assert S.can_transition(S.PARTIALLY_APPROVED, S.CANCELLED)
    assert not S.can_transition(S.ISSUED, S.CANCELLED)     # too late once issued
    assert not S.can_transition(S.REJECTED, S.CANCELLED)
