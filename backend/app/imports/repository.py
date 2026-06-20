"""Import-framework repository: import_jobs/files/errors persistence plus the
get-or-create + product/stock helpers the targets need. Tenant isolation is enforced
by RLS (the request sets ``app.current_tenant``), so reads don't filter by tenant_id;
inserts set it so the RLS ``WITH CHECK`` passes.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Brand,
    Category,
    ImportFile,
    ImportJob,
    ImportMapping,
    Inventory,
    Product,
    StockMovement,
    Supplier,
    Warehouse,
)
from app.models.imports import ImportError as ImportErrorRow
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.supplier_repo import SupplierRepository
from app.repositories.warehouse_repo import WarehouseRepository


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class ImportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.products = ProductRepository(session)
        self.warehouses = WarehouseRepository(session)
        self.suppliers = SupplierRepository(session)
        self.inventory = InventoryRepository(session)

    # ------------------------------- jobs ------------------------------ #
    async def create_job(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        target_key: str,
        filename: str,
        total_rows: int,
        column_mapping: dict | None = None,
        options: dict | None = None,
        status: str = "pending",
    ) -> ImportJob:
        job = ImportJob(
            tenant_id=tenant_id,
            created_by=user_id,
            target_key=target_key,
            filename=filename,
            total_rows=total_rows,
            status=status,
            column_mapping=column_mapping,
            options=options,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_job(self, job_id: uuid.UUID) -> ImportJob | None:
        return await self.session.get(ImportJob, job_id)

    async def list_jobs(
        self, *, target_key: str | None = None, page: int = 1, page_size: int = 20
    ) -> tuple[list[ImportJob], int]:
        base = select(ImportJob)
        if target_key:
            base = base.where(ImportJob.target_key == target_key)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        stmt = (
            base.order_by(ImportJob.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), int(total or 0)

    # ------------------------------ files ------------------------------ #
    async def save_file(
        self, *, job_id: uuid.UUID, tenant_id: uuid.UUID, content: bytes, content_type: str | None
    ) -> None:
        self.session.add(
            ImportFile(job_id=job_id, tenant_id=tenant_id, content=content, content_type=content_type)
        )
        await self.session.flush()

    async def get_file_content(self, job_id: uuid.UUID) -> bytes | None:
        f = await self.session.get(ImportFile, job_id)
        return bytes(f.content) if f is not None else None

    async def file_exists(self, job_id: uuid.UUID) -> bool:
        res = await self.session.execute(
            select(ImportFile.job_id).where(ImportFile.job_id == job_id).limit(1)
        )
        return res.scalar_one_or_none() is not None

    # ------------------------------ errors ----------------------------- #
    async def add_error(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        row_number: int,
        sku: str | None,
        message: str,
    ) -> None:
        self.session.add(
            ImportErrorRow(
                tenant_id=tenant_id,
                import_job_id=job_id,
                row_number=row_number,
                sku=sku,
                error_message=message,
            )
        )

    async def list_errors(
        self, job_id: uuid.UUID, *, limit: int | None = None
    ) -> list[ImportErrorRow]:
        stmt = (
            select(ImportErrorRow)
            .where(ImportErrorRow.import_job_id == job_id)
            .order_by(ImportErrorRow.row_number)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    # -------------------- reference data (get / create) ---------------- #
    async def find_warehouse(self, name: str) -> Warehouse | None:
        res = await self.session.execute(
            select(Warehouse).where((Warehouse.code == name) | (Warehouse.name == name)).limit(1)
        )
        return res.scalar_one_or_none()

    async def create_warehouse(self, tenant_id: uuid.UUID, name: str) -> Warehouse:
        wh = Warehouse(tenant_id=tenant_id, code=name[:64], name=name)
        self.session.add(wh)
        await self.session.flush()
        return wh

    async def find_supplier(self, name: str) -> Supplier | None:
        return await self.suppliers.get_by_name(name)

    async def create_supplier(self, tenant_id: uuid.UUID, name: str) -> Supplier:
        sup = Supplier(tenant_id=tenant_id, name=name)  # currency defaults to tenant convention
        self.session.add(sup)
        await self.session.flush()
        return sup

    async def find_category(self, name: str) -> Category | None:
        res = await self.session.execute(select(Category).where(Category.name == name).limit(1))
        return res.scalar_one_or_none()

    async def create_category(self, tenant_id: uuid.UUID, name: str) -> Category:
        cat = Category(tenant_id=tenant_id, name=name)
        self.session.add(cat)
        await self.session.flush()
        return cat

    async def find_brand(self, name: str) -> Brand | None:
        res = await self.session.execute(select(Brand).where(Brand.name == name).limit(1))
        return res.scalar_one_or_none()

    async def create_brand(self, tenant_id: uuid.UUID, name: str) -> Brand:
        br = Brand(tenant_id=tenant_id, name=name)
        self.session.add(br)
        await self.session.flush()
        return br

    # ------------------------------ products --------------------------- #
    async def get_product_by_sku(self, sku: str) -> Product | None:
        return await self.products.get_by_sku(sku)

    async def create_product(
        self,
        *,
        tenant_id: uuid.UUID,
        sku: str,
        attrs: dict[str, Any],
        category_id: uuid.UUID | None,
        brand_id: uuid.UUID | None,
        supplier_id: uuid.UUID | None,
        import_job_id: uuid.UUID,
    ) -> Product:
        product = Product(
            tenant_id=tenant_id,
            sku=sku,
            category_id=category_id,
            brand_id=brand_id,
            primary_supplier_id=supplier_id,
            created_by_import_job_id=import_job_id,
            **attrs,
        )
        self.session.add(product)
        await self.session.flush()
        return product

    async def update_product(
        self,
        product: Product,
        *,
        attrs: dict[str, Any],
        category_id: uuid.UUID | None,
        brand_id: uuid.UUID | None,
        supplier_id: uuid.UUID | None,
    ) -> Product:
        for col, val in attrs.items():
            setattr(product, col, val)
        if category_id is not None:
            product.category_id = category_id
        if brand_id is not None:
            product.brand_id = brand_id
        if supplier_id is not None:
            product.primary_supplier_id = supplier_id
        product.updated_at = _now()
        await self.session.flush()
        return product

    # ------------------------------- stock ----------------------------- #
    async def get_inventory(self, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> Inventory | None:
        return await self.inventory.get(product_id, warehouse_id)

    async def create_inventory(
        self, tenant_id: uuid.UUID, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Inventory:
        return await self.inventory.create(tenant_id, product_id, warehouse_id)

    async def add_movement(self, **fields: Any) -> StockMovement:
        return await self.inventory.add_movement(**fields)

    # --------------------- rollback / retry support -------------------- #
    async def job_movements(self, job_id: uuid.UUID) -> list[StockMovement]:
        res = await self.session.execute(
            select(StockMovement).where(
                StockMovement.reference_id == job_id,
                StockMovement.reference_type == "inventory_import",
            )
        )
        return list(res.scalars().all())

    async def other_movement_exists(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, job_id: uuid.UUID
    ) -> bool:
        """True if this (product, warehouse) has any stock movement NOT from this
        import job — i.e. stock moved since the import, so a rollback isn't safe."""
        res = await self.session.execute(
            select(StockMovement.id)
            .where(
                StockMovement.product_id == product_id,
                StockMovement.warehouse_id == warehouse_id,
                ~(
                    (StockMovement.reference_id == job_id)
                    & (StockMovement.reference_type == "inventory_import")
                ),
            )
            .limit(1)
        )
        return res.scalar_one_or_none() is not None

    async def get_inventory_for_update(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Inventory | None:
        return await self.inventory.get_for_update(product_id, warehouse_id)

    async def delete_movement(self, movement: StockMovement) -> None:
        await self.session.delete(movement)

    async def products_created_by_job(self, job_id: uuid.UUID) -> list[Product]:
        res = await self.session.execute(
            select(Product).where(Product.created_by_import_job_id == job_id)
        )
        return list(res.scalars().all())

    async def delete_product(self, product: Product) -> None:
        await self.session.delete(product)

    async def failed_row_numbers(self, job_id: uuid.UUID) -> list[int]:
        """Distinct row numbers that errored (excludes 'Skipped:' business skips)."""
        res = await self.session.execute(
            select(ImportErrorRow.row_number)
            .where(
                ImportErrorRow.import_job_id == job_id,
                ~ImportErrorRow.error_message.like("Skipped:%"),
            )
            .distinct()
            .order_by(ImportErrorRow.row_number)
        )
        return [r for (r,) in res.all()]

    # ----------------------- remembered mappings ----------------------- #
    async def find_mapping(self, target_key: str, signature: str) -> ImportMapping | None:
        res = await self.session.execute(
            select(ImportMapping)
            .where(ImportMapping.target_key == target_key, ImportMapping.header_signature == signature)
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def upsert_mapping(
        self, *, tenant_id: uuid.UUID, target_key: str, signature: str, mapping: dict, user_id: uuid.UUID
    ) -> ImportMapping:
        existing = await self.find_mapping(target_key, signature)
        if existing is not None:
            existing.mapping = mapping
            existing.created_by = user_id
            existing.updated_at = _now()
            await self.session.flush()
            return existing
        row = ImportMapping(
            tenant_id=tenant_id, target_key=target_key, header_signature=signature,
            mapping=mapping, created_by=user_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row
