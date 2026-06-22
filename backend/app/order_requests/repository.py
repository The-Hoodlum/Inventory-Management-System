"""Data access for order requests: headers/lines/audit, filtered history, dashboards,
and issue-time inventory deduction. All queries are tenant-scoped by RLS; the service
adds branch-user vs admin visibility on top.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Inventory,
    Product,
    RequestAudit,
    RequestHeader,
    RequestLine,
    StockMovement,
    User,
    Warehouse,
)


def _f(v) -> float:
    return float(v) if v is not None else 0.0


class OrderRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_request_number(self, tenant_id: uuid.UUID) -> str:
        return await self.session.scalar(
            text("SELECT next_request_number(CAST(:t AS uuid))"), {"t": str(tenant_id)}
        )

    # ------------------------------- writes ---------------------------- #
    async def create(
        self, *, tenant_id: uuid.UUID, request_number: str, branch_id: uuid.UUID,
        requested_by: uuid.UUID, purpose: str, comments: str | None, lines: list[dict],
    ) -> RequestHeader:
        header = RequestHeader(
            tenant_id=tenant_id, request_number=request_number, branch_id=branch_id,
            requested_by=requested_by, purpose=purpose, status="pending", comments=comments,
        )
        self.session.add(header)
        await self.session.flush()
        for ln in lines:
            self.session.add(RequestLine(
                tenant_id=tenant_id, request_id=header.id, product_id=ln["product_id"],
                requested_qty=Decimal(str(ln["requested_qty"])), remarks=ln.get("remarks"),
            ))
        await self.session.flush()
        await self.session.refresh(header)
        return header

    async def get(self, request_id: uuid.UUID) -> RequestHeader | None:
        return await self.session.scalar(select(RequestHeader).where(RequestHeader.id == request_id))

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

    async def issue_line(
        self, *, tenant_id: uuid.UUID, line: RequestLine, branch_id: uuid.UUID,
        qty: Decimal, user_id: uuid.UUID, request_id: uuid.UUID,
    ) -> str | None:
        """Deduct `qty` of the line's product from the branch and record an 'issue'
        movement. Returns an error string if stock is insufficient, else None."""
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
        inv.qty_on_hand = on_hand - qty
        inv.version = (inv.version or 0) + 1
        self.session.add(StockMovement(
            tenant_id=tenant_id, product_id=line.product_id, warehouse_id=branch_id,
            movement_type="issue", quantity=-qty, reference_type="order_request",
            reference_id=request_id, reason="Order request issue", user_id=user_id,
        ))
        line.issued_qty = qty
        await self.session.flush()
        return None

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
            .where(RequestHeader.status == "issued",
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
