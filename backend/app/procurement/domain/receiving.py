"""Goods-receipt computation (pure).

Given the ordered/received state of a PO's lines and a new receipt (quantity per
line), this computes the new received totals and the resulting PO status, and
rejects invalid receipts (unknown line, non-positive quantity, over-receipt).
Supports partial receipts and multiple receipts against the same PO, because the
input carries the quantity already received per line.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.procurement.domain.exceptions import ReceiptError
from app.procurement.domain.states import POStatus

ZERO = Decimal("0")


@dataclass(frozen=True)
class LineState:
    line_id: uuid.UUID
    product_id: uuid.UUID
    ordered_qty: Decimal
    already_received: Decimal

    @property
    def remaining(self) -> Decimal:
        return self.ordered_qty - self.already_received


@dataclass(frozen=True)
class LineReceipt:
    line_id: uuid.UUID
    product_id: uuid.UUID
    received_now: Decimal
    new_received_total: Decimal
    fully_received: bool


@dataclass(frozen=True)
class ReceiptOutcome:
    lines: list[LineReceipt]          # only the lines received in this receipt
    resulting_status: POStatus        # PARTIALLY_RECEIVED or RECEIVED
    fully_received: bool              # every line of the PO now fully received
    total_received_now: Decimal


def apply_receipt(
    line_states: list[LineState],
    receipt: dict[uuid.UUID, Decimal],
) -> ReceiptOutcome:
    """Validate and apply a receipt; return the per-line outcome and new status.

    ``receipt`` maps line_id -> quantity received now (must be > 0). Lines absent
    from ``receipt`` are untouched. Raises ReceiptError on any invalid quantity.
    """
    if not receipt:
        raise ReceiptError("A receipt must include at least one line.")

    by_id = {ls.line_id: ls for ls in line_states}

    unknown = set(receipt) - set(by_id)
    if unknown:
        raise ReceiptError(f"Receipt references unknown PO line(s): {sorted(map(str, unknown))}")

    received_lines: list[LineReceipt] = []
    total_now = ZERO
    for line_id, qty in receipt.items():
        qty = Decimal(qty)
        if qty <= 0:
            raise ReceiptError(f"Received quantity for line {line_id} must be > 0.")
        ls = by_id[line_id]
        if qty > ls.remaining:
            raise ReceiptError(
                f"Over-receipt on line {line_id}: receiving {qty} but only "
                f"{ls.remaining} remaining (ordered {ls.ordered_qty}, "
                f"already received {ls.already_received})."
            )
        new_total = ls.already_received + qty
        total_now += qty
        received_lines.append(
            LineReceipt(
                line_id=line_id,
                product_id=ls.product_id,
                received_now=qty,
                new_received_total=new_total,
                fully_received=(new_total == ls.ordered_qty),
            )
        )

    # Determine PO status from the cumulative state after this receipt.
    receipt_totals = {lr.line_id: lr.new_received_total for lr in received_lines}
    fully = all(
        receipt_totals.get(ls.line_id, ls.already_received) == ls.ordered_qty
        for ls in line_states
    )
    status = POStatus.RECEIVED if fully else POStatus.PARTIALLY_RECEIVED

    return ReceiptOutcome(
        lines=received_lines,
        resulting_status=status,
        fully_received=fully,
        total_received_now=total_now,
    )
