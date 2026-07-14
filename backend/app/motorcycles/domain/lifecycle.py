"""Serialized-unit SALE-STATUS state machine (pure, unit-tested).

The unit tracks four INDEPENDENT facts that move on their own — this module owns only
the first (the sale status); the others are plain columns on the unit:

  * SALE STATUS   — one of exactly five values (assembly is folded in here).
  * inspected     — boolean, set independently of the sale status.
  * registered    — boolean (+ registration number), independent of the sale status.
  * hold reason    — text, required while on hold, kept for history once cleared.

The five sale statuses and their legal transitions:

    unassembled --> assembled              (assembly done)
    unassembled --> on_hold                (pulled aside before assembly)
    assembled   --> reserved | sold | on_hold
    reserved    --> sold | assembled       (fulfilled, or the reservation fell through)
    on_hold     --> assembled | unassembled   (cleared -> back to sellable)

Rules the service layer enforces on top of this graph:
  * `reserved` REQUIRES a customer; `sold` carries the buyer via the sales invoice.
  * `on_hold` REQUIRES a hold reason and NO customer, and can NOT go straight to `sold`
    (it must return to `assembled` first — enforced by the graph + SELLABLE_FROM).

Selling still goes through the existing sales documents (reserve links a sales order,
sell links an invoice); there is no parallel sales path here.
"""
from __future__ import annotations

# --- the five sale statuses ---
UNASSEMBLED = "unassembled"
ASSEMBLED = "assembled"
RESERVED = "reserved"
ON_HOLD = "on_hold"
SOLD = "sold"

STATUSES = frozenset({UNASSEMBLED, ASSEMBLED, RESERVED, ON_HOLD, SOLD})

# The legal transition graph — the single source of truth for legality.
# A unit may be RESERVED or SOLD straight from 'unassembled': the dealership sells bikes
# before assembly (e.g. to resellers who assemble them, or retail with assembly to follow).
# Assembly is tracked as an independent fact (assembled_date + assembly_pending), NOT by
# forcing 'assembled' first.
_ALLOWED: dict[str, set[str]] = {
    UNASSEMBLED: {ASSEMBLED, ON_HOLD, RESERVED, SOLD},
    ASSEMBLED: {RESERVED, SOLD, ON_HOLD},
    RESERVED: {SOLD, ASSEMBLED},          # fulfilled, or the reservation fell through
    ON_HOLD: {ASSEMBLED, UNASSEMBLED},    # cleared -> back to sellable
    SOLD: set(),
}

TERMINAL = frozenset({SOLD})

# Reporting roll-ups. IN_STOCK = physically on hand, not sold and not reserved; POST_SALE
# is what the unified sales log counts as a motorcycle sale (see reports.sales_log).
IN_STOCK = frozenset({UNASSEMBLED, ASSEMBLED, ON_HOLD})
POST_SALE = frozenset({SOLD})

# Where a serialized hold / sale may ORIGINATE from (the service checks these). Selling /
# reserving from 'unassembled' is allowed — assembly is a separate operational step.
RESERVABLE_FROM = frozenset({ASSEMBLED, UNASSEMBLED})
SELLABLE_FROM = frozenset({ASSEMBLED, RESERVED, UNASSEMBLED})

# The only statuses that carry a customer; every other status must have none.
CUSTOMER_STATUSES = frozenset({RESERVED, SOLD})

# Stable ordering for quick-action UIs / APIs.
_ORDER = [UNASSEMBLED, ASSEMBLED, RESERVED, ON_HOLD, SOLD]


def can_transition(old: str, new: str) -> bool:
    return new in _ALLOWED.get(old, set())


def allowed_next(status: str) -> list[str]:
    """Legal next statuses from ``status`` (stable order), for quick-action UIs."""
    nxt = _ALLOWED.get(status, set())
    return [s for s in _ORDER if s in nxt]
