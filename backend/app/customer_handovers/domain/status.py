"""Handover status + the pure "can this be completed?" gate.

Two statuses only: DRAFT (editable) and COMPLETED (locked). Completing a handover is
gated on the things that make it a valid signed record — the payment is settled, the
quality sign-offs are in, the customer signed, and the delivery is dated. Kept pure so
it is unit-tested without a database, and reused by the service to build clear errors.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

DRAFT = "DRAFT"
COMPLETED = "COMPLETED"
STATUSES = frozenset({DRAFT, COMPLETED})


def _d(v: Any) -> Decimal:
    try:
        return Decimal(str(v)) if v is not None else Decimal("0")
    except Exception:
        return Decimal("0")


def completion_errors(h: Any) -> list[str]:
    """Return a list of human-readable reasons this handover can NOT be completed.
    Empty list == ready. ``h`` may be the ORM row or the read schema (attribute access).

    Rules:
      * the invoice must be settled in full (no outstanding balance);
      * Quality Control and the Branch Manager must have signed off;
      * the customer must have signed (name captured);
      * the delivery must be dated.
    """
    errors: list[str] = []

    if _d(getattr(h, "balance_zmw", 0)) > Decimal("0"):
        errors.append(
            f"Outstanding balance of {_d(getattr(h, 'balance_zmw', 0))} ZMW — settle payment "
            "before completing (or record the payment)."
        )
    if not getattr(h, "quality_control_officer_signed", False):
        errors.append("Quality Control Officer sign-off is required.")
    if not getattr(h, "branch_manager_signed", False):
        errors.append("Branch Manager sign-off is required.")
    if not (getattr(h, "customer_signature_name", None) or "").strip():
        errors.append("Customer signature (name) is required.")
    if getattr(h, "delivery_date", None) is None:
        errors.append("Delivery date is required.")

    return errors
