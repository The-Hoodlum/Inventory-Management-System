"""Bike-issue status workflow (pure, unit-tested).

    open --start--> in_repair --resolve--> resolved
    open ------------resolve-------------> resolved

Opening an issue holds the bike (`on_hold`) so it can't be sold mid-repair. Resolving
COMMITS the part consumption (deducted through InventoryService) and returns the unit to
its prior sellable status. `resolved` is terminal — a fresh fault is a new issue.
"""
from __future__ import annotations

OPEN = "open"
IN_REPAIR = "in_repair"
RESOLVED = "resolved"

STATUSES = frozenset({OPEN, IN_REPAIR, RESOLVED})
# Statuses in which the issue is still active: the bike is on hold and lines are editable.
ACTIVE = frozenset({OPEN, IN_REPAIR})
# Statuses a resolve may be triggered from.
RESOLVABLE_FROM = frozenset({OPEN, IN_REPAIR})

_ALLOWED: dict[str, set[str]] = {
    OPEN: {IN_REPAIR, RESOLVED},
    IN_REPAIR: {RESOLVED},
    RESOLVED: set(),
}


def can_transition(old: str, new: str) -> bool:
    return new in _ALLOWED.get(old, set())
