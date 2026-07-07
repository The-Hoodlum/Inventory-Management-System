"""Data access for the Assembly Planner.

Two responsibilities, both read-only against the serialized registry plus its own small
override table:

  * ``assembly_counts`` — group motorcycle_units by model/variant/colour and pivot the
    lifecycle status into assembled vs unassembled counts (tenant-scoped by RLS, optionally
    narrowed to a branch set). This is the ONLY stock input the planner uses — it reads no
    sales, demand, or velocity data.
  * ``assembly_targets`` CRUD — the per model/colour tuning the planner falls back from.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssemblyTarget,
    MotorcycleColour,
    MotorcycleModel,
    MotorcycleUnit,
    MotorcycleVariant,
)
from app.motorcycles.domain import lifecycle as L


@dataclass(frozen=True)
class ComboCount:
    model_id: uuid.UUID
    variant_id: uuid.UUID | None
    colour_id: uuid.UUID | None
    assembled: int
    unassembled: int


class AssemblyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------- counts ---------------------------------- #
    async def assembly_counts(
        self, *, branch_ids: Sequence[uuid.UUID] | None = None, model_id: uuid.UUID | None = None
    ) -> list[ComboCount]:
        """Assembled vs unassembled counts per model/variant/colour combo. Only combos that
        actually hold units appear (the GROUP BY). branch_ids=None means all branches."""
        assembled = func.count().filter(MotorcycleUnit.status == L.ASSEMBLED)
        unassembled = func.count().filter(MotorcycleUnit.status == L.UNASSEMBLED)
        stmt = (
            select(
                MotorcycleUnit.model_id,
                MotorcycleUnit.variant_id,
                MotorcycleUnit.colour_id,
                assembled.label("assembled"),
                unassembled.label("unassembled"),
            )
            .group_by(MotorcycleUnit.model_id, MotorcycleUnit.variant_id, MotorcycleUnit.colour_id)
        )
        if branch_ids is not None:
            stmt = stmt.where(MotorcycleUnit.branch_id.in_(list(branch_ids)))
        if model_id is not None:
            stmt = stmt.where(MotorcycleUnit.model_id == model_id)
        rows = await self.session.execute(stmt)
        return [
            ComboCount(model_id=m, variant_id=v, colour_id=c, assembled=int(a), unassembled=int(u))
            for m, v, c, a, u in rows.all()
        ]

    # ------------------------------- targets --------------------------------- #
    async def list_targets(self) -> list[AssemblyTarget]:
        rows = await self.session.scalars(select(AssemblyTarget).order_by(AssemblyTarget.created_at))
        return list(rows)

    async def get_target(self, target_id: uuid.UUID) -> AssemblyTarget | None:
        return await self.session.scalar(select(AssemblyTarget).where(AssemblyTarget.id == target_id))

    async def get_target_by_combo(
        self, model_id: uuid.UUID, colour_id: uuid.UUID | None
    ) -> AssemblyTarget | None:
        stmt = select(AssemblyTarget).where(AssemblyTarget.model_id == model_id)
        stmt = stmt.where(
            AssemblyTarget.colour_id == colour_id if colour_id is not None
            else AssemblyTarget.colour_id.is_(None)
        )
        return await self.session.scalar(stmt)

    async def add_target(self, target: AssemblyTarget) -> AssemblyTarget:
        self.session.add(target)
        await self.session.flush()
        return target

    async def delete_target(self, target: AssemblyTarget) -> None:
        await self.session.delete(target)
        await self.session.flush()

    # --------------------------- reference lookups --------------------------- #
    async def model_exists(self, model_id: uuid.UUID) -> bool:
        return await self.session.scalar(select(MotorcycleModel.id).where(MotorcycleModel.id == model_id)) is not None

    async def colour_exists(self, colour_id: uuid.UUID) -> bool:
        return await self.session.scalar(select(MotorcycleColour.id).where(MotorcycleColour.id == colour_id)) is not None

    # ------------------------------ name maps -------------------------------- #
    async def model_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(MotorcycleModel, ids)

    async def variant_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(MotorcycleVariant, ids)

    async def colour_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(MotorcycleColour, ids)

    async def _names(self, model, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        wanted = [v for v in {*ids} if v is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(select(model.id, model.name).where(model.id.in_(wanted)))
        return {r.id: r.name for r in rows}
