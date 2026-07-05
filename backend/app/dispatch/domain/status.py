"""Dispatch-note status workflow + per-line receipt reconciliation (pure, unit-tested).

A delivery/dispatch note documents a movement; the TYPE fixes the direction. Type 1
(warehouse -> branch transfer) confirm-on-receipt lifecycle:

    draft --dispatch--> in_transit --receive--> partially_received | received
    draft --cancel--> cancelled

On dispatch the source is decremented; on receipt the destination is incremented and
each line is reconciled (received + missing + damaged == dispatched). A short receipt
lands in ``partially_received`` (a recorded discrepancy) — never silently completed.
"""
from __future__ import annotations

DRAFT = "draft"
IN_TRANSIT = "in_transit"
PARTIALLY_RECEIVED = "partially_received"
RECEIVED = "received"
CANCELLED = "cancelled"

STATUSES = frozenset({DRAFT, IN_TRANSIT, PARTIALLY_RECEIVED, RECEIVED, CANCELLED})
RECEIVABLE = frozenset({IN_TRANSIT, PARTIALLY_RECEIVED})
CANCELLABLE = frozenset({DRAFT})

_EPS = 1e-9


def line_reconciles(dispatched: float, received: float, missing: float, damaged: float) -> bool:
    """A line reconciles when received + missing + damaged == dispatched."""
    return abs(float(dispatched) - (float(received) + float(missing) + float(damaged))) < _EPS


def receive_outcome(lines: list[tuple[float, float, float, float]]) -> str:
    """Status after a receipt, from per-line (dispatched, received, missing, damaged).

    Every line fully received (nothing missing/damaged) -> RECEIVED; any shortfall or
    damage -> PARTIALLY_RECEIVED (a recorded discrepancy)."""
    clean = all(
        float(received) + _EPS >= float(dispatched) and float(missing) <= _EPS and float(damaged) <= _EPS
        for dispatched, received, missing, damaged in lines
    )
    return RECEIVED if clean else PARTIALLY_RECEIVED
