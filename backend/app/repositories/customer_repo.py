"""Customer repository: get / list / create (with addresses + auto code) / delete,
plus derived outstanding balance from unpaid invoices."""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, CustomerAddress, Invoice


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_code(self, tenant_id: uuid.UUID) -> str:
        return await self.session.scalar(
            text("SELECT next_customer_number(CAST(:t AS uuid))"), {"t": str(tenant_id)}
        )

    async def get(self, customer_id: uuid.UUID) -> Customer | None:
        return await self.session.scalar(select(Customer).where(Customer.id == customer_id))

    async def get_by_code(self, code: str) -> Customer | None:
        return await self.session.scalar(select(Customer).where(Customer.code == code))

    async def create(self, customer: Customer) -> Customer:
        self.session.add(customer)
        await self.session.flush()
        await self.session.refresh(customer)
        return customer

    async def delete(self, customer: Customer) -> None:
        await self.session.delete(customer)
        await self.session.flush()

    async def list(
        self, *, search: str | None = None, active_only: bool = False,
        page: int = 1, page_size: int = 50,
    ) -> tuple[list[Customer], int]:
        base = select(Customer)
        if active_only:
            base = base.where(Customer.is_active.is_(True))
        if search:
            like = f"%{search.strip()}%"
            base = base.where(or_(
                Customer.name.ilike(like), Customer.code.ilike(like),
                Customer.phone.ilike(like), Customer.email.ilike(like),
            ))
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        stmt = base.order_by(Customer.name).limit(page_size).offset((page - 1) * page_size)
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), int(total or 0)

    async def outstanding_balance(self, customer_id: uuid.UUID) -> float:
        """Sum of (grand_total - amount_paid) over open invoices for this customer."""
        total = await self.session.scalar(
            select(func.coalesce(func.sum(Invoice.grand_total - Invoice.amount_paid), 0))
            .where(Invoice.customer_id == customer_id, Invoice.status != "cancelled")
        )
        return float(total or 0)

    async def add_address(self, address: CustomerAddress) -> CustomerAddress:
        self.session.add(address)
        await self.session.flush()
        return address
