"""Unit tests for the purchase-order state machine (pure domain, no DB)."""
from __future__ import annotations

import pytest

from app.procurement.domain.exceptions import InvalidTransitionError
from app.procurement.domain.states import (
    POAction,
    POStatus,
    assert_transition,
    can_edit,
    can_transition,
    is_terminal,
    target_status,
)

VALID = [
    (POStatus.DRAFT, POAction.SUBMIT, POStatus.PENDING_APPROVAL),
    (POStatus.DRAFT, POAction.CANCEL, POStatus.CANCELLED),
    (POStatus.PENDING_APPROVAL, POAction.APPROVE, POStatus.APPROVED),
    (POStatus.PENDING_APPROVAL, POAction.REJECT, POStatus.REJECTED),
    (POStatus.PENDING_APPROVAL, POAction.CANCEL, POStatus.CANCELLED),
    (POStatus.APPROVED, POAction.SEND, POStatus.SENT),
    (POStatus.APPROVED, POAction.CANCEL, POStatus.CANCELLED),
]

# (status, action) pairs that must be rejected.
INVALID = [
    (POStatus.DRAFT, POAction.APPROVE),
    (POStatus.DRAFT, POAction.REJECT),
    (POStatus.DRAFT, POAction.SEND),
    (POStatus.DRAFT, POAction.RECEIVE),
    (POStatus.PENDING_APPROVAL, POAction.SUBMIT),
    (POStatus.PENDING_APPROVAL, POAction.SEND),
    (POStatus.PENDING_APPROVAL, POAction.RECEIVE),
    (POStatus.APPROVED, POAction.APPROVE),
    (POStatus.APPROVED, POAction.SUBMIT),
    (POStatus.APPROVED, POAction.RECEIVE),
    (POStatus.SENT, POAction.CANCEL),
    (POStatus.SENT, POAction.APPROVE),
    (POStatus.SENT, POAction.SUBMIT),
    (POStatus.PARTIALLY_RECEIVED, POAction.CANCEL),
    (POStatus.PARTIALLY_RECEIVED, POAction.APPROVE),
    (POStatus.RECEIVED, POAction.CANCEL),
    (POStatus.RECEIVED, POAction.RECEIVE),
    (POStatus.RECEIVED, POAction.SEND),
    (POStatus.CANCELLED, POAction.SUBMIT),
    (POStatus.CANCELLED, POAction.APPROVE),
    (POStatus.REJECTED, POAction.SEND),
    (POStatus.REJECTED, POAction.SUBMIT),
]


@pytest.mark.parametrize("current,action,expected", VALID)
def test_valid_transitions_allowed(current, action, expected):
    assert can_transition(current, action) is True
    assert_transition(current, action)  # must not raise
    assert target_status(current, action) is expected


@pytest.mark.parametrize("current,action", INVALID)
def test_invalid_transitions_blocked(current, action):
    assert can_transition(current, action) is False
    with pytest.raises(InvalidTransitionError):
        assert_transition(current, action)


def test_receive_allowed_only_from_receivable_states():
    assert can_transition(POStatus.SENT, POAction.RECEIVE) is True
    assert can_transition(POStatus.PARTIALLY_RECEIVED, POAction.RECEIVE) is True
    # RECEIVE has no fixed target (it is quantity-driven).
    assert target_status(POStatus.SENT, POAction.RECEIVE) is None


def test_can_edit_only_in_draft():
    assert can_edit(POStatus.DRAFT) is True
    for status in (
        POStatus.PENDING_APPROVAL,
        POStatus.APPROVED,
        POStatus.SENT,
        POStatus.PARTIALLY_RECEIVED,
        POStatus.RECEIVED,
        POStatus.CANCELLED,
        POStatus.REJECTED,
    ):
        assert can_edit(status) is False


def test_terminal_states():
    for status in (POStatus.RECEIVED, POStatus.CANCELLED, POStatus.REJECTED):
        assert is_terminal(status) is True
    for status in (
        POStatus.DRAFT,
        POStatus.PENDING_APPROVAL,
        POStatus.APPROVED,
        POStatus.SENT,
        POStatus.PARTIALLY_RECEIVED,
    ):
        assert is_terminal(status) is False


def test_accepts_raw_string_status():
    # Service stores status as a string; helpers must coerce.
    assert can_transition("draft", POAction.SUBMIT) is True
    assert target_status("approved", POAction.SEND) is POStatus.SENT
