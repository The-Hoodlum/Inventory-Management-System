"""Unit tests for the customer-delivery reconcile machine + no-direct-stock-write guard."""
from __future__ import annotations

import pathlib

from app.customer_delivery.domain import status as S


def test_reconcile_outcome():
    # Everything accounted, some sold -> SETTLED.
    assert S.reconcile_outcome([(5, 5, 0), (2, 0, 2)]) == S.SETTLED
    # Everything accounted, nothing sold -> RETURNED.
    assert S.reconcile_outcome([(5, 0, 5), (2, 0, 2)]) == S.RETURNED
    # A line still partly out at the reseller -> PARTIALLY_SETTLED.
    assert S.reconcile_outcome([(5, 3, 0), (2, 0, 2)]) == S.PARTIALLY_SETTLED
    # No lines -> SETTLED (nothing owed back).
    assert S.reconcile_outcome([]) == S.SETTLED


def test_state_sets():
    assert S.OPEN_CONSIGNMENT == {S.OUT_AT_RESELLER, S.PARTIALLY_SETTLED}
    assert S.RECONCILABLE == {S.OUT_AT_RESELLER, S.PARTIALLY_SETTLED}
    assert S.CANCELLABLE == {S.DRAFT}
    assert S.MODES == {S.SALE, S.CONSIGNMENT}


def test_customer_delivery_module_never_writes_stock_directly():
    """A delivery note is PAPER documenting a movement. It must move stock ONLY through the
    inventory service / reservation repo (fungible) and the serialized registry (bikes) —
    never by writing qty_on_hand or the ledger itself. Grep-guard the whole package."""
    pkg = pathlib.Path(S.__file__).resolve().parents[1]  # app/customer_delivery/
    offenders = []
    for path in pkg.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "qty_on_hand =" in text or "qty_on_hand=" in text or ".add_movement(" in text:
            offenders.append(path.name)
    assert offenders == [], f"customer_delivery must not write stock directly: {offenders}"
