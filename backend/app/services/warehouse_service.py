"""Warehouse service: create / update / delete / get / list, with audit.

Warehouses have no soft-delete column. Deletion is a hard delete, but the
database FKs (RESTRICT from stock_movements / purchase_orders) prevent removing a
warehouse that has history — that surfaces here as a 409 with a clear message.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Warehouse
from app.repositories.audit_repo import AuditRepository
from app.repositories.warehouse_repo import WarehouseRepository
from app.schemas.warehouse import WarehouseCreate, WarehouseUpdate

_AUDITED_FIELDS = ("code", "name", "address", "is_active")


def _snapshot(w: Warehouse) -> dict[str, Any]:
    return {f: getattr(w, f) for f in _AUDITED_FIELDS}


class WarehouseService:
    def __init__(self, warehouses: WarehouseRepository, audit: AuditRepository) -> None:
        self.warehouses = warehouses
        self.audit = audit

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: WarehouseCreate,
        ip: str | None = None,
    ) -> Warehouse:
        if await self.warehouses.get_by_code(data.code):
            raise ConflictError(f"A warehouse with code '{data.code}' already exists")
        warehouse = Warehouse(tenant_id=tenant_id, **data.model_dump())
        await self.warehouses.add(warehouse)
        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="create",
            entity_type="warehouse",
            entity_id=warehouse.id,
            changes={"after": _snapshot(warehouse)},
            ip_address=ip,
        )
        return warehouse

    async def get(self, warehouse_id: uuid.UUID) -> Warehouse:
        warehouse = await self.warehouses.get(warehouse_id)
        if warehouse is None:
            raise NotFoundError("Warehouse not found")
        return warehouse

    async def update(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        data: WarehouseUpdate,
        ip: str | None = None,
    ) -> Warehouse:
        warehouse = await self.get(warehouse_id)
        changes = data.model_dump(exclude_unset=True)
        if "code" in changes and changes["code"] != warehouse.code:
            if await self.warehouses.get_by_code(changes["code"]):
                raise ConflictError(f"A warehouse with code '{changes['code']}' already exists")
        before = _snapshot(warehouse)
        for field, value in changes.items():
            setattr(warehouse, field, value)
        await self.warehouses.session.flush()
        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="update",
            entity_type="warehouse",
            entity_id=warehouse.id,
            changes={"before": before, "after": _snapshot(warehouse)},
            ip_address=ip,
        )
        return warehouse

    async def delete(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        ip: str | None = None,
    ) -> None:
        warehouse = await self.get(warehouse_id)
        wid = warehouse.id
        try:
            await self.warehouses.delete(warehouse)
        except IntegrityError as exc:
            raise ConflictError(
                "Cannot delete a warehouse that has stock or order history; "
                "deactivate it instead (set is_active = false)."
            ) from exc
        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="delete",
            entity_type="warehouse",
            entity_id=wid,
            changes={"deleted": True},
            ip_address=ip,
        )

    async def list(
        self,
        *,
        active_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Warehouse], int]:
        return await self.warehouses.list(
            active_only=active_only, page=page, page_size=page_size
        )
