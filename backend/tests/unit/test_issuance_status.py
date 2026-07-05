"""Unit tests for the issuance status machine + the no-direct-stock-write guard."""
from __future__ import annotations

import pathlib

from app.issuance.domain import status as S


def test_return_outcome():
    # Every returnable line accounted -> RETURNED.
    assert S.return_outcome([(1, 1), (3, 3)]) == S.RETURNED
    # A line still out (0 accounted) -> PARTIALLY_RETURNED.
    assert S.return_outcome([(1, 1), (3, 0)]) == S.PARTIALLY_RETURNED
    # No returnable lines (all consumable) -> RETURNED (nothing owed back).
    assert S.return_outcome([]) == S.RETURNED


def test_state_sets():
    assert S.OPEN == {S.OUT_ON_LOAN, S.PARTIALLY_RETURNED}
    assert S.CANCELLABLE == {S.DRAFT}
    assert S.CONDITIONS == {S.GOOD, S.FAIR, S.NEEDS_ATTENTION}


def test_issuance_module_never_writes_stock_directly():
    """Issuance is a loan record: it must move stock ONLY through the inventory service /
    reservation repo (fungible) and the serialized registry (bikes) — never by writing
    qty_on_hand or the ledger itself. Grep-guard the whole package."""
    pkg = pathlib.Path(S.__file__).resolve().parents[1]  # app/issuance/
    offenders = []
    for path in pkg.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "qty_on_hand =" in text or "qty_on_hand=" in text or ".add_movement(" in text:
            offenders.append(path.name)
    assert offenders == [], f"issuance must not write stock directly: {offenders}"
