"""Customer service: create / update / delete / get / list, with audit and derived
outstanding balance. Codes are auto-generated (CUST-00001) when not supplied."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Customer, CustomerAddress
from app.repositories.audit_repo import AuditRepository
from app.repositories.customer_repo import CustomerRepository
from app.schemas.customer import (
    CustomerAddressBase,
    CustomerCreate,
    CustomerSummaryOut,
    CustomerUpdate,
)


class CustomerService:
    def __init__(self, customers: CustomerRepository, audit: AuditRepository) -> None:
        self.customers = customers
        self.audit = audit

    async def create(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, data: CustomerCreate
    ) -> Customer:
        code = (data.code or "").strip() or await self.customers.next_code(tenant_id)
        if await self.customers.get_by_code(code):
            raise ConflictError(f"A customer with code '{code}' already exists")
        fields = data.model_dump(exclude={"code", "addresses"})
        customer = Customer(tenant_id=tenant_id, code=code, **fields)
        for addr in data.addresses:
            customer.addresses.append(CustomerAddress(tenant_id=tenant_id, **addr.model_dump()))
        await self.customers.create(customer)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="create", entity_type="customer",
            entity_id=customer.id, changes={"code": code, "name": customer.name},
        )
        return customer

    async def get(self, customer_id: uuid.UUID) -> Customer:
        customer = await self.customers.get(customer_id)
        if customer is None:
            raise NotFoundError("Customer not found")
        return customer

    async def get_summary(self, customer_id: uuid.UUID) -> CustomerSummaryOut:
        customer = await self.get(customer_id)
        out = CustomerSummaryOut.model_validate(customer)
        out.outstanding_balance = await self.customers.outstanding_balance(customer_id)
        limit = float(customer.credit_limit or Decimal("0"))
        out.available_credit = (limit - out.outstanding_balance) if limit > 0 else None
        return out

    async def update(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, customer_id: uuid.UUID, data: CustomerUpdate
    ) -> Customer:
        customer = await self.get(customer_id)
        changes = data.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(customer, field, value)
        await self.customers.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="update", entity_type="customer",
            entity_id=customer.id, changes={"fields": sorted(changes)},
        )
        return customer

    async def add_address(
        self, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, data: CustomerAddressBase
    ) -> Customer:
        customer = await self.get(customer_id)
        self.customers.session.add(
            CustomerAddress(tenant_id=tenant_id, customer_id=customer.id, **data.model_dump())
        )
        await self.customers.session.flush()
        return await self.get(customer_id)

    async def delete(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, customer_id: uuid.UUID) -> None:
        customer = await self.get(customer_id)
        cid = customer.id
        try:
            await self.customers.delete(customer)
        except IntegrityError as exc:
            raise ConflictError(
                "Cannot delete a customer with sales documents; deactivate it instead."
            ) from exc
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="delete", entity_type="customer",
            entity_id=cid, changes={"deleted": True},
        )

    async def list(
        self, *, search: str | None = None, active_only: bool = False, page: int = 1, page_size: int = 50
    ) -> tuple[list[Customer], int]:
        return await self.customers.list(
            search=search, active_only=active_only, page=page, page_size=page_size
        )
