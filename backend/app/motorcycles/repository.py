"""Data access for the motorcycle (serialized-unit) registry: locked reads, filtered
list, append-only event ledger writes, and name enrichment. Tenant isolation is enforced
by RLS on the request session.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Branch,
    Customer,
    Invoice,
    MotorcycleUnit,
    MotorcycleUnitEvent,
    SalesOrder,
    Supplier,
    Warehouse,
)


class MotorcycleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------ reads ------------------------------ #
    async def get(self, unit_id: uuid.UUID, *, lock: bool = False) -> MotorcycleUnit | None:
        stmt = select(MotorcycleUnit).where(MotorcycleUnit.id == unit_id)
        if lock:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_by_chassis(self, chassis: str) -> MotorcycleUnit | None:
        return await self.session.scalar(
            select(MotorcycleUnit).where(MotorcycleUnit.chassis_number == chassis)
        )

    async def events_for(self, unit_id: uuid.UUID) -> list[MotorcycleUnitEvent]:
        """The unit's lifecycle ledger, oldest-first. Queried explicitly (not via the
        lazy relationship) so it is always current and safe under async."""
        res = await self.session.execute(
            select(MotorcycleUnitEvent)
            .where(MotorcycleUnitEvent.unit_id == unit_id)
            .order_by(MotorcycleUnitEvent.created_at, MotorcycleUnitEvent.event_type)
        )
        return list(res.scalars().all())

    async def list(
        self,
        *,
        status: str | None = None,
        branch_id: uuid.UUID | None = None,
        model: str | None = None,
        colour: str | None = None,
        sold: bool | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[MotorcycleUnit], int]:
        base = select(MotorcycleUnit)
        if status:
            base = base.where(MotorcycleUnit.status == status)
        if branch_id:
            base = base.where(MotorcycleUnit.branch_id == branch_id)
        if model:
            base = base.where(MotorcycleUnit.model == model)
        if colour:
            base = base.where(MotorcycleUnit.colour == colour)
        if sold is not None:
            base = base.where(MotorcycleUnit.sold.is_(sold))
        if search:
            like = f"%{search.strip()}%"
            base = base.where(or_(
                MotorcycleUnit.chassis_number.ilike(like),
                MotorcycleUnit.engine_number.ilike(like),
                MotorcycleUnit.registration_number.ilike(like),
            ))
        total = await self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = (
            await self.session.execute(
                base.order_by(MotorcycleUnit.created_at.desc())
                .limit(page_size).offset((page - 1) * page_size)
            )
        ).scalars().all()
        return list(rows), int(total)

    # --------------------------- ledger write -------------------------- #
    async def add_event(
        self, *, tenant_id: uuid.UUID, unit_id: uuid.UUID, event_type: str,
        user_id: uuid.UUID | None, from_status: str | None = None, to_status: str | None = None,
        from_branch_id: uuid.UUID | None = None, to_branch_id: uuid.UUID | None = None,
        reference_type: str | None = None, reference_id: uuid.UUID | None = None,
        note: str | None = None,
    ) -> MotorcycleUnitEvent:
        ev = MotorcycleUnitEvent(
            tenant_id=tenant_id, unit_id=unit_id, event_type=event_type, user_id=user_id,
            from_status=from_status, to_status=to_status, from_branch_id=from_branch_id,
            to_branch_id=to_branch_id, reference_type=reference_type, reference_id=reference_id,
            note=note,
        )
        self.session.add(ev)
        await self.session.flush()
        return ev

    # --------------------------- linkage reads ------------------------- #
    async def get_sales_order(self, so_id: uuid.UUID) -> SalesOrder | None:
        return await self.session.scalar(select(SalesOrder).where(SalesOrder.id == so_id))

    async def get_invoice(self, invoice_id: uuid.UUID) -> Invoice | None:
        return await self.session.scalar(select(Invoice).where(Invoice.id == invoice_id))

    async def customer_exists(self, customer_id: uuid.UUID) -> bool:
        return await self.session.scalar(
            select(func.count()).select_from(Customer).where(Customer.id == customer_id)
        ) == 1

    # ---------------------------- enrichment --------------------------- #
    async def _names(self, model, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        ids = [i for i in {*ids} if i]
        if not ids:
            return {}
        res = await self.session.execute(select(model.id, model.name).where(model.id.in_(ids)))
        return {i: n for i, n in res.all()}

    async def branch_names(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        return await self._names(Branch, ids)

    async def warehouse_names(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        return await self._names(Warehouse, ids)

    async def supplier_names(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        return await self._names(Supplier, ids)

    async def customer_names(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        return await self._names(Customer, ids)

    async def so_number(self, so_id: uuid.UUID | None) -> str | None:
        if not so_id:
            return None
        return await self.session.scalar(select(SalesOrder.so_number).where(SalesOrder.id == so_id))

    async def invoice_number(self, invoice_id: uuid.UUID | None) -> str | None:
        if not invoice_id:
            return None
        return await self.session.scalar(select(Invoice.invoice_number).where(Invoice.id == invoice_id))
