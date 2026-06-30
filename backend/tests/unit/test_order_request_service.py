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
    CancelRequest,
    CompleteRequest,
    LineApproval,
    LineReceipt,
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
        self.received_qty = None
        self.missing_qty = None
        self.damaged_qty = None
        self.extra_qty = None
        self.remarks = None


class _Header:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Session:
    async def flush(self):
        return None


class FakeRepo:
    def __init__(self, on_hand: dict | None = None, branch_ids: set | None = None):
        self.session = _Session()
        self.headers: dict = {}
        self.audits: list = []
        self.issued: list = []
        self.transfers: list = []
        self.reserved: list = []
        self.released: list = []
        self.received_credits: list = []
        self.ledger: list = []
        self.calls: dict = {}
        self._on_hand = on_hand or {}
        self._branch_ids = branch_ids or set()  # empty = unrestricted

    async def next_request_number(self, tenant_id):
        return "REQ-2026-00001"

    async def user_branch_ids(self, user_id):
        return self._branch_ids

    async def create(self, *, tenant_id, request_number, branch_id, requested_by, purpose, comments,
                     lines, destination_branch_id=None, status="pending"):
        h = _Header(
            id=uuid.uuid4(), tenant_id=tenant_id, request_number=request_number, branch_id=branch_id,
            destination_branch_id=destination_branch_id,
            requested_by=requested_by, purpose=purpose, status=status, comments=comments,
            requested_date=dt.datetime.now(dt.UTC), approved_by=None, approved_date=None,
            issued_by=None, issued_date=None, received_by=None, received_date=None,
            completed_by=None, completed_date=None, completion_remarks=None,
            lines=[_Line(line["product_id"], line["requested_qty"]) for line in lines],
        )
        self.headers[h.id] = h
        return h

    async def get(self, request_id):
        return self.headers.get(request_id)

    async def get_for_update(self, request_id):
        return self.headers.get(request_id)

    async def add_audit(self, **kw):
        self.audits.append(kw)

    async def audit_trail(self, request_id):
        return []

    async def reserve_line(self, *, tenant_id, line, source_id, qty, user_id):
        # Mirrors the real reserve: insufficient AVAILABLE stock fails at approval.
        avail = self._on_hand.get(line.product_id, Decimal("9999"))
        if avail < qty:
            return f"Insufficient available stock for product {line.product_id}"
        self.reserved.append((line.product_id, qty, source_id))
        return None

    async def release_reservations(self, *, tenant_id, lines, user_id):
        self.released.extend((ln.product_id) for ln in lines)

    async def issue_line(self, *, tenant_id, line, branch_id, qty, user_id, request_id):
        line.issued_qty = (line.issued_qty or Decimal("0")) + qty
        self.issued.append((line.product_id, qty))
        return None

    async def transfer_line(self, *, tenant_id, line, source_id, dest_id, qty, user_id, request_id):
        line.issued_qty = (line.issued_qty or Decimal("0")) + qty
        self.transfers.append((line.product_id, qty, source_id, dest_id))
        return None

    async def receive_line(self, *, tenant_id, line, dest_id, received, damaged, user_id, request_id):
        self.received_credits.append((line.product_id, dest_id, received, damaged))

    async def add_transfer_ledger(self, **fields):
        self.ledger.append(fields)

    async def transfer_ledger(self, request_id):
        return [f for f in self.ledger if f.get("request_id") == request_id]

    async def list_requests(self, **filters):
        rows = list(self.headers.values())
        if "requested_by" in filters:
            rows = [h for h in rows if h.requested_by == filters["requested_by"]]
        return rows

    async def product_index(self, ids):
        self.calls["product_index"] = self.calls.get("product_index", 0) + 1
        return {i: ("SKU", "Name") for i in ids}

    async def warehouse_names(self, ids):
        self.calls["warehouse_names"] = self.calls.get("warehouse_names", 0) + 1
        return {i: "Lusaka" for i in ids}

    async def location_index(self, ids):
        self.calls["location_index"] = self.calls.get("location_index", 0) + 1
        # location_id -> (location_name, branch_id, branch_name)
        return {i: ("Main Warehouse", BRANCH, "Lusaka") for i in ids}

    async def user_names(self, ids):
        self.calls["user_names"] = self.calls.get("user_names", 0) + 1
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


async def test_create_blocked_for_unassigned_branch():
    other_branch = uuid.uuid4()
    repo = FakeRepo(branch_ids={other_branch})  # user scoped to a different branch than BRANCH
    svc = OrderRequestService(repo, FakeAudit())
    with pytest.raises(BusinessRuleError):
        await svc.create(tenant_id=TENANT, user_id=CASHIER, payload=_create_payload())  # payload.branch_id == BRANCH


async def test_create_allowed_for_assigned_branch():
    repo = FakeRepo(branch_ids={BRANCH})  # scoped to the request's branch
    svc = OrderRequestService(repo, FakeAudit())
    out = await svc.create(tenant_id=TENANT, user_id=CASHIER, payload=_create_payload())
    assert out.status == S.PENDING


async def test_history_batches_enrichment_no_n_plus_1():
    repo = FakeRepo()
    svc = OrderRequestService(repo, FakeAudit())
    for _ in range(3):  # three requests
        await svc.create(tenant_id=TENANT, user_id=CASHIER, payload=_create_payload())
    repo.calls.clear()
    out = await svc.history(viewer_id=ADMIN, is_admin=True, filters={})
    assert len(out) == 3
    # enrichment fetched ONCE for the whole page, not once per request
    assert repo.calls["product_index"] == 1
    assert repo.calls["location_index"] == 1
    assert repo.calls["user_names"] == 1


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


async def test_approve_insufficient_available_stock_errors():
    # Stock is now HELD at approval, so an over-approval fails when reserving (not at issue).
    repo = FakeRepo(on_hand={P1: Decimal("3")})  # only 3 of P1 available
    svc = OrderRequestService(repo, FakeAudit())
    out = await svc.create(tenant_id=TENANT, user_id=CASHIER, payload=_create_payload())
    line_ids = [ln.id for ln in out.lines]
    with pytest.raises(BusinessRuleError):
        await svc.approve(
            tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
            payload=ApproveRequest(lines=[LineApproval(line_id=line_ids[0], approved_qty=10),
                                          LineApproval(line_id=line_ids[1], approved_qty=5)]),
        )


async def test_branch_user_cannot_view_others_requests():
    svc, _ = _svc()
    out = await _make_pending(svc)  # created by CASHIER
    other = uuid.uuid4()
    with pytest.raises(NotFoundError):
        await svc.get(request_id=out.id, viewer_id=other, is_admin=False)
    # admin can view
    seen = await svc.get(request_id=out.id, viewer_id=ADMIN, is_admin=True)
    assert seen.id == out.id


async def _approve_and_issue(svc, out):
    line_ids = [ln.id for ln in out.lines]
    await svc.approve(
        tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
        payload=ApproveRequest(lines=[LineApproval(line_id=line_ids[0], approved_qty=10),
                                      LineApproval(line_id=line_ids[1], approved_qty=5)]),
    )
    return await svc.issue(tenant_id=TENANT, actor_id=ADMIN, request_id=out.id)


async def test_cancel_by_requester_before_issue():
    svc, repo = _svc()
    out = await _make_pending(svc)
    cancelled = await svc.cancel(
        tenant_id=TENANT, actor_id=CASHIER, request_id=out.id, is_admin=False,
        payload=CancelRequest(reason="No longer needed"),
    )
    assert cancelled.status == S.CANCELLED
    assert cancelled.comments == "No longer needed"
    assert any(a["action"] == "cancelled" for a in repo.audits)


async def test_cancel_hidden_from_other_branch_users():
    svc, _ = _svc()
    out = await _make_pending(svc)  # by CASHIER
    with pytest.raises(NotFoundError):
        await svc.cancel(tenant_id=TENANT, actor_id=uuid.uuid4(), request_id=out.id,
                         is_admin=False, payload=CancelRequest())


async def test_cannot_cancel_once_issued():
    svc, _ = _svc()
    out = await _make_pending(svc)
    await _approve_and_issue(svc, out)
    with pytest.raises(BusinessRuleError):
        await svc.cancel(tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
                         is_admin=True, payload=CancelRequest(reason="too late"))


async def test_complete_requires_issue_first():
    svc, _ = _svc()
    out = await _make_pending(svc)
    with pytest.raises(BusinessRuleError):  # still pending
        await svc.complete(tenant_id=TENANT, actor_id=CASHIER, request_id=out.id,
                           payload=CompleteRequest(remarks="too early"))


async def test_complete_records_receipt_and_discrepancy():
    svc, repo = _svc()
    out = await _make_pending(svc)
    issued = await _approve_and_issue(svc, out)
    assert issued.status == S.ISSUED
    line_ids = [ln.id for ln in out.lines]
    # Completion now requires EVERY issued line to reconcile (received+missing+damaged
    # = issued+extra). Line 0: 9 received + 1 missing = 10 issued; line 1: 5 received.
    completed = await svc.complete(
        tenant_id=TENANT, actor_id=CASHIER, request_id=out.id,
        payload=CompleteRequest(
            remarks="Received with one short",
            lines=[LineReceipt(line_id=line_ids[0], received_qty=9, missing_qty=1, damaged_qty=0),
                   LineReceipt(line_id=line_ids[1], received_qty=5)],
        ),
    )
    assert completed.status == S.COMPLETED
    assert completed.completion_remarks == "Received with one short"
    first = next(ln for ln in completed.lines if ln.id == line_ids[0])
    assert first.received_qty == 9 and first.missing_qty == 1
    assert any(a["action"] == "completed" for a in repo.audits)


async def test_complete_blocked_when_unreconciled():
    # A line that was issued but not reconciled blocks completion.
    svc, _ = _svc()
    out = await _make_pending(svc)
    issued = await _approve_and_issue(svc, out)
    assert issued.status == S.ISSUED
    line_ids = [ln.id for ln in out.lines]
    with pytest.raises(BusinessRuleError):
        await svc.complete(
            tenant_id=TENANT, actor_id=CASHIER, request_id=out.id,
            payload=CompleteRequest(
                remarks="only one line",
                lines=[LineReceipt(line_id=line_ids[0], received_qty=10)],  # line 1 untouched
            ),
        )


async def test_branch_transfer_requires_destination():
    svc, _ = _svc()
    with pytest.raises(BusinessRuleError):
        await svc.create(tenant_id=TENANT, user_id=CASHIER, payload=OrderRequestCreate(
            branch_id=BRANCH, purpose="branch_transfer",
            lines=[OrderRequestLineCreate(product_id=P1, requested_qty=1)],
        ))


async def test_branch_transfer_issue_goes_in_transit():
    repo = FakeRepo()
    svc = OrderRequestService(repo, FakeAudit())
    dest = uuid.uuid4()
    out = await svc.create(tenant_id=TENANT, user_id=CASHIER, payload=OrderRequestCreate(
        branch_id=BRANCH, destination_branch_id=dest, purpose="branch_transfer", comments="move it",
        lines=[OrderRequestLineCreate(product_id=P1, requested_qty=4)],
    ))
    assert out.destination_branch_id == dest
    line_id = out.lines[0].id
    await svc.approve(tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
                      payload=ApproveRequest(lines=[LineApproval(line_id=line_id, approved_qty=4)]))
    # Approval reserved the stock at the source.
    assert len(repo.reserved) == 1
    issued = await svc.issue(tenant_id=TENANT, actor_id=ADMIN, request_id=out.id)
    # A transfer goes ISSUED -> IN_TRANSIT (destination credited only at receipt).
    assert issued.status == S.IN_TRANSIT
    assert len(repo.transfers) == 1 and repo.issued == []
    pid, qty, src, dst = repo.transfers[0]
    assert pid == P1 and src == BRANCH and dst == dest and float(qty) == 4
    # Ledger captured reserved + consumed + issued events.
    events = {f["event"] for f in repo.ledger}
    assert {"reserved", "consumed", "issued"}.issubset(events)


async def test_branch_transfer_receive_credits_destination():
    repo = FakeRepo()
    svc = OrderRequestService(repo, FakeAudit())
    dest = uuid.uuid4()
    out = await svc.create(tenant_id=TENANT, user_id=CASHIER, payload=OrderRequestCreate(
        branch_id=BRANCH, destination_branch_id=dest, purpose="branch_transfer", comments="move it",
        lines=[OrderRequestLineCreate(product_id=P1, requested_qty=4)],
    ))
    line_id = out.lines[0].id
    await svc.approve(tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
                      payload=ApproveRequest(lines=[LineApproval(line_id=line_id, approved_qty=4)]))
    await svc.issue(tenant_id=TENANT, actor_id=ADMIN, request_id=out.id)
    from app.order_requests.schemas import ReceiveRequest
    received = await svc.receive(
        tenant_id=TENANT, actor_id=ADMIN, request_id=out.id,
        payload=ReceiveRequest(remarks="got 3, 1 missing",
                               lines=[LineReceipt(line_id=line_id, received_qty=3, missing_qty=1)]),
    )
    assert received.status == S.RECEIVED
    # Destination credited the 3 good units only (1 missing in transit).
    assert len(repo.received_credits) == 1
    pid, dst, recv, dmg = repo.received_credits[0]
    assert pid == P1 and dst == dest and float(recv) == 3 and float(dmg) == 0
