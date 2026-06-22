"""Order-request status workflow + line math (pure, unit-tested).

Status lifecycle:
    pending --> approved | partially_approved | rejected | cancelled
    approved / partially_approved --> issued | cancelled
    rejected / issued / cancelled are terminal.

Inventory is deducted only on the approved -> issued transition (handled in the service).
"""
from __future__ import annotations

# --- statuses ---
PENDING = "pending"
APPROVED = "approved"
PARTIALLY_APPROVED = "partially_approved"
REJECTED = "rejected"
ISSUED = "issued"
CANCELLED = "cancelled"

STATUSES = frozenset({PENDING, APPROVED, PARTIALLY_APPROVED, REJECTED, ISSUED, CANCELLED})
APPROVED_STATES = frozenset({APPROVED, PARTIALLY_APPROVED})

# --- purposes ---
PURPOSES = frozenset({"for_sale", "shelf_replenishment", "workshop_use", "office_use", "other"})

_ALLOWED: dict[str, set[str]] = {
    PENDING: {APPROVED, PARTIALLY_APPROVED, REJECTED, CANCELLED},
    APPROVED: {ISSUED, CANCELLED},
    PARTIALLY_APPROVED: {ISSUED, CANCELLED},
    REJECTED: set(),
    ISSUED: set(),
    CANCELLED: set(),
}


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


def outstanding(requested_qty: float, issued_qty: float) -> float:
    """Quantity still owed after issuing."""
    return max(0.0, float(requested_qty) - float(issued_qty))
