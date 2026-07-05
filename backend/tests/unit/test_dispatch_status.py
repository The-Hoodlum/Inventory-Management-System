"""Unit tests for the dispatch-note status + receipt reconciliation (pure, no DB)."""
from __future__ import annotations

import pathlib

from app.dispatch.domain import status as S


def test_dispatch_module_never_writes_stock_directly():
    """The delivery note is PAPER: it must move stock ONLY through InventoryService
    (parts) / the serialized registry (bikes), never by writing qty_on_hand or the
    ledger itself. Grep-guard the whole dispatch package."""
    pkg = pathlib.Path(S.__file__).resolve().parents[1]  # app/dispatch/
    offenders = []
    for path in pkg.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # Assigning qty_on_hand, or calling the low-level ledger writer, would be a
        # second stock-write path — forbidden here.
        if "qty_on_hand =" in text or "qty_on_hand=" in text or ".add_movement(" in text:
            offenders.append(path.name)
    assert offenders == [], f"dispatch must not write stock directly: {offenders}"


def test_line_reconciles():
    assert S.line_reconciles(5, 5, 0, 0)          # all received
    assert S.line_reconciles(5, 4, 1, 0)          # 1 missing
    assert S.line_reconciles(5, 3, 1, 1)          # 1 missing + 1 damaged
    assert not S.line_reconciles(5, 4, 0, 0)      # a unit unaccounted for


def test_receive_outcome_full_vs_short():
    # Every line fully received, nothing missing/damaged -> RECEIVED.
    assert S.receive_outcome([(5, 5, 0, 0), (1, 1, 0, 0)]) == S.RECEIVED
    # A shortfall on any line -> PARTIALLY_RECEIVED (a recorded discrepancy).
    assert S.receive_outcome([(5, 5, 0, 0), (2, 1, 1, 0)]) == S.PARTIALLY_RECEIVED
    # Damage counts as a discrepancy even if nothing is missing.
    assert S.receive_outcome([(3, 2, 0, 1)]) == S.PARTIALLY_RECEIVED


def test_state_sets():
    assert S.RECEIVABLE == {S.IN_TRANSIT, S.PARTIALLY_RECEIVED}
    assert S.CANCELLABLE == {S.DRAFT}
    assert len(S.STATUSES) == 5
