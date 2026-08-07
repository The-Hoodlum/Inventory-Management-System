"""Data access for Customer Handovers."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Branch,
    Customer,
    CustomerAddress,
    CustomerHandover,
    Invoice,
    MotorcycleColour,
    MotorcycleModel,
    MotorcycleUnit,
    SalesOrder,
    User,
)


class CustomerHandoverRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def number(self, tenant_id: uuid.UUID) -> str:
        return await self.session.scalar(
            text("SELECT next_sales_number(CAST(:t AS uuid), :d, :p)"),
            {"t": str(tenant_id), "d": "handover", "p": "HO"},
        )

    async def get(self, hid: uuid.UUID, *, lock: bool = False) -> CustomerHandover | None:
        stmt = select(CustomerHandover).where(CustomerHandover.id == hid)
        if lock:
            stmt = stmt.with_for_update(of=CustomerHandover)
        return await self.session.scalar(stmt)

    async def get_unit(self, uid: uuid.UUID, *, lock: bool = False) -> MotorcycleUnit | None:
        stmt = select(MotorcycleUnit).where(MotorcycleUnit.id == uid)
        if lock:
            stmt = stmt.with_for_update(of=MotorcycleUnit)
        return await self.session.scalar(stmt)

    async def get_invoice(self, iid: uuid.UUID) -> Invoice | None:
        return await self.session.scalar(select(Invoice).where(Invoice.id == iid))

    async def get_customer(self, cid: uuid.UUID) -> Customer | None:
        return await self.session.scalar(select(Customer).where(Customer.id == cid))

    async def default_address(self, cid: uuid.UUID) -> CustomerAddress | None:
        """The customer's default address (else the first). Used to seed physical_address."""
        rows = await self.session.scalars(
            select(CustomerAddress)
            .where(CustomerAddress.customer_id == cid)
            .order_by(CustomerAddress.is_default.desc(), CustomerAddress.created_at)
        )
        return next(iter(rows), None)

    async def order_salesperson(self, invoice: Invoice) -> uuid.UUID | None:
        """Best available salesperson: the linked sales order's salesperson, else whoever
        raised the invoice (POS bike sales carry no sales order)."""
        if invoice.sales_order_id is not None:
            sp = await self.session.scalar(
                select(SalesOrder.salesperson_id).where(SalesOrder.id == invoice.sales_order_id)
            )
            if sp is not None:
                return sp
        return invoice.created_by

    async def unit_handover(self, tenant_id: uuid.UUID, unit_id: uuid.UUID) -> CustomerHandover | None:
        """An existing handover for this unit (enforces one-per-unit with a friendly error
        before the DB unique constraint would fire)."""
        return await self.session.scalar(
            select(CustomerHandover).where(
                CustomerHandover.tenant_id == tenant_id, CustomerHandover.unit_id == unit_id
            )
        )

    async def find_sold_unit_by_chassis(
        self, tenant_id: uuid.UUID, chassis: str
    ) -> MotorcycleUnit | None:
        """Locate a unit by exact chassis/VIN (case-insensitive) for the 'scan chassis'
        entry point. Returns the unit regardless of status; the service validates it."""
        return await self.session.scalar(
            select(MotorcycleUnit).where(
                MotorcycleUnit.tenant_id == tenant_id,
                text("lower(motorcycle_units.chassis_number) = lower(:c)").bindparams(c=chassis),
            )
        )

    async def list_handovers(
        self,
        *,
        branch_ids: list[uuid.UUID] | None,
        status: str | None,
        date_from: dt.date | None,
        date_to: dt.date | None,
        search: str | None,
        limit: int = 100,
    ) -> list[CustomerHandover]:
        stmt = select(CustomerHandover)
        if branch_ids is not None:
            stmt = stmt.where(CustomerHandover.branch_id.in_(branch_ids))
        if status:
            stmt = stmt.where(CustomerHandover.status == status)
        if date_from is not None:
            stmt = stmt.where(CustomerHandover.delivery_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(CustomerHandover.delivery_date <= date_to)
        if search:
            like = f"%{search.strip()}%"
            # handover_no / customer name are on the row; chassis lives on the unit.
            unit_ids = select(MotorcycleUnit.id).where(MotorcycleUnit.chassis_number.ilike(like))
            stmt = stmt.where(
                or_(
                    CustomerHandover.handover_no.ilike(like),
                    CustomerHandover.full_name.ilike(like),
                    CustomerHandover.unit_id.in_(unit_ids),
                )
            )
        stmt = stmt.order_by(CustomerHandover.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    # ------------------------------ resolvers -------------------------------- #
    async def unit_context(self, unit_id: uuid.UUID) -> dict:
        """chassis / engine / model name / colour name for one unit."""
        row = (
            await self.session.execute(
                select(
                    MotorcycleUnit.chassis_number,
                    MotorcycleUnit.engine_number,
                    MotorcycleModel.name,
                    MotorcycleColour.name,
                )
                .join(MotorcycleModel, MotorcycleModel.id == MotorcycleUnit.model_id)
                .outerjoin(MotorcycleColour, MotorcycleColour.id == MotorcycleUnit.colour_id)
                .where(MotorcycleUnit.id == unit_id)
            )
        ).first()
        if row is None:
            return {}
        return {
            "chassis_number": row[0],
            "engine_number": row[1],
            "model_name": row[2],
            "colour_name": row[3],
        }

    async def branch_name(self, bid: uuid.UUID | None) -> str | None:
        if bid is None:
            return None
        return await self.session.scalar(select(Branch.name).where(Branch.id == bid))

    async def user_display(self, uid: uuid.UUID | None) -> str | None:
        if uid is None:
            return None
        return await self.session.scalar(select(User.full_name).where(User.id == uid))

    async def invoice_number(self, iid: uuid.UUID | None) -> str | None:
        if iid is None:
            return None
        return await self.session.scalar(select(Invoice.invoice_number).where(Invoice.id == iid))
