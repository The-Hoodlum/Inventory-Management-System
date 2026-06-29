"""Sales document status machines (pure, unit-tested).

Quotation:  draft -> sent -> accepted | rejected | expired | cancelled
Sales order: draft -> confirmed (reserves stock) -> partially_delivered -> delivered;
             cancellable until anything is delivered (releases reservations).
Delivery:   pending -> delivered | partially_delivered | returned
Invoice:    draft -> sent -> partially_paid -> paid; overdue; cancelled
"""
from __future__ import annotations

from decimal import Decimal

# --- quotation ---
Q_DRAFT, Q_SENT, Q_ACCEPTED, Q_REJECTED, Q_EXPIRED, Q_CANCELLED = (
    "draft", "sent", "accepted", "rejected", "expired", "cancelled",
)
QUOTE_STATUSES = frozenset({Q_DRAFT, Q_SENT, Q_ACCEPTED, Q_REJECTED, Q_EXPIRED, Q_CANCELLED})
_QUOTE_ALLOWED = {
    Q_DRAFT: {Q_SENT, Q_ACCEPTED, Q_CANCELLED},
    Q_SENT: {Q_ACCEPTED, Q_REJECTED, Q_EXPIRED, Q_CANCELLED},
    Q_ACCEPTED: {Q_CANCELLED},
    Q_REJECTED: set(), Q_EXPIRED: set(), Q_CANCELLED: set(),
}
# A quotation may be converted to a sales order while still open.
QUOTE_CONVERTIBLE = frozenset({Q_DRAFT, Q_SENT, Q_ACCEPTED})

# --- sales order ---
SO_DRAFT, SO_CONFIRMED, SO_RESERVED, SO_PICKING = "draft", "confirmed", "reserved", "picking"
SO_PARTIALLY_DELIVERED, SO_DELIVERED, SO_CANCELLED = "partially_delivered", "delivered", "cancelled"
SO_STATUSES = frozenset({
    SO_DRAFT, SO_CONFIRMED, SO_RESERVED, SO_PICKING,
    SO_PARTIALLY_DELIVERED, SO_DELIVERED, SO_CANCELLED,
})
# Stock has been reserved but not all delivered (cancellation releases the hold).
SO_OPEN_RESERVED = frozenset({SO_CONFIRMED, SO_RESERVED, SO_PICKING, SO_PARTIALLY_DELIVERED})
SO_DELIVERABLE = frozenset({SO_CONFIRMED, SO_RESERVED, SO_PICKING, SO_PARTIALLY_DELIVERED})
SO_CANCELLABLE = frozenset({SO_DRAFT, SO_CONFIRMED, SO_RESERVED, SO_PICKING})

# --- delivery ---
DN_PENDING, DN_DELIVERED, DN_PARTIAL, DN_RETURNED = (
    "pending", "delivered", "partially_delivered", "returned",
)

# --- invoice ---
INV_DRAFT, INV_SENT, INV_PARTIALLY_PAID, INV_PAID, INV_OVERDUE, INV_CANCELLED = (
    "draft", "sent", "partially_paid", "paid", "overdue", "cancelled",
)
INVOICE_STATUSES = frozenset({INV_DRAFT, INV_SENT, INV_PARTIALLY_PAID, INV_PAID, INV_OVERDUE, INV_CANCELLED})
INVOICE_PAYABLE = frozenset({INV_DRAFT, INV_SENT, INV_PARTIALLY_PAID, INV_OVERDUE})

_EPS = Decimal("0.00005")


def quote_can_transition(old: str, new: str) -> bool:
    return new in _QUOTE_ALLOWED.get(old, set())


def so_delivery_outcome(line_pairs: list[tuple[float, float]]) -> str:
    """(delivered_qty, ordered_qty) per line -> DELIVERED if all fully delivered,
    else PARTIALLY_DELIVERED."""
    fully = all(d + 1e-9 >= o for d, o in line_pairs)
    return SO_DELIVERED if fully else SO_PARTIALLY_DELIVERED


def invoice_status_after_payment(grand_total, amount_paid) -> str:
    """PAID when fully settled, PARTIALLY_PAID when some paid, else SENT."""
    total, paid = Decimal(str(grand_total)), Decimal(str(amount_paid))
    if paid + _EPS >= total and total > 0:
        return INV_PAID
    if paid > _EPS:
        return INV_PARTIALLY_PAID
    return INV_SENT
