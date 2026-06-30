"""Data access for order requests / stock transfers: headers/lines/audit, filtered
history, dashboards, reservations (hold/consume/release), issue-time inventory
movement, and the immutable transfer ledger. All queries are tenant-scoped by RLS;
the service adds branch-user vs admin visibility on top.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Branch,
    Inventory,
    Product,
    RequestAudit,
    RequestHeader,
    RequestLine,
    StockMovement,
    StockTransferLedger,
    User,
    UserWarehouseAccess,
    Warehouse,
)
from app.repositories.reservation_repo import ReservationRepository


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")


class OrderRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reservations = ReservationRepository(session)

    async def next_request_number(self, tenant_id: uuid.UUID) -> str:
        return await self.session.scalar(
            text("SELECT next_request_number(CAST(:t AS uuid))"), {"t": str(tenant_id)}
        )

    async def user_branch_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        """Warehouses a user is explicitly scoped to. Empty set = unrestricted (all branches)."""
        res = await self.session.execute(
            select(UserWarehouseAccess.warehouse_id).where(UserWarehouseAccess.user_id == user_id)
        )
        return {wid for (wid,) in res.all()}

    # ------------------------------- writes ---------------------------- #
    async def create(
        self, *, tenant_id: uuid.UUID, request_number: str, branch_id: uuid.UUID,
        requested_by: uuid.UUID, purpose: str, comments: str | None, lines: list[dict],
        destination_branch_id: uuid.UUID | None = None, status: str = "pending",
    ) -> RequestHeader:
        header = RequestHeader(
            tenant_id=tenant_id, request_number=request_number, branch_id=branch_id,
            destination_branch_id=destination_branch_id,
            requested_by=requested_by, purpose=purpose, status=status, comments=comments,
        )
        self.session.add(header)
        await self.session.flush()
        for ln in lines:
            self.session.add(RequestLine(
                tenant_id=tenant_id, request_id=header.id, product_id=ln["product_id"],
                requested_qty=_d(ln["requested_qty"]), remarks=ln.get("remarks"),
            ))
        await self.session.flush()
        await self.session.refresh(header)
        return header

    async def get(self, request_id: uuid.UUID) -> RequestHeader | None:
        return await self.session.scalar(select(RequestHeader).where(RequestHeader.id == request_id))

    async def get_for_update(self, request_id: uuid.UUID) -> RequestHeader | None:
        """Row-locked fetch (SELECT ... FOR UPDATE) so concurrent state transitions on the
        same request serialise — prevents e.g. a double-issue that would deduct stock twice."""
        return await self.session.scalar(
            select(RequestHeader).where(RequestHeader.id == request_id).with_for_update()
        )

    async def find_by_number(self, request_number: str) -> RequestHeader | None:
        """Resolve a human-facing request number (REQ-YYYY-00001) to its header."""
        return await self.session.scalar(
            select(RequestHeader).where(RequestHeader.request_number == request_number.strip())
        )

    async def add_audit(
        self, *, tenant_id: uuid.UUID, request_id: uuid.UUID, user_id: uuid.UUID | None,
        action: str, old_status: str | None, new_status: str | None,
    ) -> None:
        self.session.add(RequestAudit(
            tenant_id=tenant_id, request_id=request_id, user_id=user_id,
            action=action, old_status=old_status, new_status=new_status,
        ))
        await self.session.flush()

    async def audit_trail(self, request_id: uuid.UUID) -> list[RequestAudit]:
        res = await self.session.execute(
            select(RequestAudit).where(RequestAudit.request_id == request_id)
            .order_by(RequestAudit.created_at)
        )
        return list(res.scalars().all())

    # --------------------------- reservations -------------------------- #
    async def reserve_line(
        self, *, tenant_id: uuid.UUID, line: RequestLine, source_id: uuid.UUID,
        qty: Decimal, user_id: uuid.UUID,
    ) -> str | None:
        """Hold `qty` of the line's product at the source location (on approval). Returns
        an error string if AVAILABLE stock is insufficient, else None."""
        if qty <= 0:
            return None
        inv = await self.session.scalar(
            select(Inventory).where(
                Inventory.product_id == line.product_id, Inventory.warehouse_id == source_id
            ).with_for_update()
        )
        available = (
            (inv.qty_on_hand - inv.qty_reserved - inv.qty_damaged) if inv else Decimal("0")
        )
        if inv is None or available < qty:
            return (
                f"Insufficient available stock for product {line.product_id} "
                f"(available {_f(available):g}, need {_f(qty):g})"
            )
        await self.reservations.reserve(
            tenant_id=tenant_id, inv=inv, qty=qty, reference_id=line.id, user_id=user_id
        )
        return None

    async def release_reservations(
        self, *, tenant_id: uuid.UUID, lines: list[RequestLine], user_id: uuid.UUID
    ) -> None:
        """Release every active hold for the request's lines (cancel / reject)."""
        for line in lines:
            res = await self.reservations.active_for(line.id)
            if res is None:
                continue
            inv = await self.session.scalar(
                select(Inventory).where(
                    Inventory.product_id == res.product_id, Inventory.warehouse_id == res.warehouse_id
                ).with_for_update()
            )
            if inv is None:
                res.status = "released"
                res.released_at = dt.datetime.now(dt.UTC)
                continue
            await self.reservations.release(
                tenant_id=tenant_id, inv=inv, reservation=res, user_id=user_id
            )

    async def issue_line(
        self, *, tenant_id: uuid.UUID, line: RequestLine, branch_id: uuid.UUID,
        qty: Decimal, user_id: uuid.UUID, request_id: uuid.UUID,
    ) -> str | None:
        """Consume the line's reservation and deduct `qty` from the source location,
        recording an 'issue' movement. Accumulates issued_qty (supports partial issue).
        Returns an error string if on-hand is insufficient, else None."""
        if qty <= 0:
            return None
        inv = await self.session.scalar(
            select(Inventory).where(
                Inventory.product_id == line.product_id, Inventory.warehouse_id == branch_id
            ).with_for_update()
        )
        on_hand = inv.qty_on_hand if inv else Decimal("0")
        if inv is None or on_hand < qty:
            return f"Insufficient stock for product {line.product_id} (on hand {_f(on_hand):g}, need {_f(qty):g})"
        res = await self.reservations.active_for(line.id)
        if res is not None:
            await self.reservations.consume(
                tenant_id=tenant_id, inv=inv, reservation=res, qty=qty, user_id=user_id
            )
        inv.qty_on_hand = on_hand - qty
        inv.version = (inv.version or 0) + 1
        self.session.add(StockMovement(
            tenant_id=tenant_id, product_id=line.product_id, warehouse_id=branch_id,
            movement_type="issue", quantity=-qty, reference_type="order_request",
            reference_id=request_id, reason="Order request issue", user_id=user_id,
        ))
        line.issued_qty = _d(line.issued_qty) + qty
        await self.session.flush()
        return None

    async def transfer_line(
        self, *, tenant_id: uuid.UUID, line: RequestLine, source_id: uuid.UUID,
        dest_id: uuid.UUID, qty: Decimal, user_id: uuid.UUID, request_id: uuid.UUID,
    ) -> str | None:
        """Issue a transfer: consume the line's reservation and DEBIT the source. The stock
        is now in transit — the destination is credited only at receipt (receive_line), so
        missing/damaged units never reach it. Accumulates issued_qty (supports partial issue)."""
        if qty <= 0:
            return None
        src = await self.session.scalar(
            select(Inventory).where(
                Inventory.product_id == line.product_id, Inventory.warehouse_id == source_id
            ).with_for_update()
        )
        if src is None or src.qty_on_hand < qty:
            on_hand = src.qty_on_hand if src else Decimal("0")
            return (
                f"Insufficient stock for product {line.product_id} at the source "
                f"(on hand {_f(on_hand):g}, need {_f(qty):g})"
            )
        res = await self.reservations.active_for(line.id)
        if res is not None:
            await self.reservations.consume(
                tenant_id=tenant_id, inv=src, reservation=res, qty=qty, user_id=user_id
            )
        src.qty_on_hand = src.qty_on_hand - qty
        src.version = (src.version or 0) + 1
        self.session.add(StockMovement(
            tenant_id=tenant_id, product_id=line.product_id, warehouse_id=source_id,
            movement_type="transfer_out", quantity=-qty, reference_type="order_request",
            reference_id=request_id, from_warehouse_id=source_id, to_warehouse_id=dest_id,
            reason="Order request transfer (issued)", user_id=user_id,
        ))
        line.issued_qty = _d(line.issued_qty) + qty
        await self.session.flush()
        return None

    async def receive_line(
        self, *, tenant_id: uuid.UUID, line: RequestLine, dest_id: uuid.UUID,
        received: Decimal, damaged: Decimal, user_id: uuid.UUID, request_id: uuid.UUID,
    ) -> None:
        """Credit a transfer's destination at receipt: good units to on-hand, damaged units
        to the damaged bucket. Missing units are a transit loss (credited nowhere). Quantities
        are DELTAS (supports correcting/repeated receipts). Creates the dest row if needed."""
        if received == 0 and damaged == 0:
            return
        inv = await self.session.scalar(
            select(Inventory).where(
                Inventory.product_id == line.product_id, Inventory.warehouse_id == dest_id
            ).with_for_update()
        )
        if inv is None:
            inv = Inventory(
                tenant_id=tenant_id, product_id=line.product_id, warehouse_id=dest_id,
                qty_on_hand=Decimal("0"), qty_reserved=Decimal("0"),
                qty_damaged=Decimal("0"), version=0,
            )
            self.session.add(inv)
            await self.session.flush()
        if received != 0:
            inv.qty_on_hand = inv.qty_on_hand + received
            self.session.add(StockMovement(
                tenant_id=tenant_id, product_id=line.product_id, warehouse_id=dest_id,
                movement_type="transfer_in", quantity=received, reference_type="order_request",
                reference_id=request_id, to_warehouse_id=dest_id,
                reason="Order request transfer (received)", user_id=user_id,
            ))
        if damaged != 0:
            inv.qty_damaged = (inv.qty_damaged or Decimal("0")) + damaged
            self.session.add(StockMovement(
                tenant_id=tenant_id, product_id=line.product_id, warehouse_id=dest_id,
                movement_type="damage", quantity=damaged, reference_type="order_request",
                reference_id=request_id, to_warehouse_id=dest_id,
                reason="Order request transfer (damaged in transit)", user_id=user_id,
            ))
        inv.version = (inv.version or 0) + 1
        await self.session.flush()

    # --------------------------- transfer ledger ----------------------- #
    async def add_transfer_ledger(self, **fields) -> None:
        """Append one immutable snapshot row (no UPDATE/DELETE grant on the table)."""
        self.session.add(StockTransferLedger(**fields))
        await self.session.flush()

    async def transfer_ledger(self, request_id: uuid.UUID) -> list[StockTransferLedger]:
        res = await self.session.execute(
            select(StockTransferLedger).where(StockTransferLedger.request_id == request_id)
            .order_by(StockTransferLedger.created_at)
        )
        return list(res.scalars().all())

    # ------------------------------- reads ----------------------------- #
    async def list_requests(
        self, *, requested_by: uuid.UUID | None = None, branch_id: uuid.UUID | None = None,
        status: str | None = None, purpose: str | None = None,
        date_from: dt.date | None = None, date_to: dt.date | None = None,
        product_id: uuid.UUID | None = None, limit: int = 100,
    ) -> list[RequestHeader]:
        stmt = select(RequestHeader)
        if requested_by:
            stmt = stmt.where(RequestHeader.requested_by == requested_by)
        if branch_id:
            stmt = stmt.where(RequestHeader.branch_id == branch_id)
        if status:
            stmt = stmt.where(RequestHeader.status == status)
        if purpose:
            stmt = stmt.where(RequestHeader.purpose == purpose)
        if date_from:
            stmt = stmt.where(func.date(RequestHeader.requested_date) >= date_from)
        if date_to:
            stmt = stmt.where(func.date(RequestHeader.requested_date) <= date_to)
        if product_id:
            stmt = stmt.where(
                RequestHeader.id.in_(select(RequestLine.request_id).where(RequestLine.product_id == product_id))
            )
        stmt = stmt.order_by(RequestHeader.requested_date.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    # enrichment maps for building response models
    async def product_index(self, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
        if not product_ids:
            return {}
        res = await self.session.execute(
            select(Product.id, Product.sku, Product.name).where(Product.id.in_(product_ids))
        )
        return {pid: (sku, name) for pid, sku, name in res.all()}

    async def warehouse_names(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not ids:
            return {}
        res = await self.session.execute(select(Warehouse.id, Warehouse.name).where(Warehouse.id.in_(ids)))
        return {wid: name for wid, name in res.all()}

    async def location_index(
        self, ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[str, uuid.UUID | None, str | None]]:
        """warehouse_id -> (location_name, branch_id, branch_name). The branch is the
        location's warehouses.branch_id; powers the source/dest branch+location output."""
        ids = [i for i in ids if i]
        if not ids:
            return {}
        res = await self.session.execute(
            select(Warehouse.id, Warehouse.name, Warehouse.branch_id, Branch.name)
            .outerjoin(Branch, Branch.id == Warehouse.branch_id)
            .where(Warehouse.id.in_(ids))
        )
        return {wid: (wname, bid, bname) for wid, wname, bid, bname in res.all()}

    async def user_names(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        res = await self.session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
        return {uid: name for uid, name in res.all()}

    # ------------------------------ dashboards ------------------------- #
    async def _status_counts(self, requested_by: uuid.UUID | None) -> dict[str, int]:
        stmt = select(RequestHeader.status, func.count()).group_by(RequestHeader.status)
        if requested_by:
            stmt = stmt.where(RequestHeader.requested_by == requested_by)
        res = await self.session.execute(stmt)
        return {status: int(n) for status, n in res.all()}

    async def issued_today_count(self) -> int:
        return int(await self.session.scalar(
            select(func.count()).select_from(RequestHeader)
            .where(RequestHeader.status.in_(["issued", "in_transit"]),
                   func.date(RequestHeader.issued_date) == dt.date.today())
        ) or 0)

    async def requests_by_branch(self) -> list[dict]:
        res = await self.session.execute(
            select(Warehouse.name, func.count(RequestHeader.id))
            .join(Warehouse, Warehouse.id == RequestHeader.branch_id)
            .group_by(Warehouse.name).order_by(func.count(RequestHeader.id).desc()).limit(50)
        )
        return [{"branch": name, "count": int(n)} for name, n in res.all()]

    async def most_requested_items(self, limit: int = 10) -> list[dict]:
        total = func.sum(RequestLine.requested_qty)
        res = await self.session.execute(
            select(Product.sku, Product.name, total)
            .join(Product, Product.id == RequestLine.product_id)
            .group_by(Product.sku, Product.name).order_by(total.desc()).limit(limit)
        )
        return [{"sku": sku, "name": name, "total_requested": _f(qty)} for sku, name, qty in res.all()]
