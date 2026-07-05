"""Branch -> customer/reseller delivery status (pure, unit-tested).

sale mode:         draft --deliver--> delivered
consignment mode:  draft --deliver--> out_at_reseller --settle/return-->
                     partially_settled | settled | returned
draft --cancel--> cancelled

A sale delivery is proof of a handover the sale already deducted for. A consignment
holds stock at the reseller (available reduced / bikes consigned, on_hand unchanged);
sold lines are SETTLED (a real deduction / bike sale), unsold lines RETURNED.
"""
from __future__ import annotations

DRAFT = "draft"
DELIVERED = "delivered"            # sale mode: handed over
OUT_AT_RESELLER = "out_at_reseller"
PARTIALLY_SETTLED = "partially_settled"
SETTLED = "settled"
RETURNED = "returned"
CANCELLED = "cancelled"

STATUSES = frozenset({DRAFT, DELIVERED, OUT_AT_RESELLER, PARTIALLY_SETTLED, SETTLED, RETURNED, CANCELLED})
# A consignment still at the reseller (drives the not-sellable derivation for bikes).
OPEN_CONSIGNMENT = frozenset({OUT_AT_RESELLER, PARTIALLY_SETTLED})
RECONCILABLE = frozenset({OUT_AT_RESELLER, PARTIALLY_SETTLED})
CANCELLABLE = frozenset({DRAFT})

SALE, CONSIGNMENT = "sale", "consignment"
MODES = frozenset({SALE, CONSIGNMENT})

_EPS = 1e-9


def reconcile_outcome(lines: list[tuple[float, float, float]]) -> str:
    """Status after a settle/return, from per-line (qty, settled, returned).
    Every line fully accounted (settled+returned >= qty): all-returned -> RETURNED,
    otherwise SETTLED. Anything still out at the reseller -> PARTIALLY_SETTLED."""
    if not lines:
        return SETTLED
    all_done = all(settled + returned + _EPS >= qty for qty, settled, returned in lines)
    if not all_done:
        return PARTIALLY_SETTLED
    any_settled = any(settled > _EPS for _q, settled, _r in lines)
    return SETTLED if any_settled else RETURNED
