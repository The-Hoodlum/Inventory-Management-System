"""Order-request / stock-transfer orchestration.

Lifecycle: create (draft|pending) -> submit -> approve (HOLD: reserve stock) ->
issue (CONSUME: move/deduct stock, possibly partial) -> receive (reconcile
received/missing/damaged/extra) -> complete. Cancel/reject RELEASE held stock.

Inventory is held on approval, physically moved on issue, and every stock-affecting
event appends an immutable row to the transfer ledger. Every status transition is
audited (both request_audit and the global audit log). Tenant-scoped via RLS.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.core.exceptions import BusinessRuleError, NotFoundError, PermissionDeniedError
from app.core.permissions import P
from app.order_requests.domain import status as S
from app.order_requests.repository import OrderRequestRepository
from app.order_requests.schemas import (
    ApproveRequest,
    AuditEntryOut,
    CancelRequest,
    CompleteRequest,
    IssueRequest,
    OrderRequestCreate,
    OrderRequestLineOut,
    OrderRequestOut,
    ReceiveRequest,
    RejectRequest,
    TransferLedgerEntryOut,
)
from app.repositories.audit_repo import AuditRepository

_RECONCILE_MSG = (
    "Receipt quantities do not reconcile. Received + Missing + Damaged must equal "
    "Issued + Extra."
)


def _opt_f(v) -> float | None:
    """Decimal|None -> float|None (nullable receipt-reconciliation quantities)."""
    return float(v) if v is not None else None


def _f(v) -> float:
    return float(v) if v is not None else 0.0


class OrderRequestService:
    def __init__(self, repo: OrderRequestRepository, audit: AuditRepository) -> None:
        self.repo = repo
        self.audit = audit

    # ------------------------------- create ---------------------------- #
    async def create(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: OrderRequestCreate,
        user_permissions: set[str] | None = None, user_branch_ids: set[uuid.UUID] | None = None,
    ) -> OrderRequestOut:
        user_permissions = user_permissions or set()
        user_branch_ids = user_branch_ids or set()
        # The explicit inter-location move types must name a destination.
        if payload.purpose in S.TRANSFER_TYPES and payload.destination_branch_id is None:
            raise BusinessRuleError("A transfer needs a destination location.")
        # Validate that the chosen locations exist (a transfer also needs a destination).
        loc_ids = [payload.branch_id]
        if payload.destination_branch_id is not None:
            loc_ids.append(payload.destination_branch_id)
        locs = await self.repo.location_index(loc_ids)
        if payload.branch_id not in locs:
            raise NotFoundError("Source location not found")
        if payload.destination_branch_id is not None and payload.destination_branch_id not in locs:
            raise NotFoundError("Destination location not found")

        # Role/branch gate (FIX 4): a restock/sales request goes to the user's OWN branch and
        # needs only order_request.create. A managed inter-location transfer, or a request
        # sending stock to a branch the user isn't scoped to, needs order_request.transfer.
        dest_branch = locs[payload.destination_branch_id][1] if payload.destination_branch_id else None
        sends_outside = bool(user_branch_ids) and dest_branch is not None and dest_branch not in user_branch_ids
        if payload.purpose in S.TRANSFER_TYPES or sends_outside:
            if P.ORDER_REQUEST_TRANSFER not in user_permissions:
                raise PermissionDeniedError(
                    "You need the stock-transfer permission to raise an inter-location transfer; "
                    "a restock request must be for your own location."
                )

        new_status = S.PENDING if payload.submit else S.DRAFT
        number = await self.repo.next_request_number(tenant_id)
        header = await self.repo.create(
            tenant_id=tenant_id, request_number=number, branch_id=payload.branch_id,
            destination_branch_id=payload.destination_branch_id,
            requested_by=user_id, purpose=payload.purpose, comments=payload.comments,
            lines=[ln.model_dump() for ln in payload.lines], status=new_status,
        )
        await self._audit(tenant_id, header.id, user_id, "created", None, new_status)
        return await self._to_out(header)

    # ------------------------------- submit ---------------------------- #
    async def submit(
        self, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, request_id: uuid.UUID, is_admin: bool
    ) -> OrderRequestOut:
        header = await self._require(request_id, lock=True)
        if not is_admin and header.requested_by != actor_id:
            raise NotFoundError("Order request not found")
        if not S.can_transition(header.status, S.PENDING):
            raise BusinessRuleError(f"Only a draft can be submitted (status={header.status}).")
        header.status = S.PENDING
        await self.repo.session.flush()
        await self._audit(tenant_id, header.id, actor_id, "submitted", S.DRAFT, S.PENDING)
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
        # HOLD the approved quantity at the source location (reservations).
        locs = await self._locs(header)
        for line in header.lines:
            qty = Decimal(str(line.approved_qty or 0))
            if qty <= 0:
                continue
            err = await self.repo.reserve_line(
                tenant_id=tenant_id, line=line, source_id=header.branch_id, qty=qty, user_id=actor_id
            )
            if err:
                raise BusinessRuleError(err)  # rolls back the whole approval (one transaction)
            await self._ledger(header, line, "reserved", actor_id, locs)
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
        self, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, request_id: uuid.UUID,
        payload: IssueRequest | None = None,
    ) -> OrderRequestOut:
        header = await self._require(request_id, lock=True)
        prev_status = header.status
        if not S.can_transition(header.status, S.ISSUED):
            raise BusinessRuleError(f"Only approved requests can be issued (status={header.status}).")
        is_transfer = header.destination_branch_id is not None
        wanted = {ln.line_id: ln.issue_qty for ln in (payload.lines if payload else [])}
        locs = await self._locs(header)
        pairs: list[tuple[float, float]] = []
        for line in header.lines:
            approved = Decimal(str(line.approved_qty or 0))
            already = Decimal(str(line.issued_qty or 0))
            remaining = approved - already
            # Default: issue everything still owed; otherwise the requested amount, capped.
            req = Decimal(str(wanted[line.id])) if line.id in wanted else remaining
            qty = max(Decimal("0"), min(req, remaining))
            if qty > 0:
                if is_transfer:
                    err = await self.repo.transfer_line(
                        tenant_id=tenant_id, line=line, source_id=header.branch_id,
                        dest_id=header.destination_branch_id, qty=qty, user_id=actor_id,
                        request_id=header.id,
                    )
                else:
                    err = await self.repo.issue_line(
                        tenant_id=tenant_id, line=line, branch_id=header.branch_id, qty=qty,
                        user_id=actor_id, request_id=header.id,
                    )
                if err:
                    raise BusinessRuleError(err)  # rolls back the whole issue (one transaction)
                await self._ledger(header, line, "consumed", actor_id, locs)
                await self._ledger(header, line, "issued", actor_id, locs)
            pairs.append((float(line.issued_qty or 0), float(line.approved_qty or 0)))
        if sum(i for i, _ in pairs) <= 0:
            raise BusinessRuleError("Nothing to issue (no approved quantity outstanding).")
        outcome = S.issue_outcome(pairs, is_transfer=is_transfer)
        header.status = outcome
        header.issued_by = actor_id
        header.issued_date = dt.datetime.now(dt.UTC)
        await self.repo.session.flush()
        await self._audit(tenant_id, header.id, actor_id, "issued", prev_status, outcome)
        return await self._to_out(header)

    # ------------------------------ receive ---------------------------- #
    async def receive(
        self, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, request_id: uuid.UUID,
        payload: ReceiveRequest,
    ) -> OrderRequestOut:
        """Capture a receipt: per-line received/missing/damaged/extra. Each submitted line
        must reconcile (received + missing + damaged = issued + extra); the request becomes
        RECEIVED once every issued line is accounted, else PARTIALLY_RECEIVED."""
        header = await self._require(request_id, lock=True)
        if not S.can_transition(header.status, S.RECEIVED):
            raise BusinessRuleError(
                f"Only an issued / in-transit transfer can be received (status={header.status})."
            )
        receipts = {r.line_id: r for r in payload.lines}
        await self._record_receipts(tenant_id=tenant_id, header=header, receipts=receipts, actor_id=actor_id)
        accounted = [
            (
                _f(line.received_qty) + _f(line.missing_qty) + _f(line.damaged_qty)
                if line.received_qty is not None else 0.0,
                _f(line.issued_qty) + _f(line.extra_qty),
            )
            for line in header.lines if float(line.issued_qty or 0) > 0
        ]
        outcome = S.receive_outcome(accounted) if accounted else S.RECEIVED
        prev = header.status
        header.status = outcome
        header.received_by = actor_id
        header.received_date = dt.datetime.now(dt.UTC)
        if payload.remarks:
            header.completion_remarks = payload.remarks
        await self.repo.session.flush()
        await self._audit(tenant_id, header.id, actor_id, "received", prev, outcome)
        return await self._to_out(header)

    # ------------------------------ cancel ----------------------------- #
    async def cancel(
        self, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, request_id: uuid.UUID,
        is_admin: bool, payload: CancelRequest,
    ) -> OrderRequestOut:
        header = await self._require(request_id, lock=True)
        # A request can be cancelled by its own requester or by an admin/approver,
        # and only before any stock has been issued (draft/pending/approved).
        if not is_admin and header.requested_by != actor_id:
            raise NotFoundError("Order request not found")  # don't leak others' requests
        if not S.can_transition(header.status, S.CANCELLED):
            raise BusinessRuleError(
                f"Cannot cancel a request in status {header.status} (only before it is issued)."
            )
        # RELEASE any stock held by approval back to available.
        if header.status in S.APPROVED_STATES:
            locs = await self._locs(header)
            await self.repo.release_reservations(
                tenant_id=tenant_id, lines=list(header.lines), user_id=actor_id
            )
            for line in header.lines:
                await self._ledger(header, line, "released", actor_id, locs)
        prev = header.status
        header.status = S.CANCELLED
        if payload.reason:
            header.comments = payload.reason
        await self.repo.session.flush()
        await self._audit(tenant_id, header.id, actor_id, "cancelled", prev, S.CANCELLED)
        return await self._to_out(header)

    # ----------------------------- complete ---------------------------- #
    async def complete(
        self, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, request_id: uuid.UUID,
        payload: CompleteRequest,
    ) -> OrderRequestOut:
        """Confirm receipt and close a transfer. Accepts an optional per-line receipt (so a
        simple requisition can receive + close in one step). Blocked unless every issued
        line reconciles (received + missing + damaged = issued + extra)."""
        header = await self._require(request_id, lock=True)
        if not S.can_transition(header.status, S.COMPLETED):
            raise BusinessRuleError(
                f"Only a received / issued transfer can be completed (status={header.status})."
            )
        prev = header.status
        if payload.lines:
            await self._record_receipts(
                tenant_id=tenant_id, header=header,
                receipts={r.line_id: r for r in payload.lines}, actor_id=actor_id,
            )
            if header.received_by is None:
                header.received_by = actor_id
                header.received_date = dt.datetime.now(dt.UTC)
        # Completion requires every issued line to be reconciled.
        for line in header.lines:
            if float(line.issued_qty or 0) <= 0:
                continue
            if line.received_qty is None or not S.is_balanced(
                _f(line.issued_qty), _f(line.extra_qty),
                _f(line.received_qty), _f(line.missing_qty), _f(line.damaged_qty),
            ):
                raise BusinessRuleError(_RECONCILE_MSG)
        header.status = S.COMPLETED
        header.completed_by = actor_id
        header.completed_date = dt.datetime.now(dt.UTC)
        header.completion_remarks = payload.remarks
        await self.repo.session.flush()
        await self._audit(tenant_id, header.id, actor_id, "completed", prev, S.COMPLETED)
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

    async def get_by_number(self, request_number: str) -> OrderRequestOut | None:
        """Resolve a request by its human number (for the chat approve/reject flow)."""
        header = await self.repo.find_by_number(request_number)
        return await self._to_out(header) if header else None

    async def audit_trail(self, *, request_id: uuid.UUID, viewer_id: uuid.UUID, is_admin: bool) -> list[AuditEntryOut]:
        header = await self._require(request_id)
        if not is_admin and header.requested_by != viewer_id:
            raise NotFoundError("Order request not found")
        rows = await self.repo.audit_trail(request_id)
        return [AuditEntryOut(action=r.action, old_status=r.old_status, new_status=r.new_status,
                              user_id=r.user_id, created_at=r.created_at) for r in rows]

    async def ledger(
        self, *, request_id: uuid.UUID, viewer_id: uuid.UUID, is_admin: bool
    ) -> list[TransferLedgerEntryOut]:
        header = await self._require(request_id)
        if not is_admin and header.requested_by != viewer_id:
            raise NotFoundError("Order request not found")
        rows = await self.repo.transfer_ledger(request_id)
        prod = await self.repo.product_index([r.product_id for r in rows])
        locs = await self.repo.location_index(
            [i for r in rows for i in (r.source_location_id, r.dest_location_id) if i]
        )

        def _loc(i):
            return locs.get(i, (None, None, None))

        out: list[TransferLedgerEntryOut] = []
        for r in rows:
            sku, name = prod.get(r.product_id, (None, None))
            out.append(TransferLedgerEntryOut(
                id=r.id, event=r.event, request_number=r.request_number, product_id=r.product_id,
                sku=sku, name=name,
                qty_requested=_opt_f(r.qty_requested), qty_approved=_opt_f(r.qty_approved),
                qty_issued=_opt_f(r.qty_issued), qty_received=_opt_f(r.qty_received),
                qty_missing=_opt_f(r.qty_missing), qty_damaged=_opt_f(r.qty_damaged),
                qty_extra=_opt_f(r.qty_extra),
                source_location_name=_loc(r.source_location_id)[0],
                source_branch_name=_loc(r.source_location_id)[2],
                dest_location_name=_loc(r.dest_location_id)[0],
                dest_branch_name=_loc(r.dest_location_id)[2],
                transfer_type=r.transfer_type, reason=r.reason, created_at=r.created_at,
            ))
        return out

    async def dashboard(self, *, viewer_id: uuid.UUID, is_admin: bool) -> dict:
        if is_admin:
            counts = await self.repo._status_counts(None)
            return {
                "scope": "admin",
                "pending": counts.get(S.PENDING, 0),
                "approved": counts.get(S.APPROVED, 0) + counts.get(S.PARTIALLY_APPROVED, 0),
                "rejected": counts.get(S.REJECTED, 0),
                "issued": counts.get(S.ISSUED, 0) + counts.get(S.PARTIALLY_ISSUED, 0),
                "in_transit": counts.get(S.IN_TRANSIT, 0),
                "received": counts.get(S.RECEIVED, 0) + counts.get(S.PARTIALLY_RECEIVED, 0),
                "completed": counts.get(S.COMPLETED, 0),
                "cancelled": counts.get(S.CANCELLED, 0),
                "issued_today": await self.repo.issued_today_count(),
                "requests_by_branch": await self.repo.requests_by_branch(),
                "most_requested_items": await self.repo.most_requested_items(),
            }
        counts = await self.repo._status_counts(viewer_id)
        recent = await self.repo.list_requests(requested_by=viewer_id, status=S.IN_TRANSIT, limit=10)
        return {
            "scope": "branch",
            "my_pending": counts.get(S.PENDING, 0),
            "my_approved": counts.get(S.APPROVED, 0) + counts.get(S.PARTIALLY_APPROVED, 0),
            "my_rejected": counts.get(S.REJECTED, 0),
            "my_completed": counts.get(S.COMPLETED, 0),
            "my_recent_issued": [r.request_number for r in recent],
        }

    # ------------------------------ helpers ---------------------------- #
    @staticmethod
    def _apply_receipts(header, receipts: dict) -> None:
        """Write per-line received/missing/damaged/extra, enforcing the reconciliation
        invariant for each submitted line (uses the line's issued quantity)."""
        for line in header.lines:
            r = receipts.get(line.id)
            if r is None:
                continue
            received = r.received_qty if r.received_qty is not None else _f(line.received_qty)
            missing = r.missing_qty if r.missing_qty is not None else _f(line.missing_qty)
            damaged = r.damaged_qty if r.damaged_qty is not None else _f(line.damaged_qty)
            extra = r.extra_qty if r.extra_qty is not None else _f(line.extra_qty)
            if not S.is_balanced(_f(line.issued_qty), extra, received, missing, damaged):
                raise BusinessRuleError(_RECONCILE_MSG)
            line.received_qty = Decimal(str(received))
            line.missing_qty = Decimal(str(missing))
            line.damaged_qty = Decimal(str(damaged))
            line.extra_qty = Decimal(str(extra))

    async def _record_receipts(self, *, tenant_id, header, receipts: dict, actor_id) -> None:
        """Validate + persist per-line receipts and, for a transfer, CREDIT the destination
        with the receipt DELTA (good units to on-hand, damaged to the damaged bucket; missing
        is a transit loss). Appends a 'received' ledger row per submitted line."""
        is_transfer = header.destination_branch_id is not None
        prior = {ln.id: (_f(ln.received_qty), _f(ln.damaged_qty)) for ln in header.lines}
        self._apply_receipts(header, receipts)  # validates the reconciliation invariant
        locs = await self._locs(header)
        for line in header.lines:
            if line.id not in receipts:
                continue
            if is_transfer:
                d_received = _f(line.received_qty) - prior[line.id][0]
                d_damaged = _f(line.damaged_qty) - prior[line.id][1]
                await self.repo.receive_line(
                    tenant_id=tenant_id, line=line, dest_id=header.destination_branch_id,
                    received=Decimal(str(d_received)), damaged=Decimal(str(d_damaged)),
                    user_id=actor_id, request_id=header.id,
                )
            await self._ledger(header, line, "received", actor_id, locs)

    async def _locs(self, header) -> dict:
        ids = [i for i in [header.branch_id, header.destination_branch_id] if i]
        return await self.repo.location_index(ids)

    async def _ledger(self, header, line, event: str, actor_id: uuid.UUID, locs: dict) -> None:
        src = locs.get(header.branch_id, (None, None, None))
        dst = locs.get(header.destination_branch_id, (None, None, None)) if header.destination_branch_id else (None, None, None)
        await self.repo.add_transfer_ledger(
            tenant_id=header.tenant_id, request_id=header.id, request_number=header.request_number,
            line_id=line.id, product_id=line.product_id, event=event,
            qty_requested=line.requested_qty, qty_approved=line.approved_qty,
            qty_issued=line.issued_qty, qty_received=line.received_qty,
            qty_missing=line.missing_qty, qty_damaged=line.damaged_qty, qty_extra=line.extra_qty,
            source_branch_id=src[1], source_location_id=header.branch_id,
            dest_branch_id=dst[1], dest_location_id=header.destination_branch_id,
            transfer_type=header.purpose, reason=header.comments,
            requested_by=header.requested_by, approved_by=header.approved_by,
            issued_by=header.issued_by, received_by=header.received_by, created_by=actor_id,
        )

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
        locs = await self.repo.location_index(
            [i for i in [header.branch_id, header.destination_branch_id] if i]
        )
        users = await self.repo.user_names(
            [header.requested_by, header.approved_by, header.issued_by,
             header.received_by, header.completed_by]
        )
        return self._build_out(header, prod, locs, users)

    async def _to_out_many(self, headers: list) -> list[OrderRequestOut]:
        """List response: fetch all enrichment maps ONCE across every header (avoids the
        N+1 of resolving product/branch/user names per row)."""
        if not headers:
            return []
        product_ids = {ln.product_id for h in headers for ln in h.lines}
        loc_ids = {h.branch_id for h in headers} | {
            h.destination_branch_id for h in headers if h.destination_branch_id
        }
        user_ids = {
            uid for h in headers
            for uid in (h.requested_by, h.approved_by, h.issued_by, h.received_by, h.completed_by)
            if uid
        }
        prod = await self.repo.product_index(list(product_ids))
        locs = await self.repo.location_index(list(loc_ids))
        users = await self.repo.user_names(list(user_ids))
        return [self._build_out(h, prod, locs, users) for h in headers]

    @staticmethod
    def _build_out(header, prod: dict, locs: dict, users: dict) -> OrderRequestOut:
        """Map a header (+ prefetched lookups) to the response model. Pure."""
        src = locs.get(header.branch_id, (None, None, None))
        dst = (
            locs.get(header.destination_branch_id, (None, None, None))
            if header.destination_branch_id else (None, None, None)
        )
        lines = []
        for ln in header.lines:
            received = _opt_f(ln.received_qty)
            variance = (
                S.reconcile_variance(_f(ln.issued_qty), _f(ln.extra_qty),
                                     _f(ln.received_qty), _f(ln.missing_qty), _f(ln.damaged_qty))
                if received is not None else 0.0
            )
            lines.append(OrderRequestLineOut(
                id=ln.id, product_id=ln.product_id,
                sku=prod.get(ln.product_id, (None, None))[0],
                name=prod.get(ln.product_id, (None, None))[1],
                requested_qty=float(ln.requested_qty), approved_qty=float(ln.approved_qty),
                issued_qty=float(ln.issued_qty),
                outstanding_qty=S.outstanding(float(ln.requested_qty), float(ln.issued_qty)),
                received_qty=received, missing_qty=_opt_f(ln.missing_qty),
                damaged_qty=_opt_f(ln.damaged_qty), extra_qty=_opt_f(ln.extra_qty),
                variance=variance, balanced=abs(variance) < 1e-9,
                remarks=ln.remarks,
            ))
        return OrderRequestOut(
            id=header.id, request_number=header.request_number,
            transfer_type=header.purpose, purpose=header.purpose, status=header.status,
            reason=header.comments,
            branch_id=header.branch_id, branch_name=src[0],
            destination_branch_id=header.destination_branch_id, destination_branch_name=dst[0],
            source_location_id=header.branch_id, source_location_name=src[0],
            source_branch_id=src[1], source_branch_name=src[2],
            dest_location_id=header.destination_branch_id, dest_location_name=dst[0],
            dest_branch_id=dst[1], dest_branch_name=dst[2],
            requested_by=header.requested_by, requester_name=users.get(header.requested_by),
            requested_date=header.requested_date,
            approved_by=header.approved_by, approved_date=header.approved_date,
            issued_by=header.issued_by, issued_date=header.issued_date,
            received_by=header.received_by, receiver_name=users.get(header.received_by),
            received_date=header.received_date,
            completed_by=header.completed_by, completer_name=users.get(header.completed_by),
            completed_date=header.completed_date, completion_remarks=header.completion_remarks,
            comments=header.comments, lines=lines,
        )
