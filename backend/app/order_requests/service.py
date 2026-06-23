"""Order-request orchestration: create (branch user) -> approve/partial/reject (admin)
-> issue (admin, deducts inventory). Every transition is audited (both the request_audit
trail and the global audit log). Inventory changes happen ONLY at issue time.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.order_requests.domain import status as S
from app.order_requests.repository import OrderRequestRepository
from app.order_requests.schemas import (
    ApproveRequest,
    AuditEntryOut,
    OrderRequestCreate,
    OrderRequestLineOut,
    OrderRequestOut,
    RejectRequest,
)
from app.repositories.audit_repo import AuditRepository


class OrderRequestService:
    def __init__(self, repo: OrderRequestRepository, audit: AuditRepository) -> None:
        self.repo = repo
        self.audit = audit

    # ------------------------------- create ---------------------------- #
    async def create(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: OrderRequestCreate
    ) -> OrderRequestOut:
        # Branch users may only raise requests for a branch they're scoped to
        # (no grants = unrestricted). Covers both the web API and the assistant path.
        branch_ids = await self.repo.user_branch_ids(user_id)
        if branch_ids and payload.branch_id not in branch_ids:
            raise BusinessRuleError("You can only raise requests for your assigned branch.")
        number = await self.repo.next_request_number(tenant_id)
        header = await self.repo.create(
            tenant_id=tenant_id, request_number=number, branch_id=payload.branch_id,
            requested_by=user_id, purpose=payload.purpose, comments=payload.comments,
            lines=[ln.model_dump() for ln in payload.lines],
        )
        await self._audit(tenant_id, header.id, user_id, "created", None, S.PENDING)
        return await self._to_out(header)

    # ------------------------------ approve ---------------------------- #
    async def approve(
        self, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, request_id: uuid.UUID, payload: ApproveRequest
    ) -> OrderRequestOut:
        header = await self._require(request_id, lock=True)
        if header.status != S.PENDING:
            raise BusinessRuleError(f"Only pending requests can be approved (status={header.status}).")
        approvals = {a.line_id: a.approved_qty for a in payload.lines}
        pairs: list[tuple[float, float]] = []
        for line in header.lines:
            approved = S.clamp_approved(approvals.get(line.id, 0.0), float(line.requested_qty))
            line.approved_qty = Decimal(str(approved))
            pairs.append((approved, float(line.requested_qty)))
        outcome = S.approval_outcome(pairs)
        if outcome == S.REJECTED:
            raise BusinessRuleError("Nothing approved — use reject (with a reason) instead.")
        header.status = outcome
        header.approved_by = actor_id
        header.approved_date = dt.datetime.now(dt.UTC)
        if payload.comments:
            header.comments = payload.comments
        await self.repo.session.flush()
        await self._audit(tenant_id, header.id, actor_id, "approved", S.PENDING, outcome)
        return await self._to_out(header)

    # ------------------------------ reject ----------------------------- #
    async def reject(
        self, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, request_id: uuid.UUID, payload: RejectRequest
    ) -> OrderRequestOut:
        header = await self._require(request_id, lock=True)
        if not S.can_transition(header.status, S.REJECTED):
            raise BusinessRuleError(f"Cannot reject a request in status {header.status}.")
        header.status = S.REJECTED
        header.comments = payload.reason
        header.approved_by = actor_id
        header.approved_date = dt.datetime.now(dt.UTC)
        await self.repo.session.flush()
        await self._audit(tenant_id, header.id, actor_id, "rejected", S.PENDING, S.REJECTED)
        return await self._to_out(header)

    # ------------------------------- issue ----------------------------- #
    async def issue(
        self, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, request_id: uuid.UUID
    ) -> OrderRequestOut:
        header = await self._require(request_id, lock=True)
        prev_status = header.status
        if not S.can_transition(header.status, S.ISSUED):
            raise BusinessRuleError(f"Only approved requests can be issued (status={header.status}).")
        for line in header.lines:
            qty = Decimal(str(line.approved_qty or 0))
            if qty <= 0:
                continue
            err = await self.repo.issue_line(
                tenant_id=tenant_id, line=line, branch_id=header.branch_id, qty=qty,
                user_id=actor_id, request_id=header.id,
            )
            if err:
                raise BusinessRuleError(err)  # rolls back the whole issue (one transaction)
        header.status = S.ISSUED
        header.issued_by = actor_id
        header.issued_date = dt.datetime.now(dt.UTC)
        await self.repo.session.flush()
        await self._audit(tenant_id, header.id, actor_id, "issued", prev_status, S.ISSUED)
        return await self._to_out(header)

    # ------------------------------- reads ----------------------------- #
    async def get(self, *, request_id: uuid.UUID, viewer_id: uuid.UUID, is_admin: bool) -> OrderRequestOut:
        header = await self._require(request_id)
        if not is_admin and header.requested_by != viewer_id:
            raise NotFoundError("Order request not found")  # don't leak others' requests
        return await self._to_out(header)

    async def history(
        self, *, viewer_id: uuid.UUID, is_admin: bool, filters: dict
    ) -> list[OrderRequestOut]:
        if not is_admin:
            filters = {**filters, "requested_by": viewer_id}  # branch users see only their own
        headers = await self.repo.list_requests(**filters)
        return await self._to_out_many(headers)

    async def audit_trail(self, *, request_id: uuid.UUID, viewer_id: uuid.UUID, is_admin: bool) -> list[AuditEntryOut]:
        header = await self._require(request_id)
        if not is_admin and header.requested_by != viewer_id:
            raise NotFoundError("Order request not found")
        rows = await self.repo.audit_trail(request_id)
        return [AuditEntryOut(action=r.action, old_status=r.old_status, new_status=r.new_status,
                              user_id=r.user_id, created_at=r.created_at) for r in rows]

    async def dashboard(self, *, viewer_id: uuid.UUID, is_admin: bool) -> dict:
        if is_admin:
            counts = await self.repo._status_counts(None)
            return {
                "scope": "admin",
                "pending": counts.get(S.PENDING, 0),
                "approved": counts.get(S.APPROVED, 0) + counts.get(S.PARTIALLY_APPROVED, 0),
                "rejected": counts.get(S.REJECTED, 0),
                "issued": counts.get(S.ISSUED, 0),
                "issued_today": await self.repo.issued_today_count(),
                "requests_by_branch": await self.repo.requests_by_branch(),
                "most_requested_items": await self.repo.most_requested_items(),
            }
        counts = await self.repo._status_counts(viewer_id)
        recent = await self.repo.list_requests(requested_by=viewer_id, status=S.ISSUED, limit=10)
        return {
            "scope": "branch",
            "my_pending": counts.get(S.PENDING, 0),
            "my_approved": counts.get(S.APPROVED, 0) + counts.get(S.PARTIALLY_APPROVED, 0),
            "my_rejected": counts.get(S.REJECTED, 0),
            "my_recent_issued": [r.request_number for r in recent],
        }

    # ------------------------------ helpers ---------------------------- #
    async def _require(self, request_id: uuid.UUID, *, lock: bool = False) -> object:
        # lock=True row-locks the header so concurrent transitions serialise (no double-issue).
        header = await (self.repo.get_for_update(request_id) if lock else self.repo.get(request_id))
        if header is None:
            raise NotFoundError("Order request not found")
        return header

    async def _audit(self, tenant_id, request_id, user_id, action, old, new) -> None:
        await self.repo.add_audit(
            tenant_id=tenant_id, request_id=request_id, user_id=user_id,
            action=action, old_status=old, new_status=new,
        )
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action=f"order_request.{action}",
            entity_type="order_request", entity_id=request_id,
        )

    async def _to_out(self, header) -> OrderRequestOut:
        """Single-header response (create/approve/reject/issue paths)."""
        prod = await self.repo.product_index([ln.product_id for ln in header.lines])
        wh = await self.repo.warehouse_names([header.branch_id])
        users = await self.repo.user_names([header.requested_by, header.approved_by, header.issued_by])
        return self._build_out(header, prod, wh, users)

    async def _to_out_many(self, headers: list) -> list[OrderRequestOut]:
        """List response: fetch all enrichment maps ONCE across every header (avoids the
        N+1 of resolving product/branch/user names per row)."""
        if not headers:
            return []
        product_ids = {ln.product_id for h in headers for ln in h.lines}
        branch_ids = {h.branch_id for h in headers}
        user_ids = {uid for h in headers for uid in (h.requested_by, h.approved_by, h.issued_by) if uid}
        prod = await self.repo.product_index(list(product_ids))
        wh = await self.repo.warehouse_names(list(branch_ids))
        users = await self.repo.user_names(list(user_ids))
        return [self._build_out(h, prod, wh, users) for h in headers]

    @staticmethod
    def _build_out(header, prod: dict, wh: dict, users: dict) -> OrderRequestOut:
        """Map a header (+ prefetched name lookups) to the response model. Pure."""
        lines = [
            OrderRequestLineOut(
                id=ln.id, product_id=ln.product_id,
                sku=prod.get(ln.product_id, (None, None))[0],
                name=prod.get(ln.product_id, (None, None))[1],
                requested_qty=float(ln.requested_qty), approved_qty=float(ln.approved_qty),
                issued_qty=float(ln.issued_qty),
                outstanding_qty=S.outstanding(float(ln.requested_qty), float(ln.issued_qty)),
                remarks=ln.remarks,
            )
            for ln in header.lines
        ]
        return OrderRequestOut(
            id=header.id, request_number=header.request_number, branch_id=header.branch_id,
            branch_name=wh.get(header.branch_id), requested_by=header.requested_by,
            requester_name=users.get(header.requested_by), purpose=header.purpose, status=header.status,
            requested_date=header.requested_date, approved_by=header.approved_by,
            approved_date=header.approved_date, issued_by=header.issued_by, issued_date=header.issued_date,
            comments=header.comments, lines=lines,
        )
