"""Service-level tests for ProcurementService.

Covers the full workflow (create -> submit -> approve/reject -> send -> receive),
approval, partial/multiple receipts, inventory effects, invalid transitions, and
audit/event recording. Runs entirely on in-memory fakes (no database). Reuses
``fake_inventory_repo``, ``fake_audit_repo`` and ``ids`` from conftest.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.procurement.schemas import (
    POCreate,
    POLineCreate,
    POUpdate,
    ReceiptLineIn,
    ReceiveRequest,
)
from app.procurement.service import ProcurementService


class _Sess:
    async def flush(self) -> None:
        return None


class FakeProcurementRepo:
    def __init__(self, supplier_present: bool = True) -> None:
        self.session = _Sess()
        self._pos: dict[uuid.UUID, Any] = {}
        self._lines: dict[uuid.UUID, list[Any]] = {}
        self.events: list[Any] = []
        self._counter = 0
        self._supplier_present = supplier_present

    async def next_po_number(self, tenant_id):
        self._counter += 1
        return f"PO-TEST-{self._counter:04d}"

    async def add_po(self, **f: Any):
        now = dt.datetime.now(dt.timezone.utc)
        po = SimpleNamespace(
            id=uuid.uuid4(), created_at=now, updated_at=now, version=0,
            approved_by=None, approved_at=None, **f,
        )
        self._pos[po.id] = po
        self._lines.setdefault(po.id, [])
        return po

    async def get(self, po_id):
        return self._pos.get(po_id)

    async def get_for_update(self, po_id):
        return self._pos.get(po_id)

    async def list(self, **kw):
        rows = list(self._pos.values())
        return rows, len(rows)

    async def add_line(self, **f: Any):
        line = SimpleNamespace(id=uuid.uuid4(), **f)
        self._lines.setdefault(f["po_id"], []).append(line)
        return line

    async def lines_for(self, po_id):
        return list(self._lines.get(po_id, []))

    async def lines_for_update(self, po_id):
        return list(self._lines.get(po_id, []))

    async def delete_lines(self, po_id):
        self._lines[po_id] = []

    async def add_event(self, **f: Any):
        ev = SimpleNamespace(id=uuid.uuid4(), **f)
        self.events.append(ev)
        return ev

    async def events_for(self, po_id):
        return [e for e in self.events if e.po_id == po_id]

    async def get_supplier(self, supplier_id):
        if not self._supplier_present:
            return None
        return SimpleNamespace(
            id=supplier_id, name="Acme Supplies", currency="USD",
            email="supplier@example.test", contact_person="Pat", phone="+260000000",
            country="ZM",
        )

    async def get_warehouse(self, warehouse_id):
        return SimpleNamespace(id=warehouse_id, name="Main DC")

    async def get_product(self, product_id):
        return SimpleNamespace(id=product_id, sku="SKU-1", name="Widget", units_per_carton=10)


class DummyEmail:
    async def send_purchase_order(self, **kw):
        return False, "disabled in tests"


# --------------------------------- fixtures --------------------------------- #
@pytest.fixture
def proc_repo() -> FakeProcurementRepo:
    return FakeProcurementRepo()


@pytest.fixture
def po_service(proc_repo, fake_inventory_repo, fake_audit_repo) -> ProcurementService:
    return ProcurementService(proc_repo, fake_inventory_repo, fake_audit_repo, DummyEmail())


def _po_create(ids, product2=None) -> POCreate:
    lines = [
        POLineCreate(
            product_id=ids.p1, ordered_qty=Decimal(100), unit_cost=Decimal("2.50"),
            units_per_carton=10,
        )
    ]
    if product2 is not None:
        lines.append(
            POLineCreate(product_id=product2, ordered_qty=Decimal(50), unit_cost=Decimal("4.00"))
        )
    return POCreate(supplier_id=uuid.uuid4(), warehouse_id=ids.wh1, lines=lines)


async def _advance_to_sent(po_service, ids, po_id):
    await po_service.submit(po_id=po_id, comment=None, actor=ids.user, tenant=ids.tenant, ip=None)
    await po_service.approve(po_id=po_id, comment=None, actor=ids.user, tenant=ids.tenant, ip=None)
    await po_service.send(po_id=po_id, comment=None, actor=ids.user, tenant=ids.tenant, ip=None)


# ----------------------------------- tests ---------------------------------- #
async def test_create_persists_draft_with_totals(po_service, proc_repo, fake_audit_repo, ids):
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip="1.2.3.4"
    )
    assert out.status == "draft"
    assert out.po_number.startswith("PO-TEST-")
    assert out.subtotal == Decimal("250.0000")  # 100 * 2.50
    assert out.total == out.subtotal
    assert out.lines[0].ordered_cartons == 10   # ceil(100 / 10)
    assert out.lines[0].remaining_qty == Decimal(100)
    assert any(e.action == "created" for e in proc_repo.events)
    assert any(a["action"] == "po.create" for a in fake_audit_repo.entries)


async def test_create_unknown_supplier_raises(fake_inventory_repo, fake_audit_repo, ids):
    repo = FakeProcurementRepo(supplier_present=False)
    svc = ProcurementService(repo, fake_inventory_repo, fake_audit_repo, DummyEmail())
    with pytest.raises(NotFoundError):
        await svc.create_po(tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip=None)


async def test_submit_approve_send_workflow(po_service, proc_repo, ids):
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip=None
    )
    s = await po_service.submit(
        po_id=out.id, comment="please review", actor=ids.user, tenant=ids.tenant, ip=None
    )
    assert s.status == "pending_approval"
    a = await po_service.approve(
        po_id=out.id, comment="looks good", actor=ids.user, tenant=ids.tenant, ip=None
    )
    assert a.status == "approved"
    assert a.approved_by == ids.user
    assert a.approved_at is not None
    sent = await po_service.send(
        po_id=out.id, comment=None, actor=ids.user, tenant=ids.tenant, ip=None
    )
    assert sent.status == "sent"
    assert {"submitted", "approved", "sent"} <= {e.action for e in proc_repo.events}


async def test_reject_records_comment(po_service, proc_repo, ids):
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip=None
    )
    await po_service.submit(po_id=out.id, comment=None, actor=ids.user, tenant=ids.tenant, ip=None)
    r = await po_service.reject(
        po_id=out.id, comment="prices too high", actor=ids.user, tenant=ids.tenant, ip=None
    )
    assert r.status == "rejected"
    rejected = [e for e in proc_repo.events if e.action == "rejected"]
    assert rejected and rejected[0].comment == "prices too high"


async def test_cancel_from_draft(po_service, ids):
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip=None
    )
    c = await po_service.cancel(
        po_id=out.id, comment="duplicate", actor=ids.user, tenant=ids.tenant, ip=None
    )
    assert c.status == "cancelled"


async def test_invalid_transition_raises_conflict(po_service, ids):
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip=None
    )
    # Approving a draft is not allowed.
    with pytest.raises(ConflictError):
        await po_service.approve(
            po_id=out.id, comment=None, actor=ids.user, tenant=ids.tenant, ip=None
        )
    # Submitting twice is not allowed.
    await po_service.submit(po_id=out.id, comment=None, actor=ids.user, tenant=ids.tenant, ip=None)
    with pytest.raises(ConflictError):
        await po_service.submit(
            po_id=out.id, comment=None, actor=ids.user, tenant=ids.tenant, ip=None
        )


async def test_receive_full_updates_inventory_and_closes(
    po_service, proc_repo, fake_inventory_repo, fake_audit_repo, ids
):
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip=None
    )
    line_id = out.lines[0].id
    await _advance_to_sent(po_service, ids, out.id)

    res = await po_service.receive(
        tenant_id=ids.tenant, user_id=ids.user, po_id=out.id,
        req=ReceiveRequest(lines=[ReceiptLineIn(line_id=line_id, quantity=Decimal(100))]),
        ip=None,
    )
    assert res.fully_received is True
    assert res.purchase_order.status == "received"
    assert res.received_now == Decimal(100)
    assert res.movements_created == 1
    assert res.purchase_order.lines[0].received_qty == Decimal(100)
    assert res.purchase_order.lines[0].remaining_qty == Decimal(0)

    inv = fake_inventory_repo._rows[(ids.p1, ids.wh1)]
    assert inv.qty_on_hand == Decimal(100)
    assert any(
        m.movement_type == "receipt" and m.reference_type == "purchase_order"
        for m in fake_inventory_repo.movements
    )
    assert {"received", "closed"} <= {e.action for e in proc_repo.events}
    audit_actions = {a["action"] for a in fake_audit_repo.entries}
    assert {"goods.received", "po.closed"} <= audit_actions


async def test_receive_partial_then_full(po_service, fake_inventory_repo, ids):
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip=None
    )
    line_id = out.lines[0].id
    await _advance_to_sent(po_service, ids, out.id)

    r1 = await po_service.receive(
        tenant_id=ids.tenant, user_id=ids.user, po_id=out.id,
        req=ReceiveRequest(lines=[ReceiptLineIn(line_id=line_id, quantity=Decimal(60))]),
        ip=None,
    )
    assert r1.fully_received is False
    assert r1.purchase_order.status == "partially_received"
    assert r1.purchase_order.lines[0].received_qty == Decimal(60)
    assert r1.purchase_order.lines[0].remaining_qty == Decimal(40)
    assert fake_inventory_repo._rows[(ids.p1, ids.wh1)].qty_on_hand == Decimal(60)

    r2 = await po_service.receive(
        tenant_id=ids.tenant, user_id=ids.user, po_id=out.id,
        req=ReceiveRequest(lines=[ReceiptLineIn(line_id=line_id, quantity=Decimal(40))]),
        ip=None,
    )
    assert r2.fully_received is True
    assert r2.purchase_order.status == "received"
    assert fake_inventory_repo._rows[(ids.p1, ids.wh1)].qty_on_hand == Decimal(100)


async def test_multi_line_receipt_partial(po_service, fake_inventory_repo, ids):
    product2 = uuid.uuid4()
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids, product2=product2), ip=None
    )
    line_a = next(ln.id for ln in out.lines if ln.product_id == ids.p1)
    line_b = next(ln.id for ln in out.lines if ln.product_id == product2)
    await _advance_to_sent(po_service, ids, out.id)

    res = await po_service.receive(
        tenant_id=ids.tenant, user_id=ids.user, po_id=out.id,
        req=ReceiveRequest(
            lines=[
                ReceiptLineIn(line_id=line_a, quantity=Decimal(100)),  # complete
                ReceiptLineIn(line_id=line_b, quantity=Decimal(20)),   # partial
            ]
        ),
        ip=None,
    )
    assert res.fully_received is False
    assert res.purchase_order.status == "partially_received"
    assert res.movements_created == 2


async def test_over_receipt_raises_business_rule(po_service, ids):
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip=None
    )
    line_id = out.lines[0].id
    await _advance_to_sent(po_service, ids, out.id)
    with pytest.raises(BusinessRuleError):
        await po_service.receive(
            tenant_id=ids.tenant, user_id=ids.user, po_id=out.id,
            req=ReceiveRequest(lines=[ReceiptLineIn(line_id=line_id, quantity=Decimal(150))]),
            ip=None,
        )


async def test_receive_requires_receivable_status(po_service, ids):
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip=None
    )
    line_id = out.lines[0].id
    # PO is still a draft -> not receivable.
    with pytest.raises(ConflictError):
        await po_service.receive(
            tenant_id=ids.tenant, user_id=ids.user, po_id=out.id,
            req=ReceiveRequest(lines=[ReceiptLineIn(line_id=line_id, quantity=Decimal(10))]),
            ip=None,
        )


async def test_update_draft_replaces_lines(po_service, proc_repo, ids):
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip=None
    )
    res = await po_service.update_po(
        tenant_id=ids.tenant, user_id=ids.user, po_id=out.id,
        data=POUpdate(
            notes="revised",
            lines=[POLineCreate(product_id=ids.p1, ordered_qty=Decimal(10), unit_cost=Decimal("5.00"))],
        ),
        ip=None,
    )
    assert res.notes == "revised"
    assert res.subtotal == Decimal("50.0000")
    assert len(res.lines) == 1
    assert res.version == out.version + 1
    assert any(e.action == "updated" for e in proc_repo.events)


async def test_update_after_submit_raises(po_service, ids):
    out = await po_service.create_po(
        tenant_id=ids.tenant, user_id=ids.user, data=_po_create(ids), ip=None
    )
    await po_service.submit(po_id=out.id, comment=None, actor=ids.user, tenant=ids.tenant, ip=None)
    with pytest.raises(BusinessRuleError):
        await po_service.update_po(
            tenant_id=ids.tenant, user_id=ids.user, po_id=out.id,
            data=POUpdate(notes="too late"), ip=None,
        )
