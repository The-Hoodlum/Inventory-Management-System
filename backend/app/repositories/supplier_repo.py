"""Supplier repository: get, list, create, soft-delete."""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select

from app.models import Supplier
from app.repositories.base import BaseRepository


class SupplierRepository(BaseRepository[Supplier]):
    model = Supplier

    async def get(self, supplier_id: uuid.UUID) -> Supplier | None:
        stmt = select(Supplier).where(
            Supplier.id == supplier_id, Supplier.deleted_at.is_(None)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Supplier | None:
        stmt = select(Supplier).where(
            Supplier.name == name, Supplier.deleted_at.is_(None)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Supplier], int]:
        base = select(Supplier).where(Supplier.deleted_at.is_(None))
        if search:
            like = f"%{search}%"
            base = base.where(
                or_(
                    Supplier.name.ilike(like),
                    Supplier.contact_person.ilike(like),
                    Supplier.email.ilike(like),
                )
            )
        if status:
            base = base.where(Supplier.status == status)
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = (
            base.order_by(Supplier.name)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), int(total or 0)
