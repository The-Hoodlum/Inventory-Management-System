"""Unit tests for InventoryService: balance math, the movement ledger, and audit.

All run against in-memory fakes (see conftest), so no database is required.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.exceptions import BusinessRuleError
from app.schemas.inventory import (
    AdjustStockRequest,
    IssueLine,
    IssueStockRequest,
    ReceiptLine,
    ReceiveStockRequest,
    TransferStockRequest,
)


async def test_receive_increments_creates_movement_and_audits(
    inv_service, fake_inventory_repo, fake_audit_repo, ids
):
    req = ReceiveStockRequest(
        warehouse_id=ids.wh1,
        lines=[ReceiptLine(product_id=ids.p1, quantity=Decimal("10"), unit_cost=Decimal("2.5"))],
    )
    rows = await inv_service.receive(tenant_id=ids.tenant, user_id=ids.user, req=req)

    assert rows[0].qty_on_hand == Decimal("10")
    assert rows[0].version == 1
    assert len(fake_inventory_repo.movements) == 1
    mv = fake_inventory_repo.movements[0]
    assert mv.movement_type == "receipt"
    assert mv.quantity == Decimal("10")
    assert any(e["action"] == "stock.receive" for e in fake_audit_repo.entries)


async def test_issue_insufficient_stock_raises(inv_service, ids):
    req = IssueStockRequest(
        warehouse_id=ids.wh1,
        lines=[IssueLine(product_id=ids.p1, quantity=Decimal("5"))],
    )
    with pytest.raises(BusinessRuleError):
        await inv_service.issue(tenant_id=ids.tenant, user_id=ids.user, req=req)


async def test_issue_reduces_on_hand_and_writes_negative_movement(
    inv_service, fake_inventory_repo, ids
):
    fake_inventory_repo.seed(ids.p1, ids.wh1, on_hand=20, tenant_id=ids.tenant)
    req = IssueStockRequest(
        warehouse_id=ids.wh1,
        lines=[IssueLine(product_id=ids.p1, quantity=Decimal("8"))],
    )
    rows = await inv_service.issue(tenant_id=ids.tenant, user_id=ids.user, req=req)
    assert rows[0].qty_on_hand == Decimal("12")
    assert fake_inventory_repo.movements[-1].movement_type == "issue"
    assert fake_inventory_repo.movements[-1].quantity == Decimal("-8")


async def test_adjust_below_zero_raises(inv_service, fake_inventory_repo, ids):
    fake_inventory_repo.seed(ids.p1, ids.wh1, on_hand=3, tenant_id=ids.tenant)
    req = AdjustStockRequest(
        warehouse_id=ids.wh1, product_id=ids.p1, delta=Decimal("-5"), reason="cycle count"
    )
    with pytest.raises(BusinessRuleError):
        await inv_service.adjust(tenant_id=ids.tenant, user_id=ids.user, req=req)


async def test_adjust_applies_and_audits(inv_service, fake_inventory_repo, fake_audit_repo, ids):
    fake_inventory_repo.seed(ids.p1, ids.wh1, on_hand=3, tenant_id=ids.tenant)
    req = AdjustStockRequest(
        warehouse_id=ids.wh1, product_id=ids.p1, delta=Decimal("4"), reason="found units"
    )
    inv = await inv_service.adjust(tenant_id=ids.tenant, user_id=ids.user, req=req)
    assert inv.qty_on_hand == Decimal("7")
    assert fake_inventory_repo.movements[-1].movement_type == "adjustment"
    assert any(e["action"] == "stock.adjust" for e in fake_audit_repo.entries)


async def test_transfer_moves_qty_and_creates_two_movements(
    inv_service, fake_inventory_repo, fake_audit_repo, ids
):
    fake_inventory_repo.seed(ids.p1, ids.wh1, on_hand=15, tenant_id=ids.tenant)
    req = TransferStockRequest(
        product_id=ids.p1,
        from_warehouse_id=ids.wh1,
        to_warehouse_id=ids.wh2,
        quantity=Decimal("6"),
    )
    rows = await inv_service.transfer(tenant_id=ids.tenant, user_id=ids.user, req=req)

    src = next(r for r in rows if r.warehouse_id == ids.wh1)
    dst = next(r for r in rows if r.warehouse_id == ids.wh2)
    assert src.qty_on_hand == Decimal("9")
    assert dst.qty_on_hand == Decimal("6")

    types = {m.movement_type for m in fake_inventory_repo.movements}
    assert {"transfer_out", "transfer_in"} <= types
    assert sum(1 for e in fake_audit_repo.entries if e["action"] == "stock.transfer") == 2


async def test_transfer_insufficient_stock_raises(inv_service, ids):
    req = TransferStockRequest(
        product_id=ids.p1,
        from_warehouse_id=ids.wh1,
        to_warehouse_id=ids.wh2,
        quantity=Decimal("3"),
    )
    with pytest.raises(BusinessRuleError):
        await inv_service.transfer(tenant_id=ids.tenant, user_id=ids.user, req=req)
