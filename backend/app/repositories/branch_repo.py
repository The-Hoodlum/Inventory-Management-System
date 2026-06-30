"""Branch repository: get, list, create (via base), delete."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models import Branch
from app.repositories.base import BaseRepository


class BranchRepository(BaseRepository[Branch]):
    model = Branch

    async def get(self, branch_id: uuid.UUID) -> Branch | None:
        return await self.session.get(Branch, branch_id)

    async def get_by_code(self, code: str) -> Branch | None:
        res = await self.session.execute(select(Branch).where(Branch.code == code))
        return res.scalar_one_or_none()

    async def list(
        self, *, active_only: bool = False, page: int = 1, page_size: int = 100
    ) -> tuple[list[Branch], int]:
        base = select(Branch)
        if active_only:
            base = base.where(Branch.is_active.is_(True))
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        stmt = base.order_by(Branch.name).limit(page_size).offset((page - 1) * page_size)
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), int(total or 0)

    async def delete(self, branch: Branch) -> None:
        await self.session.delete(branch)
        await self.session.flush()
