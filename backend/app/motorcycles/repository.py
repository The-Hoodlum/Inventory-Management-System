"""Data access for the Motorcycle module: reference catalog CRUD, the per-unit
registry (locked reads for lifecycle mutations), name resolution for output, and
lookups into the existing sales documents (customers / sales orders / invoices)."""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Brand,
    Category,
    Customer,
    Invoice,
    Issuance,
    IssuanceLine,
    MotorcycleColour,
    MotorcycleModel,
    MotorcycleUnit,
    MotorcycleUnitEvent,
    MotorcycleVariant,
    SalesOrder,
    Supplier,
    Warehouse,
)
from app.models.inventory import Branch


def _ids(values) -> list[uuid.UUID]:
    return [v for v in {*values} if v is not None]


class MotorcycleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ============================ reference: models ======================= #
    async def get_model(self, model_id: uuid.UUID) -> MotorcycleModel | None:
        return await self.session.scalar(select(MotorcycleModel).where(MotorcycleModel.id == model_id))

    async def model_name_conflict(
        self, brand_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
    ) -> bool:
        stmt = select(MotorcycleModel.id).where(
            MotorcycleModel.brand_id == brand_id, func.lower(MotorcycleModel.name) == name.strip().lower()
        )
        if exclude_id is not None:
            stmt = stmt.where(MotorcycleModel.id != exclude_id)
        return await self.session.scalar(stmt) is not None

    async def list_models(
        self, *, search: str | None, active_only: bool, page: int, page_size: int
    ) -> tuple[list[MotorcycleModel], int]:
        base = select(MotorcycleModel)
        if active_only:
            base = base.where(MotorcycleModel.is_active.is_(True))
        if search:
            base = base.where(MotorcycleModel.name.ilike(f"%{search.strip()}%"))
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self.session.scalars(
            base.order_by(MotorcycleModel.name).limit(page_size).offset((page - 1) * page_size)
        )
        return list(rows), int(total or 0)

    # =========================== reference: variants ====================== #
    async def get_variant(self, variant_id: uuid.UUID) -> MotorcycleVariant | None:
        return await self.session.scalar(select(MotorcycleVariant).where(MotorcycleVariant.id == variant_id))

    async def variant_name_conflict(
        self, model_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
    ) -> bool:
        stmt = select(MotorcycleVariant.id).where(
            MotorcycleVariant.model_id == model_id, func.lower(MotorcycleVariant.name) == name.strip().lower()
        )
        if exclude_id is not None:
            stmt = stmt.where(MotorcycleVariant.id != exclude_id)
        return await self.session.scalar(stmt) is not None

    async def list_variants(
        self, *, model_id: uuid.UUID | None, active_only: bool, page: int, page_size: int
    ) -> tuple[list[MotorcycleVariant], int]:
        base = select(MotorcycleVariant)
        if model_id is not None:
            base = base.where(MotorcycleVariant.model_id == model_id)
        if active_only:
            base = base.where(MotorcycleVariant.is_active.is_(True))
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self.session.scalars(
            base.order_by(MotorcycleVariant.name).limit(page_size).offset((page - 1) * page_size)
        )
        return list(rows), int(total or 0)

    # =========================== reference: colours ======================= #
    async def get_colour(self, colour_id: uuid.UUID) -> MotorcycleColour | None:
        return await self.session.scalar(select(MotorcycleColour).where(MotorcycleColour.id == colour_id))

    async def colour_name_conflict(self, name: str, exclude_id: uuid.UUID | None = None) -> bool:
        stmt = select(MotorcycleColour.id).where(func.lower(MotorcycleColour.name) == name.strip().lower())
        if exclude_id is not None:
            stmt = stmt.where(MotorcycleColour.id != exclude_id)
        return await self.session.scalar(stmt) is not None

    async def list_colours(
        self, *, active_only: bool, page: int, page_size: int
    ) -> tuple[list[MotorcycleColour], int]:
        base = select(MotorcycleColour)
        if active_only:
            base = base.where(MotorcycleColour.is_active.is_(True))
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self.session.scalars(
            base.order_by(MotorcycleColour.name).limit(page_size).offset((page - 1) * page_size)
        )
        return list(rows), int(total or 0)

    # ============================ existence checks ======================== #
    async def brand_exists(self, brand_id: uuid.UUID) -> bool:
        return await self.session.scalar(select(Brand.id).where(Brand.id == brand_id)) is not None

    async def get_or_create_brand(self, tenant_id: uuid.UUID, name: str) -> Brand:
        """Resolve a brand by name within the tenant, creating it if absent (reuses the
        shared brands table — the same get-or-create products use)."""
        existing = await self.session.scalar(
            select(Brand).where(func.lower(Brand.name) == name.strip().lower())
        )
        if existing is not None:
            return existing
        brand = Brand(tenant_id=tenant_id, name=name.strip())
        self.session.add(brand)
        await self.session.flush()
        return brand

    async def category_exists(self, category_id: uuid.UUID) -> bool:
        return await self.session.scalar(select(Category.id).where(Category.id == category_id)) is not None

    async def supplier_exists(self, supplier_id: uuid.UUID) -> bool:
        return await self.session.scalar(select(Supplier.id).where(Supplier.id == supplier_id)) is not None

    async def customer_exists(self, customer_id: uuid.UUID) -> bool:
        return await self.session.scalar(select(Customer.id).where(Customer.id == customer_id)) is not None

    async def get_sales_order(self, so_id: uuid.UUID) -> SalesOrder | None:
        return await self.session.scalar(select(SalesOrder).where(SalesOrder.id == so_id))

    async def get_invoice(self, invoice_id: uuid.UUID) -> Invoice | None:
        return await self.session.scalar(select(Invoice).where(Invoice.id == invoice_id))

    async def unit_out_on_loan(self, unit_id: uuid.UUID) -> bool:
        """Is this unit currently out on an OPEN internal issuance? A unit on loan is not
        sellable (derived from the issuance record — not a sale-status, not on_hold)."""
        stmt = (
            select(IssuanceLine.id)
            .join(Issuance, Issuance.id == IssuanceLine.issuance_id)
            .where(
                IssuanceLine.unit_id == unit_id,
                IssuanceLine.line_kind == "motorcycle",
                IssuanceLine.returnable.is_(True),
                IssuanceLine.returned_at.is_(None),
                Issuance.status.in_(("out_on_loan", "partially_returned")),
            )
        )
        return await self.session.scalar(stmt.limit(1)) is not None

    # =============================== units ============================== #
    async def get_unit(self, unit_id: uuid.UUID, *, lock: bool = False) -> MotorcycleUnit | None:
        stmt = select(MotorcycleUnit).where(MotorcycleUnit.id == unit_id)
        if lock:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_unit_by_chassis(self, chassis: str) -> MotorcycleUnit | None:
        return await self.session.scalar(
            select(MotorcycleUnit).where(func.lower(MotorcycleUnit.chassis_number) == chassis.strip().lower())
        )

    async def list_units(
        self, *, search: str | None = None, status: str | None = None,
        branch_id: uuid.UUID | None = None, model_id: uuid.UUID | None = None,
        variant_id: uuid.UUID | None = None, colour_id: uuid.UUID | None = None,
        sold: bool | None = None, inspected: bool | None = None,
        registered: bool | None = None, page: int = 1, page_size: int = 50,
    ) -> tuple[list[MotorcycleUnit], int]:
        base = select(MotorcycleUnit)
        if status:
            base = base.where(MotorcycleUnit.status == status)
        if inspected is not None:
            base = base.where(MotorcycleUnit.inspected.is_(inspected))
        if registered is not None:
            base = base.where(MotorcycleUnit.registered.is_(registered))
        if branch_id is not None:
            base = base.where(MotorcycleUnit.branch_id == branch_id)
        if model_id is not None:
            base = base.where(MotorcycleUnit.model_id == model_id)
        if variant_id is not None:
            base = base.where(MotorcycleUnit.variant_id == variant_id)
        if colour_id is not None:
            base = base.where(MotorcycleUnit.colour_id == colour_id)
        if sold is True:
            base = base.where(MotorcycleUnit.sold_ref.is_not(None))
        elif sold is False:
            base = base.where(MotorcycleUnit.sold_ref.is_(None))
        if search:
            like = f"%{search.strip()}%"
            base = base.where(or_(
                MotorcycleUnit.chassis_number.ilike(like),
                MotorcycleUnit.engine_number.ilike(like),
                MotorcycleUnit.registration_number.ilike(like),
            ))
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self.session.scalars(
            base.order_by(MotorcycleUnit.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
        )
        return list(rows), int(total or 0)

    async def status_counts(self, *, branch_id: uuid.UUID | None = None) -> dict[str, int]:
        """Count units grouped by lifecycle status (tenant-scoped by RLS; optionally
        narrowed to one branch). Powers the dashboard KPI."""
        stmt = select(MotorcycleUnit.status, func.count()).group_by(MotorcycleUnit.status)
        if branch_id is not None:
            stmt = stmt.where(MotorcycleUnit.branch_id == branch_id)
        rows = await self.session.execute(stmt)
        return {status: int(count) for status, count in rows.all()}

    # ============================ unit events =========================== #
    async def add_event(self, **kwargs) -> MotorcycleUnitEvent:
        event = MotorcycleUnitEvent(**kwargs)
        self.session.add(event)
        await self.session.flush()
        return event

    async def events_for(self, unit_id: uuid.UUID) -> list[MotorcycleUnitEvent]:
        rows = await self.session.scalars(
            select(MotorcycleUnitEvent)
            .where(MotorcycleUnitEvent.unit_id == unit_id)
            .order_by(MotorcycleUnitEvent.created_at.asc())
        )
        return list(rows)

    # ========================= name resolution ========================== #
    async def _names(self, model, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        wanted = _ids(ids)
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(model.id, model.name).where(model.id.in_(wanted))
        )
        return {r.id: r.name for r in rows}

    async def brand_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(Brand, ids)

    async def model_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(MotorcycleModel, ids)

    async def variant_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(MotorcycleVariant, ids)

    async def colour_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(MotorcycleColour, ids)

    async def supplier_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(Supplier, ids)

    async def branch_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(Branch, ids)

    async def warehouse_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(Warehouse, ids)

    async def customer_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(Customer, ids)

    async def so_number(self, so_id: uuid.UUID | None) -> str | None:
        if so_id is None:
            return None
        return await self.session.scalar(select(SalesOrder.so_number).where(SalesOrder.id == so_id))

    async def invoice_number(self, invoice_id: uuid.UUID | None) -> str | None:
        if invoice_id is None:
            return None
        return await self.session.scalar(select(Invoice.invoice_number).where(Invoice.id == invoice_id))
