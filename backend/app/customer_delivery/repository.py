"""Data access for branch -> customer/reseller deliveries."""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.customer_delivery.domain import status as S
from app.models import (
    Branch,
    Customer,
    CustomerDelivery,
    CustomerDeliveryLine,
    Invoice,
    InvoiceLine,
    MotorcycleModel,
    MotorcycleUnit,
    Product,
    Warehouse,
)


class CustomerDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def number(self, tenant_id: uuid.UUID) -> str:
        return await self.session.scalar(
            text("SELECT next_sales_number(CAST(:t AS uuid), :d, :p)"),
            {"t": str(tenant_id), "d": "customer_delivery", "p": "CD"},
        )

    async def get(self, did: uuid.UUID, *, lock: bool = False) -> CustomerDelivery | None:
        stmt = select(CustomerDelivery).where(CustomerDelivery.id == did)
        if lock:
            stmt = stmt.with_for_update(of=CustomerDelivery)
        return await self.session.scalar(stmt)

    async def get_warehouse(self, wid: uuid.UUID) -> Warehouse | None:
        return await self.session.scalar(select(Warehouse).where(Warehouse.id == wid))

    async def get_product(self, pid: uuid.UUID) -> Product | None:
        return await self.session.scalar(select(Product).where(Product.id == pid))

    async def get_customer(self, cid: uuid.UUID) -> Customer | None:
        return await self.session.scalar(select(Customer).where(Customer.id == cid))

    async def get_unit(self, uid: uuid.UUID, *, lock: bool = False) -> MotorcycleUnit | None:
        stmt = select(MotorcycleUnit).where(MotorcycleUnit.id == uid)
        if lock:
            stmt = stmt.with_for_update(of=MotorcycleUnit)
        return await self.session.scalar(stmt)

    async def get_invoice(self, iid: uuid.UUID) -> Invoice | None:
        return await self.session.scalar(select(Invoice).where(Invoice.id == iid))

    async def invoice_part_lines(self, invoice_id: uuid.UUID) -> list[tuple[uuid.UUID, float]]:
        rows = await self.session.execute(
            select(InvoiceLine.product_id, InvoiceLine.qty).where(InvoiceLine.invoice_id == invoice_id)
        )
        return [(pid, float(qty)) for pid, qty in rows]

    async def units_on_invoice(self, invoice_id: uuid.UUID) -> list[MotorcycleUnit]:
        rows = await self.session.scalars(
            select(MotorcycleUnit).where(MotorcycleUnit.sold_ref == invoice_id)
        )
        return list(rows)

    async def unit_on_open_consignment(self, unit_id: uuid.UUID) -> bool:
        """Is this unit currently OUT on an open consignment (not yet settled/returned)?"""
        stmt = (
            select(CustomerDeliveryLine.id)
            .join(CustomerDelivery, CustomerDelivery.id == CustomerDeliveryLine.delivery_id)
            .where(
                CustomerDeliveryLine.unit_id == unit_id,
                CustomerDeliveryLine.line_kind == "motorcycle",
                CustomerDeliveryLine.settled_qty <= 0,
                CustomerDeliveryLine.returned_qty <= 0,
                CustomerDelivery.status.in_(tuple(S.OPEN_CONSIGNMENT)),
            )
        )
        return await self.session.scalar(stmt.limit(1)) is not None

    async def list_deliveries(
        self, *, customer_id: uuid.UUID | None, status: str | None, mode: str | None, limit: int = 100,
    ) -> list[CustomerDelivery]:
        stmt = select(CustomerDelivery)
        if customer_id is not None:
            stmt = stmt.where(CustomerDelivery.customer_id == customer_id)
        if status:
            stmt = stmt.where(CustomerDelivery.status == status)
        if mode:
            stmt = stmt.where(CustomerDelivery.delivery_mode == mode)
        stmt = stmt.order_by(CustomerDelivery.created_at.desc()).limit(limit)
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

    async def customer_names(self, ids) -> dict[uuid.UUID, str]:
        return await self._names(Customer, ids)

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

    async def invoice_number(self, invoice_id: uuid.UUID | None) -> str | None:
        if invoice_id is None:
            return None
        return await self.session.scalar(select(Invoice.invoice_number).where(Invoice.id == invoice_id))
