"""Data access for bike issues (internal repairs that consume spare parts).

Stock is NEVER written here — the service drives InventoryService for every deduction.
This repository persists the issue documents + resolves display names, and reads/locks
the serialized unit + writes its lifecycle event (the same ledger the motorcycle module
uses) for the on_hold tie-in.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    BikeIssue,
    Branch,
    MotorcycleModel,
    MotorcycleUnit,
    MotorcycleUnitEvent,
    Product,
    Warehouse,
)


class BikeIssueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def number(self, tenant_id: uuid.UUID) -> str:
        return await self.session.scalar(
            text("SELECT next_sales_number(CAST(:t AS uuid), :d, :p)"),
            {"t": str(tenant_id), "d": "bike_issue", "p": "REP"},
        )

    # ------------------------------- issues ---------------------------------- #
    async def get(self, issue_id: uuid.UUID, *, lock: bool = False) -> BikeIssue | None:
        stmt = select(BikeIssue).where(BikeIssue.id == issue_id)
        if lock:
            stmt = stmt.with_for_update(of=BikeIssue)
        return await self.session.scalar(stmt)

    async def list_issues(
        self, *, status: str | None = None, branch_id: uuid.UUID | None = None,
        branch_ids: Sequence[uuid.UUID] | None = None, unit_id: uuid.UUID | None = None,
        model_id: uuid.UUID | None = None, search: str | None = None,
        page: int = 1, page_size: int = 50,
    ) -> tuple[list[BikeIssue], int]:
        base = select(BikeIssue)
        if status:
            base = base.where(BikeIssue.status == status)
        if branch_id is not None:
            base = base.where(BikeIssue.branch_id == branch_id)
        # Server-side branch scope (user restricted to certain branches). None = all.
        if branch_ids is not None:
            base = base.where(BikeIssue.branch_id.in_(list(branch_ids)))
        if unit_id is not None:
            base = base.where(BikeIssue.unit_id == unit_id)
        if model_id is not None:
            base = base.where(
                BikeIssue.unit_id.in_(
                    select(MotorcycleUnit.id).where(MotorcycleUnit.model_id == model_id)
                )
            )
        if search:
            like = f"%{search.strip()}%"
            base = base.where(or_(
                BikeIssue.chassis_number.ilike(like),
                BikeIssue.engine_number.ilike(like),
                BikeIssue.issue_number.ilike(like),
            ))
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self.session.scalars(
            base.order_by(BikeIssue.reported_at.desc()).limit(page_size).offset((page - 1) * page_size)
        )
        return list(rows), int(total or 0)

    # ------------------------- referenced entities --------------------------- #
    async def get_product(self, pid: uuid.UUID) -> Product | None:
        return await self.session.scalar(select(Product).where(Product.id == pid))

    async def get_warehouse(self, wid: uuid.UUID) -> Warehouse | None:
        return await self.session.scalar(select(Warehouse).where(Warehouse.id == wid))

    async def get_unit(self, unit_id: uuid.UUID, *, lock: bool = False) -> MotorcycleUnit | None:
        stmt = select(MotorcycleUnit).where(MotorcycleUnit.id == unit_id)
        if lock:
            stmt = stmt.with_for_update(of=MotorcycleUnit)
        return await self.session.scalar(stmt)

    async def add_unit_event(self, **kwargs) -> MotorcycleUnitEvent:
        """Write to the serialized unit's own immutable lifecycle ledger (shared with the
        motorcycle module), so a repair hold/release shows in the unit's history."""
        event = MotorcycleUnitEvent(**kwargs)
        self.session.add(event)
        await self.session.flush()
        return event

    # ------------------------------ name maps -------------------------------- #
    async def branch_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(Branch, ids)

    async def warehouse_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(Warehouse, ids)

    async def _names(self, model, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        wanted = [v for v in {*ids} if v is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(select(model.id, model.name).where(model.id.in_(wanted)))
        return {r.id: r.name for r in rows}

    async def product_index(self, ids) -> dict[uuid.UUID, tuple[str, str]]:
        wanted = [v for v in {*ids} if v is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(Product.id, Product.sku, Product.name).where(Product.id.in_(wanted))
        )
        return {pid: (sku, name) for pid, sku, name in rows}

    async def unit_model_names(self, unit_ids) -> dict[uuid.UUID, str]:
        """Map unit_id -> model display name (for the issue list/detail)."""
        wanted = [v for v in {*unit_ids} if v is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(MotorcycleUnit.id, MotorcycleModel.name)
            .join(MotorcycleModel, MotorcycleModel.id == MotorcycleUnit.model_id)
            .where(MotorcycleUnit.id.in_(wanted))
        )
        return {uid: name for uid, name in rows}
