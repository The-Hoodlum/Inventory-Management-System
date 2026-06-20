"""Supplier service: create / update / soft-delete / get / list, with audit."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Supplier
from app.repositories.audit_repo import AuditRepository
from app.repositories.supplier_repo import SupplierRepository
from app.schemas.supplier import SupplierCreate, SupplierUpdate

_AUDITED_FIELDS = (
    "name", "contact_person", "email", "phone", "country", "currency",
    "payment_terms", "default_lead_time_days", "status",
)


def _snapshot(s: Supplier) -> dict[str, Any]:
    return {f: (str(v) if v is not None else None) for f in _AUDITED_FIELDS for v in [getattr(s, f)]}


class SupplierService:
    def __init__(self, suppliers: SupplierRepository, audit: AuditRepository) -> None:
        self.suppliers = suppliers
        self.audit = audit

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: SupplierCreate,
        ip: str | None = None,
    ) -> Supplier:
        if await self.suppliers.get_by_name(data.name):
            raise ConflictError(f"A supplier named '{data.name}' already exists")
        supplier = Supplier(tenant_id=tenant_id, **data.model_dump())
        await self.suppliers.add(supplier)
        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="create",
            entity_type="supplier",
            entity_id=supplier.id,
            changes={"after": _snapshot(supplier)},
            ip_address=ip,
        )
        return supplier

    async def get(self, supplier_id: uuid.UUID) -> Supplier:
        supplier = await self.suppliers.get(supplier_id)
        if supplier is None:
            raise NotFoundError("Supplier not found")
        return supplier

    async def update(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        supplier_id: uuid.UUID,
        data: SupplierUpdate,
        ip: str | None = None,
    ) -> Supplier:
        supplier = await self.get(supplier_id)
        changes = data.model_dump(exclude_unset=True)
        if "name" in changes and changes["name"] != supplier.name:
            if await self.suppliers.get_by_name(changes["name"]):
                raise ConflictError(f"A supplier named '{changes['name']}' already exists")
        before = _snapshot(supplier)
        for field, value in changes.items():
            setattr(supplier, field, value)
        await self.suppliers.session.flush()
        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="update",
            entity_type="supplier",
            entity_id=supplier.id,
            changes={"before": before, "after": _snapshot(supplier)},
            ip_address=ip,
        )
        return supplier

    async def delete(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        supplier_id: uuid.UUID,
        ip: str | None = None,
    ) -> None:
        supplier = await self.get(supplier_id)
        supplier.deleted_at = func.now()
        await self.suppliers.session.flush()
        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="delete",
            entity_type="supplier",
            entity_id=supplier.id,
            changes={"soft_deleted": True},
            ip_address=ip,
        )

    async def list(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Supplier], int]:
        return await self.suppliers.list(
            search=search, status=status, page=page, page_size=page_size
        )
