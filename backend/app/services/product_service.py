"""Product service: create / update / soft-delete / get / search, with audit."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Brand, Category, Product
from app.repositories.audit_repo import AuditRepository
from app.repositories.product_repo import ProductRepository
from app.schemas.product import ProductCreate, ProductUpdate

_AUDITED_FIELDS = (
    "sku", "barcode", "name", "status", "cost_price", "selling_price", "wholesale_price",
    "units_per_carton", "moq", "lead_time_days", "category_id", "brand_id",
    "primary_supplier_id", "reorder_point", "safety_stock",
    # Product Intelligence Profile
    "commodity_tags", "country_of_origin", "transport_mode", "criticality",
    "supplier_dependency", "demand_type", "substitutability",
    "unit_of_measure", "currency", "strategic_item", "alternate_supplier_available",
)


def _snapshot(p: Product) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in _AUDITED_FIELDS:
        v = getattr(p, f)
        out[f] = str(v) if v is not None else None
    return out


class ProductService:
    def __init__(self, products: ProductRepository, audit: AuditRepository) -> None:
        self.products = products
        self.audit = audit

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ProductCreate,
        ip: str | None = None,
    ) -> Product:
        if await self.products.get_by_sku(data.sku):
            raise ConflictError(f"A product with SKU '{data.sku}' already exists")
        payload = data.model_dump()
        category = payload.pop("category", None)
        brand = payload.pop("brand", None)
        product = Product(tenant_id=tenant_id, **payload)
        cat = await self._get_or_create_category(tenant_id, category)
        if cat is not None:
            product.category_id = cat.id
        br = await self._get_or_create_brand(tenant_id, brand)
        if br is not None:
            product.brand_id = br.id
        await self.products.add(product)
        await self._attach_names([product])
        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="create",
            entity_type="product",
            entity_id=product.id,
            changes={"after": _snapshot(product)},
            ip_address=ip,
        )
        return product

    async def get(self, product_id: uuid.UUID) -> Product:
        product = await self.products.get(product_id)
        if product is None:
            raise NotFoundError("Product not found")
        await self._attach_names([product])
        return product

    async def update(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        product_id: uuid.UUID,
        data: ProductUpdate,
        ip: str | None = None,
    ) -> Product:
        product = await self.get(product_id)
        changes = data.model_dump(exclude_unset=True)
        if "sku" in changes and changes["sku"] != product.sku:
            if await self.products.get_by_sku(changes["sku"]):
                raise ConflictError(f"A product with SKU '{changes['sku']}' already exists")

        # Category/Brand arrive by name (get-or-create); empty string clears them.
        has_category = "category" in changes
        has_brand = "brand" in changes
        category = changes.pop("category", None)
        brand = changes.pop("brand", None)

        before = _snapshot(product)
        for field, value in changes.items():
            setattr(product, field, value)
        if has_category:
            cat = await self._get_or_create_category(tenant_id, category)
            product.category_id = cat.id if cat is not None else None
        if has_brand:
            br = await self._get_or_create_brand(tenant_id, brand)
            product.brand_id = br.id if br is not None else None
        await self.products.session.flush()
        await self._attach_names([product])
        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="update",
            entity_type="product",
            entity_id=product.id,
            changes={"before": before, "after": _snapshot(product)},
            ip_address=ip,
        )
        return product

    async def delete(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        product_id: uuid.UUID,
        ip: str | None = None,
    ) -> None:
        product = await self.get(product_id)
        product.deleted_at = func.now()
        await self.products.session.flush()
        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="delete",
            entity_type="product",
            entity_id=product.id,
            changes={"soft_deleted": True},
            ip_address=ip,
        )

    async def search(
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
        items, total = await self.products.list(
            search=search,
            category_id=category_id,
            brand_id=brand_id,
            supplier_id=supplier_id,
            status=status,
            page=page,
            page_size=page_size,
        )
        await self._attach_names(items)
        return items, total

    # --------------------- reference data helpers ---------------------- #
    async def _get_or_create_category(self, tenant_id: uuid.UUID, name: str | None) -> Category | None:
        clean = (name or "").strip()
        if not clean:
            return None
        res = await self.products.session.execute(select(Category).where(Category.name == clean).limit(1))
        cat = res.scalar_one_or_none()
        if cat is None:
            cat = Category(tenant_id=tenant_id, name=clean)
            self.products.session.add(cat)
            await self.products.session.flush()
        return cat

    async def _get_or_create_brand(self, tenant_id: uuid.UUID, name: str | None) -> Brand | None:
        clean = (name or "").strip()
        if not clean:
            return None
        res = await self.products.session.execute(select(Brand).where(Brand.name == clean).limit(1))
        br = res.scalar_one_or_none()
        if br is None:
            br = Brand(tenant_id=tenant_id, name=clean)
            self.products.session.add(br)
            await self.products.session.flush()
        return br

    async def _attach_names(self, products: list[Product]) -> None:
        """Set transient ``category_name`` / ``brand_name`` on each product for the
        API response (batched lookup — no N+1)."""
        cat_ids = {p.category_id for p in products if p.category_id}
        brand_ids = {p.brand_id for p in products if p.brand_id}
        cats: dict = {}
        brands: dict = {}
        if cat_ids:
            res = await self.products.session.execute(
                select(Category.id, Category.name).where(Category.id.in_(cat_ids))
            )
            cats = {i: n for i, n in res.all()}
        if brand_ids:
            res = await self.products.session.execute(
                select(Brand.id, Brand.name).where(Brand.id.in_(brand_ids))
            )
            brands = {i: n for i, n in res.all()}
        for p in products:
            p.category_name = cats.get(p.category_id)
            p.brand_name = brands.get(p.brand_id)
