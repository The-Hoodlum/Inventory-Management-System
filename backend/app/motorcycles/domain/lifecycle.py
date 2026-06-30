"""Serialized-unit lifecycle state machine (pure, unit-tested).

One explicit transition graph for a serialized asset's whole life. Legal transitions
only; illegal ones are rejected and (in the service) every accepted transition is written
to the unit's immutable event ledger with from/to/user — exactly like the sales document
state machines.

    received -> assembly_required -> in_assembly -> assembled -> inspected ->
    reserved -> sold -> delivered -> registered -> warranty_active

Sensible skips are explicit in the graph: a unit needing no assembly goes
``received -> inspected`` directly, and ``inspected`` can go straight to ``sold`` without
``reserved``. ``reserved -> inspected`` releases a hold. ``cancelled`` is a terminal
reachable only before a unit is sold (once sold, a sales document exists).
"""
from __future__ import annotations

# --- statuses ---
RECEIVED = "received"
ASSEMBLY_REQUIRED = "assembly_required"
IN_ASSEMBLY = "in_assembly"
ASSEMBLED = "assembled"
INSPECTED = "inspected"
RESERVED = "reserved"
SOLD = "sold"
DELIVERED = "delivered"
REGISTERED = "registered"
WARRANTY_ACTIVE = "warranty_active"
CANCELLED = "cancelled"

STATUSES = frozenset({
    RECEIVED, ASSEMBLY_REQUIRED, IN_ASSEMBLY, ASSEMBLED, INSPECTED,
    RESERVED, SOLD, DELIVERED, REGISTERED, WARRANTY_ACTIVE, CANCELLED,
})

# The allowed transition graph — the single source of truth for legality.
_ALLOWED: dict[str, set[str]] = {
    RECEIVED: {ASSEMBLY_REQUIRED, INSPECTED, CANCELLED},
    ASSEMBLY_REQUIRED: {IN_ASSEMBLY, CANCELLED},
    IN_ASSEMBLY: {ASSEMBLED, CANCELLED},
    ASSEMBLED: {INSPECTED, CANCELLED},
    INSPECTED: {RESERVED, SOLD, CANCELLED},
    RESERVED: {SOLD, INSPECTED, CANCELLED},   # -> inspected releases the hold
    SOLD: {DELIVERED},
    DELIVERED: {REGISTERED},
    REGISTERED: {WARRANTY_ACTIVE},
    WARRANTY_ACTIVE: set(),
    CANCELLED: set(),
}

TERMINAL = frozenset({WARRANTY_ACTIVE, CANCELLED})

# States from which a unit may be reserved / sold (used by the service + UI).
RESERVABLE_FROM = frozenset({INSPECTED, RESERVED})
SELLABLE_FROM = frozenset({INSPECTED, RESERVED})


def can_transition(old: str, new: str) -> bool:
    return new in _ALLOWED.get(old, set())


def allowed_next(status: str) -> list[str]:
    """The legal next statuses from ``status`` (stable order), for quick-action UIs/APIs."""
    order = [
        ASSEMBLY_REQUIRED, IN_ASSEMBLY, ASSEMBLED, INSPECTED, RESERVED, SOLD,
        DELIVERED, REGISTERED, WARRANTY_ACTIVE, CANCELLED,
    ]
    nxt = _ALLOWED.get(status, set())
    return [s for s in order if s in nxt]
