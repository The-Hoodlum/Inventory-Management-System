"""Data access for internal issuance / handover."""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.issuance.domain import status as S
from app.models import (
    Branch,
    Issuance,
    IssuanceLine,
    MotorcycleModel,
    MotorcycleUnit,
    Product,
    Warehouse,
)


class IssuanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def number(self, tenant_id: uuid.UUID) -> str:
        return await self.session.scalar(
            text("SELECT next_sales_number(CAST(:t AS uuid), :d, :p)"),
            {"t": str(tenant_id), "d": "issuance", "p": "ISS"},
        )

    async def get(self, iid: uuid.UUID, *, lock: bool = False) -> Issuance | None:
        stmt = select(Issuance).where(Issuance.id == iid)
        if lock:
            stmt = stmt.with_for_update(of=Issuance)
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

    async def unit_out_on_loan(self, unit_id: uuid.UUID) -> bool:
        """Is this unit already out on an OPEN returnable issuance?"""
        stmt = (
            select(IssuanceLine.id)
            .join(Issuance, Issuance.id == IssuanceLine.issuance_id)
            .where(
                IssuanceLine.unit_id == unit_id,
                IssuanceLine.line_kind == "motorcycle",
                IssuanceLine.returnable.is_(True),
                IssuanceLine.returned_at.is_(None),
                Issuance.status.in_(tuple(S.OPEN)),
            )
        )
        return await self.session.scalar(stmt.limit(1)) is not None

    async def list_issuances(
        self, *, branch_id: uuid.UUID | None = None, status: str | None = None,
        open_only: bool = False,
        branch_ids: Sequence[uuid.UUID] | None = None, limit: int = 100,
    ) -> list[Issuance]:
        stmt = select(Issuance)
        if branch_id is not None:
            stmt = stmt.where(Issuance.branch_id == branch_id)
        if branch_ids is not None:
            stmt = stmt.where(Issuance.branch_id.in_(list(branch_ids)))
        if status:
            stmt = stmt.where(Issuance.status == status)
        if open_only:
            stmt = stmt.where(Issuance.status.in_(tuple(S.OPEN)))
        stmt = stmt.order_by(Issuance.created_at.desc()).limit(limit)
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
