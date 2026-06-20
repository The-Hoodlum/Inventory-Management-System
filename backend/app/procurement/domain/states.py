"""Purchase-order status model and state-transition rules.

Status values match the database CHECK constraint on ``purchase_orders.status``
exactly (note: the fully-received state is ``received``). Transitions are the
single source of truth for what is allowed; the service calls ``assert_transition``
before mutating a PO.

    draft ──submit──> pending_approval ──approve──> approved ──send──> sent
      │                     │                          │                 │
   cancel                reject/cancel              cancel            receive
      ▼                     ▼ / ▼                       ▼            (partial/full)
  cancelled            rejected / cancelled        cancelled   partially_received
                                                                      │  │
                                                                 receive  receive
                                                                      ▼  ▼
                                                          partially_received / received

Editing line items / header is permitted only while a PO is in ``draft``.
Terminal states (no further transitions): received, cancelled, rejected.
"""
from __future__ import annotations

from enum import Enum

from app.procurement.domain.exceptions import InvalidTransitionError


class POStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"  # fully received
    CANCELLED = "cancelled"


class POAction(str, Enum):
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    SEND = "send"
    RECEIVE = "receive"


# Fixed (non-receiving) transitions: (current, action) -> next status.
_TRANSITIONS: dict[tuple[POStatus, POAction], POStatus] = {
    (POStatus.DRAFT, POAction.SUBMIT): POStatus.PENDING_APPROVAL,
    (POStatus.DRAFT, POAction.CANCEL): POStatus.CANCELLED,
    (POStatus.PENDING_APPROVAL, POAction.APPROVE): POStatus.APPROVED,
    (POStatus.PENDING_APPROVAL, POAction.REJECT): POStatus.REJECTED,
    (POStatus.PENDING_APPROVAL, POAction.CANCEL): POStatus.CANCELLED,
    (POStatus.APPROVED, POAction.SEND): POStatus.SENT,
    (POStatus.APPROVED, POAction.CANCEL): POStatus.CANCELLED,
}

# Receiving is quantity-driven: the resulting status (partially_received vs
# received) is computed by the receiving logic, so it is modelled separately.
RECEIVABLE_STATUSES: frozenset[POStatus] = frozenset(
    {POStatus.SENT, POStatus.PARTIALLY_RECEIVED}
)

TERMINAL_STATUSES: frozenset[POStatus] = frozenset(
    {POStatus.RECEIVED, POStatus.CANCELLED, POStatus.REJECTED}
)


def _coerce(status) -> POStatus:
    return status if isinstance(status, POStatus) else POStatus(status)


def can_transition(current, action: POAction) -> bool:
    current = _coerce(current)
    if action is POAction.RECEIVE:
        return current in RECEIVABLE_STATUSES
    return (current, action) in _TRANSITIONS


def target_status(current, action: POAction) -> POStatus | None:
    """Resulting status for a *fixed* transition. RECEIVE returns None because
    its target depends on received quantities (see domain.receiving)."""
    if action is POAction.RECEIVE:
        return None
    return _TRANSITIONS.get((_coerce(current), action))


def assert_transition(current, action: POAction) -> None:
    if not can_transition(current, action):
        cur = _coerce(current).value
        raise InvalidTransitionError(
            f"Cannot '{action.value}' a purchase order in status '{cur}'."
        )


def can_edit(status) -> bool:
    """Header/line edits are only allowed while the PO is a draft."""
    return _coerce(status) is POStatus.DRAFT


def is_terminal(status) -> bool:
    return _coerce(status) in TERMINAL_STATUSES
