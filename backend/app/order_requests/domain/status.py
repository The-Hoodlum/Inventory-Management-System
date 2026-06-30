"""Order-request / stock-transfer status workflow + line math (pure, unit-tested).

Status lifecycle (a transfer is an order-request with a destination location):

    draft --> pending | cancelled
    pending --> approved | partially_approved | rejected | cancelled
    approved / partially_approved --> partially_issued | issued | in_transit | cancelled
    partially_issued --> partially_issued | issued | in_transit | partially_received | received
    issued / in_transit --> partially_received | received | completed
    partially_received --> partially_received | received | completed
    received --> completed
    rejected / cancelled / completed are terminal.

Stock is HELD (reserved) on approval, CONSUMED (physically moved/deducted) on issue,
and RELEASED on cancel/reject. A transfer goes ISSUED -> IN_TRANSIT (it has left the
source, awaiting receipt); a pure consumption (no destination) goes straight to ISSUED.
Receiving captures received / missing / damaged / extra per line and must reconcile
before completion.
"""
from __future__ import annotations

# --- statuses ---
DRAFT = "draft"
PENDING = "pending"
APPROVED = "approved"
PARTIALLY_APPROVED = "partially_approved"
REJECTED = "rejected"
PARTIALLY_ISSUED = "partially_issued"
ISSUED = "issued"
IN_TRANSIT = "in_transit"
PARTIALLY_RECEIVED = "partially_received"
RECEIVED = "received"
CANCELLED = "cancelled"
COMPLETED = "completed"

STATUSES = frozenset({
    DRAFT, PENDING, APPROVED, PARTIALLY_APPROVED, REJECTED, PARTIALLY_ISSUED,
    ISSUED, IN_TRANSIT, PARTIALLY_RECEIVED, RECEIVED, CANCELLED, COMPLETED,
})
APPROVED_STATES = frozenset({APPROVED, PARTIALLY_APPROVED})
ISSUED_STATES = frozenset({PARTIALLY_ISSUED, ISSUED, IN_TRANSIT})
# Stock that has left the source but is not yet fully received (drives "in transit" reporting).
IN_TRANSIT_STATES = frozenset({ISSUED, IN_TRANSIT, PARTIALLY_RECEIVED})

# --- transfer types (the request "purpose"; industry-agnostic) ---
BRANCH_TRANSFER = "branch_transfer"      # moves stock between branches
INTERNAL_TRANSFER = "internal_transfer"  # moves stock between locations in one branch
PURPOSES = frozenset({
    "for_sale", "shelf_replenishment", "internal_transfer", "branch_transfer",
    "workshop_use", "damaged_replacement", "office_use", "stock_adjustment", "other",
})

_ALLOWED: dict[str, set[str]] = {
    DRAFT: {PENDING, CANCELLED},
    PENDING: {APPROVED, PARTIALLY_APPROVED, REJECTED, CANCELLED},
    APPROVED: {PARTIALLY_ISSUED, ISSUED, IN_TRANSIT, CANCELLED},
    PARTIALLY_APPROVED: {PARTIALLY_ISSUED, ISSUED, IN_TRANSIT, CANCELLED},
    PARTIALLY_ISSUED: {PARTIALLY_ISSUED, ISSUED, IN_TRANSIT, PARTIALLY_RECEIVED, RECEIVED},
    ISSUED: {IN_TRANSIT, PARTIALLY_RECEIVED, RECEIVED, COMPLETED},
    IN_TRANSIT: {PARTIALLY_RECEIVED, RECEIVED, COMPLETED},
    PARTIALLY_RECEIVED: {PARTIALLY_RECEIVED, RECEIVED, COMPLETED},
    RECEIVED: {COMPLETED},
    REJECTED: set(),
    CANCELLED: set(),
    COMPLETED: set(),
}

# Cancellation is only allowed before any stock has been issued.
CANCELLABLE = frozenset({DRAFT, PENDING, APPROVED, PARTIALLY_APPROVED})

_EPS = 1e-9


def can_transition(old: str, new: str) -> bool:
    return new in _ALLOWED.get(old, set())


def clamp_approved(approved_qty: float, requested_qty: float) -> float:
    """Approved can't be negative or exceed what was requested."""
    return max(0.0, min(float(approved_qty), float(requested_qty)))


def approval_outcome(approved_vs_requested: list[tuple[float, float]]) -> str:
    """Decide the resulting status from per-line (approved, requested) pairs.

    All lines approved in full -> APPROVED; some short -> PARTIALLY_APPROVED;
    nothing approved -> REJECTED (the caller should use the explicit reject path).
    """
    total_approved = sum(a for a, _ in approved_vs_requested)
    if total_approved <= 0:
        return REJECTED
    fully = all(a >= r for a, r in approved_vs_requested)
    return APPROVED if fully else PARTIALLY_APPROVED


def issue_outcome(issued_vs_approved: list[tuple[float, float]], *, is_transfer: bool) -> str:
    """Status after an issue. Fully issued -> IN_TRANSIT (transfer) / ISSUED (consumption);
    anything still owed -> PARTIALLY_ISSUED."""
    fully = all(i >= a for i, a in issued_vs_approved)
    if not fully:
        return PARTIALLY_ISSUED
    return IN_TRANSIT if is_transfer else ISSUED


def receive_outcome(accounted_vs_issued: list[tuple[float, float]]) -> str:
    """Status after a receipt from per-line (accounted, issued+extra) pairs, where
    accounted = received + missing + damaged. Every issued line fully accounted ->
    RECEIVED; otherwise PARTIALLY_RECEIVED."""
    fully = all(acc + _EPS >= owed for acc, owed in accounted_vs_issued)
    return RECEIVED if fully else PARTIALLY_RECEIVED


def outstanding(requested_qty: float, issued_qty: float) -> float:
    """Quantity still owed after issuing."""
    return max(0.0, float(requested_qty) - float(issued_qty))


def reconcile_variance(
    issued: float, extra: float, received: float, missing: float, damaged: float
) -> float:
    """Receipt variance = (issued + extra) - (received + missing + damaged).
    Zero means the line reconciles."""
    return (float(issued) + float(extra)) - (float(received) + float(missing) + float(damaged))


def is_balanced(
    issued: float, extra: float, received: float, missing: float, damaged: float
) -> bool:
    """A line reconciles when received + missing + damaged == issued + extra."""
    return abs(reconcile_variance(issued, extra, received, missing, damaged)) < _EPS
