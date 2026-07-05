"""Internal issuance / handover status workflow (pure, unit-tested).

    draft --issue--> out_on_loan --return--> partially_returned | returned
    draft --cancel--> cancelled

Issuing makes returnable stock temporarily not-sellable (bikes marked out-on-loan,
fungible items HELD) without a permanent deduction; consumables are deducted at
handover. Returning releases the hold / frees the bike; a damaged bike routes to
`on_hold`. All returnable lines closed -> returned; some still out -> partially_returned.
"""
from __future__ import annotations

DRAFT = "draft"
OUT_ON_LOAN = "out_on_loan"
PARTIALLY_RETURNED = "partially_returned"
RETURNED = "returned"
CANCELLED = "cancelled"

STATUSES = frozenset({DRAFT, OUT_ON_LOAN, PARTIALLY_RETURNED, RETURNED, CANCELLED})
# An issuance whose returnable lines are still out (drives out-on-loan availability).
OPEN = frozenset({OUT_ON_LOAN, PARTIALLY_RETURNED})
RETURNABLE_STATES = frozenset({OUT_ON_LOAN, PARTIALLY_RETURNED})
CANCELLABLE = frozenset({DRAFT})

# Bike return conditions.
GOOD, FAIR, NEEDS_ATTENTION = "good", "fair", "needs_attention"
CONDITIONS = frozenset({GOOD, FAIR, NEEDS_ATTENTION})

_EPS = 1e-9


def return_outcome(returnable_lines: list[tuple[float, float]]) -> str:
    """Status after a return, from per-RETURNABLE-line (qty, returned+missing accounted).
    Every returnable line fully accounted -> RETURNED; otherwise PARTIALLY_RETURNED.
    (Consumable lines are excluded — they are never expected back.)"""
    if not returnable_lines:
        return RETURNED
    done = all(accounted + _EPS >= qty for qty, accounted in returnable_lines)
    return RETURNED if done else PARTIALLY_RETURNED
