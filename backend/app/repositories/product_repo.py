"""Product repository: get, search/list, create, soft-delete."""
from __future__ import annotations

import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product
from app.repositories.base import BaseRepository


class ProductRepository(BaseRepository[Product]):
    model = Product

    async def get(self, product_id: uuid.UUID) -> Product | None:
        stmt = select(Product).where(
            Product.id == product_id, Product.deleted_at.is_(None)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_sku(self, sku: str) -> Product | None:
        stmt = select(Product).where(
            Product.sku == sku, Product.deleted_at.is_(None)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    def _filtered(
        self,
        *,
        search: str | None,
        category_id: uuid.UUID | None,
        brand_id: uuid.UUID | None,
        supplier_id: uuid.UUID | None,
        status: str | None,
    ) -> Select:
        stmt = select(Product).where(Product.deleted_at.is_(None))
        if search:
            like = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Product.name.ilike(like),
                    Product.sku.ilike(like),
                    Product.barcode.ilike(like),
                )
            )
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        if brand_id:
            stmt = stmt.where(Product.brand_id == brand_id)
        if supplier_id:
            stmt = stmt.where(Product.primary_supplier_id == supplier_id)
        if status:
            stmt = stmt.where(Product.status == status)
        return stmt

    async def list(
        self,
        *,
        search: str | None = None,
        category_id: uuid.UUID | None = None,
        brand_id: uuid.UUID | None = None,
        supplier_id: uuid.UUID | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Product], int]:
        base = self._filtered(
            search=search,
            category_id=category_id,
            brand_id=brand_id,
            supplier_id=supplier_id,
            status=status,
        )
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = (
            base.order_by(Product.name)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), int(total or 0)
