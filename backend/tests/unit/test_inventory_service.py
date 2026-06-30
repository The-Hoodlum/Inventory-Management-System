"""Unit tests for InventoryService: balance math, the movement ledger, and audit.

All run against in-memory fakes (see conftest), so no database is required.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

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
from tests.conftest import FakeLookup


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


# -------------------- issue against a reservation (sales / POS) -------------------- #
class _FakeReservationRepo:
    """Minimal hold store: returns the seeded reservation and nets it down on consume,
    mirroring ReservationRepository so the service can be unit-tested without a DB."""

    def __init__(self, reservation=None) -> None:
        self._res = reservation
        self.consumed: list[Decimal] = []

    async def active_for(self, reference_id, reference_type=None):
        return self._res

    async def consume(self, *, tenant_id, inv, reservation, qty, user_id):
        take = min(qty, reservation.qty)
        inv.qty_reserved = inv.qty_reserved - take
        reservation.qty = reservation.qty - take
        self.consumed.append(take)


def _svc_with_reservation(fake_inventory_repo, fake_audit_repo, ids, reservation=None):
    from app.services.inventory_service import InventoryService

    products = FakeLookup({ids.p1})
    warehouses = FakeLookup({ids.wh1, ids.wh2})
    return InventoryService(
        fake_inventory_repo, products, warehouses, fake_audit_repo,
        _FakeReservationRepo(reservation),
    )


async def test_issue_against_reservation_consumes_hold_audits_and_records_demand(
    fake_inventory_repo, fake_audit_repo, ids
):
    # A confirmed sales-order line holds 5 of the 20 on hand.
    fake_inventory_repo.seed(ids.p1, ids.wh1, on_hand=20, reserved=5, tenant_id=ids.tenant)
    line_id = uuid.uuid4()
    note_id = uuid.uuid4()
    reservation = SimpleNamespace(qty=Decimal("5"))
    svc = _svc_with_reservation(fake_inventory_repo, fake_audit_repo, ids, reservation)

    inv = await svc.issue_against_reservation(
        tenant_id=ids.tenant, user_id=ids.user, product_id=ids.p1, warehouse_id=ids.wh1,
        quantity=Decimal("5"), reference_type="sales_delivery", reference_id=note_id,
        reason="Sales delivery DN-1", reservation_ref=line_id,
        reservation_ref_type="sales_order_line", demand_source="sale",
    )

    assert inv.qty_on_hand == Decimal("15")      # on-hand deducted once
    assert inv.qty_reserved == Decimal("0")      # the line's own hold was consumed
    mv = fake_inventory_repo.movements[-1]
    assert mv.movement_type == "issue" and mv.quantity == Decimal("-5")
    assert mv.reference_type == "sales_delivery"
    # Same audit story as a manual issue, regardless of which document triggered it.
    assert any(e["action"] == "stock.issue" for e in fake_audit_repo.entries)
    # Demand fed exactly once, tagged with the sale source.
    assert len(fake_inventory_repo.demand) == 1
    assert fake_inventory_repo.demand[0].source == "sale"


async def test_pos_issue_without_reservation_draws_from_free_pool(
    fake_inventory_repo, fake_audit_repo, ids
):
    fake_inventory_repo.seed(ids.p1, ids.wh1, on_hand=10, tenant_id=ids.tenant)
    svc = _svc_with_reservation(fake_inventory_repo, fake_audit_repo, ids, reservation=None)

    inv = await svc.issue_against_reservation(
        tenant_id=ids.tenant, user_id=ids.user, product_id=ids.p1, warehouse_id=ids.wh1,
        quantity=Decimal("4"), reference_type="sales_delivery", reference_id=uuid.uuid4(),
        reason="POS sale DN-2", reservation_ref=None, demand_source="pos",
    )
    assert inv.qty_on_hand == Decimal("6")
    assert fake_inventory_repo.demand[0].source == "pos"


async def test_issue_against_reservation_respects_other_holds(
    fake_inventory_repo, fake_audit_repo, ids
):
    # 10 on hand but 8 are reserved by OTHER demands; only 2 are free. POS holds nothing,
    # so a request for 5 must fail rather than raid someone else's reservation.
    fake_inventory_repo.seed(ids.p1, ids.wh1, on_hand=10, reserved=8, tenant_id=ids.tenant)
    svc = _svc_with_reservation(fake_inventory_repo, fake_audit_repo, ids, reservation=None)

    with pytest.raises(BusinessRuleError):
        await svc.issue_against_reservation(
            tenant_id=ids.tenant, user_id=ids.user, product_id=ids.p1, warehouse_id=ids.wh1,
            quantity=Decimal("5"), reference_type="sales_delivery", reference_id=uuid.uuid4(),
            reason="POS sale", reservation_ref=None, demand_source="pos",
        )
