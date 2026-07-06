"""Data access for typed delivery / dispatch notes."""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatch.domain import status as S
from app.models import (
    Branch,
    DispatchNote,
    DispatchNoteLine,
    MotorcycleModel,
    MotorcycleUnit,
    Product,
    Warehouse,
)


class DispatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def number(self, tenant_id: uuid.UUID) -> str:
        # Reuse the generic per-tenant/-year document counter (doc_type 'dispatch_note').
        return await self.session.scalar(
            text("SELECT next_sales_number(CAST(:t AS uuid), :d, :p)"),
            {"t": str(tenant_id), "d": "dispatch_note", "p": "DN"},
        )

    async def get(self, note_id: uuid.UUID, *, lock: bool = False) -> DispatchNote | None:
        stmt = select(DispatchNote).where(DispatchNote.id == note_id)
        if lock:
            stmt = stmt.with_for_update(of=DispatchNote)
        return await self.session.scalar(stmt)

    async def get_warehouse(self, wid: uuid.UUID) -> Warehouse | None:
        return await self.session.scalar(select(Warehouse).where(Warehouse.id == wid))

    async def get_product(self, pid: uuid.UUID) -> Product | None:
        return await self.session.scalar(select(Product).where(Product.id == pid))

    async def get_unit(self, uid: uuid.UUID, *, lock: bool = False) -> MotorcycleUnit | None:
        stmt = select(MotorcycleUnit).where(MotorcycleUnit.id == uid)
        if lock:
            stmt = stmt.with_for_update(of=MotorcycleUnit)
        return await self.session.scalar(stmt)

    async def unit_on_open_note(self, unit_id: uuid.UUID, *, exclude_note: uuid.UUID | None = None) -> bool:
        """Is this unit already on an OPEN (draft / in-transit) dispatch note?"""
        stmt = (
            select(DispatchNoteLine.id)
            .join(DispatchNote, DispatchNote.id == DispatchNoteLine.dispatch_note_id)
            .where(
                DispatchNoteLine.unit_id == unit_id,
                DispatchNote.status.in_((S.DRAFT, S.IN_TRANSIT, S.PARTIALLY_RECEIVED)),
            )
        )
        if exclude_note is not None:
            stmt = stmt.where(DispatchNote.id != exclude_note)
        return await self.session.scalar(stmt.limit(1)) is not None

    async def list_notes(
        self, *, branch_id: uuid.UUID | None = None, status: str | None = None,
        dispatch_type: str | None = None,
        branch_ids: Sequence[uuid.UUID] | None = None, limit: int = 100,
    ) -> list[DispatchNote]:
        stmt = select(DispatchNote)
        if branch_id is not None:
            stmt = stmt.where(or_(DispatchNote.from_branch_id == branch_id, DispatchNote.to_branch_id == branch_id))
        # Server-side branch scope: a note is visible if EITHER end is an allowed branch.
        if branch_ids is not None:
            ids = list(branch_ids)
            stmt = stmt.where(or_(DispatchNote.from_branch_id.in_(ids), DispatchNote.to_branch_id.in_(ids)))
        if status:
            stmt = stmt.where(DispatchNote.status == status)
        if dispatch_type:
            stmt = stmt.where(DispatchNote.dispatch_type == dispatch_type)
        stmt = stmt.order_by(DispatchNote.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    # ------------------------------ name maps -------------------------------- #
    async def _names(self, model, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        wanted = [v for v in {*ids} if v is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(select(model.id, model.name).where(model.id.in_(wanted)))
        return {r.id: r.name for r in rows}

    async def branch_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(Branch, ids)

    async def warehouse_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(Warehouse, ids)

    async def model_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(MotorcycleModel, ids)

    async def product_index(self, ids) -> dict[uuid.UUID, tuple[str, str]]:
        wanted = [v for v in {*ids} if v is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(Product.id, Product.sku, Product.name).where(Product.id.in_(wanted))
        )
        return {pid: (sku, name) for pid, sku, name in rows}

    async def unit_model_ids(self, unit_ids) -> dict[uuid.UUID, uuid.UUID]:
        wanted = [v for v in {*unit_ids} if v is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(MotorcycleUnit.id, MotorcycleUnit.model_id).where(MotorcycleUnit.id.in_(wanted))
        )
        return {uid: mid for uid, mid in rows}
