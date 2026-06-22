"""Order-request service flows with in-memory fakes (no DB):
create -> approve (full/partial) / reject -> issue (deduct), plus visibility + guards.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.order_requests.domain import status as S
from app.order_requests.schemas import (
    ApproveRequest,
    LineApproval,
    OrderRequestCreate,
    OrderRequestLineCreate,
    RejectRequest,
)
from app.order_requests.service import OrderRequestService

TENANT = uuid.uuid4()
CASHIER = uuid.uuid4()
ADMIN = uuid.uuid4()
BRANCH = uuid.uuid4()
P1 = uuid.uuid4()
P2 = uuid.uuid4()


class _Line:
    def __init__(self, product_id, requested_qty):
        self.id = uuid.uuid4()
        self.product_id = product_id
        self.requested_qty = Decimal(str(requested_qty))
        self.approved_qty = Decimal("0")
        self.issued_qty = Decimal("0")
        self.remarks = None


class _Header:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Session:
    async def flush(self):
        return None


class FakeRepo:
    def __init__(self, on_hand: dict | None = None):
        self.session = _Session()
        self.headers: dict = {}
        self.audits: list = []
        self.issued: list = []
        self._on_hand = on_hand or {}

    async def next_request_number(self, tenant_id):
        return "REQ-2026-00001"

    async def create(self, *, tenant_id, request_number, branch_id, requested_by, purpose, comments, lines):
        h = _Header(
            id=uuid.uuid4(), tenant_id=tenant_id, request_number=request_number, branch_id=branch_id,
            requested_by=requested_by, purpose=purpose, status="pending", comments=comments,
            requested_date=dt.datetime.now(dt.UTC), approved_by=None, approved_date=None,
            issued_by=None, issued_date=None,
            lines=[_Line(line["product_id"], line["requested_qty"]) for line in lines],
        )
        self.headers[h.id] = h
        return h

    async def get(self, request_id):
        return self.headers.get(request_id)

    async def add_audit(self, **kw):
        self.audits.append(kw)

    async def audit_trail(self, request_id):
        return []

    async def issue_line(self, *, tenant_id, line, branch_id, qty, user_id, request_id):
        avail = self._on_hand.get(line.product_id, Decimal("9999"))
        if avail < qty:
            return f"Insufficient stock for product {line.product_id}"
        line.issued_qty = qty
        self.issued.append((line.product_id, qty))
        return None

    async def product_index(self, ids):
        return {i: ("SKU", "Name") for i in ids}

    async def warehouse_names(self, ids):
        return {i: "Lusaka" for i in ids}

    async def user_names(self, ids):
        return {i: "User" for i in ids if i}


class FakeAudit:
    def __init__(self):
        self.entries = []

    async def add(self, **kw):
        self.entries.append(kw)


def _svc(repo=None):
    repo = repo or FakeRepo()
    return OrderRequestService(repo, FakeAudit()), repo


def _create_payload():
    return OrderRequestCreate(
        branch_id=BRANCH, purpose="for_sale",
        lines=[OrderRequestLineCreate(product_id=P1, requested_qty=10),
               OrderRequestLineCreate(product_id=P2, requested_qty=5)],
    )


async def _make_pending(svc):
    return await svc.create(tenant_id=TENANT, user_id=CASHIER, payload=_create_payload())


async def test_create_is_pending_and_audited():
    svc, repo = _svc()
    out = await _make_pending(svc)
    assert out.status == S.PENDING
    assert out.request_number == "REQ-2026-00001"
    assert len(out.lines) == 2
    assert any(a["action"] == "created" for a in repo.audits)


async def test_full_approval():
    svc, repo = _svc()
    out = await _make_pending(svc)
    line_ids = [ln.id for ln in out.lines]
    approved = await svc.approve(
        tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
        payload=ApproveRequest(lines=[LineApproval(line_id=line_ids[0], approved_qty=10),
                                      LineApproval(line_id=line_ids[1], approved_qty=5)]),
    )
    assert approved.status == S.APPROVED
    assert all(ln.approved_qty == ln.requested_qty for ln in approved.lines)


async def test_partial_approval_records_outstanding():
    svc, _ = _svc()
    out = await _make_pending(svc)
    line_ids = [ln.id for ln in out.lines]
    approved = await svc.approve(
        tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
        payload=ApproveRequest(lines=[LineApproval(line_id=line_ids[0], approved_qty=6),
                                      LineApproval(line_id=line_ids[1], approved_qty=5)]),
    )
    assert approved.status == S.PARTIALLY_APPROVED
    first = next(ln for ln in approved.lines if ln.id == line_ids[0])
    assert first.approved_qty == 6


async def test_approve_caps_at_requested():
    svc, _ = _svc()
    out = await _make_pending(svc)
    line_ids = [ln.id for ln in out.lines]
    approved = await svc.approve(
        tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
        payload=ApproveRequest(lines=[LineApproval(line_id=line_ids[0], approved_qty=999),
                                      LineApproval(line_id=line_ids[1], approved_qty=5)]),
    )
    first = next(ln for ln in approved.lines if ln.id == line_ids[0])
    assert first.approved_qty == 10  # clamped to requested
    assert approved.status == S.APPROVED


async def test_approve_nothing_is_rejected_error():
    svc, _ = _svc()
    out = await _make_pending(svc)
    line_ids = [ln.id for ln in out.lines]
    with pytest.raises(BusinessRuleError):
        await svc.approve(
            tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
            payload=ApproveRequest(lines=[LineApproval(line_id=line_ids[0], approved_qty=0),
                                          LineApproval(line_id=line_ids[1], approved_qty=0)]),
        )


async def test_reject_sets_reason():
    svc, _ = _svc()
    out = await _make_pending(svc)
    rejected = await svc.reject(
        tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
        payload=RejectRequest(reason="Out of budget"),
    )
    assert rejected.status == S.REJECTED
    assert rejected.comments == "Out of budget"


async def test_issue_deducts_and_completes():
    svc, repo = _svc()
    out = await _make_pending(svc)
    line_ids = [ln.id for ln in out.lines]
    await svc.approve(
        tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
        payload=ApproveRequest(lines=[LineApproval(line_id=line_ids[0], approved_qty=10),
                                      LineApproval(line_id=line_ids[1], approved_qty=5)]),
    )
    issued = await svc.issue(tenant_id=TENANT, actor_id=ADMIN, request_id=out.id)
    assert issued.status == S.ISSUED
    assert len(repo.issued) == 2  # both lines deducted
    assert all(ln.issued_qty == ln.approved_qty for ln in issued.lines)


async def test_issue_requires_approval_first():
    svc, _ = _svc()
    out = await _make_pending(svc)
    with pytest.raises(BusinessRuleError):
        await svc.issue(tenant_id=TENANT, actor_id=ADMIN, request_id=out.id)  # still pending


async def test_issue_insufficient_stock_errors():
    repo = FakeRepo(on_hand={P1: Decimal("3")})  # only 3 of P1 on hand
    svc = OrderRequestService(repo, FakeAudit())
    out = await svc.create(tenant_id=TENANT, user_id=CASHIER, payload=_create_payload())
    line_ids = [ln.id for ln in out.lines]
    await svc.approve(
        tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
        payload=ApproveRequest(lines=[LineApproval(line_id=line_ids[0], approved_qty=10),
                                      LineApproval(line_id=line_ids[1], approved_qty=5)]),
    )
    with pytest.raises(BusinessRuleError):
        await svc.issue(tenant_id=TENANT, actor_id=ADMIN, request_id=out.id)


async def test_branch_user_cannot_view_others_requests():
    svc, _ = _svc()
    out = await _make_pending(svc)  # created by CASHIER
    other = uuid.uuid4()
    with pytest.raises(NotFoundError):
        await svc.get(request_id=out.id, viewer_id=other, is_admin=False)
    # admin can view
    seen = await svc.get(request_id=out.id, viewer_id=ADMIN, is_admin=True)
    assert seen.id == out.id
