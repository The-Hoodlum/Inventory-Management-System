"""Supplier endpoints: create, list, get, update, delete."""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.v1.deps import CurrentUser, get_supplier_service, require_permission
from app.core.permissions import P
from app.schemas.common import Page
from app.schemas.supplier import (
    SupplierCreate,
    SupplierOut,
    SupplierStatus,
    SupplierUpdate,
)
from app.services.supplier_service import SupplierService

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    payload: SupplierCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.SUPPLIER_CREATE)),
    svc: SupplierService = Depends(get_supplier_service),
) -> SupplierOut:
    supplier = await svc.create(
        tenant_id=user.tenant_id, user_id=user.id, data=payload, ip=_ip(request)
    )
    return SupplierOut.model_validate(supplier)


@router.get("", response_model=Page[SupplierOut])
async def list_suppliers(
    search: str | None = Query(default=None, description="Match name, contact, or email"),
    status_: SupplierStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.SUPPLIER_READ)),
    svc: SupplierService = Depends(get_supplier_service),
) -> Page[SupplierOut]:
    items, total = await svc.list(
        search=search, status=status_, page=page, page_size=page_size
    )
    return Page[SupplierOut](
        items=[SupplierOut.model_validate(s) for s in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{supplier_id}", response_model=SupplierOut)
async def get_supplier(
    supplier_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.SUPPLIER_READ)),
    svc: SupplierService = Depends(get_supplier_service),
) -> SupplierOut:
    return SupplierOut.model_validate(await svc.get(supplier_id))


@router.patch("/{supplier_id}", response_model=SupplierOut)
async def update_supplier(
    supplier_id: uuid.UUID,
    payload: SupplierUpdate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.SUPPLIER_UPDATE)),
    svc: SupplierService = Depends(get_supplier_service),
) -> SupplierOut:
    supplier = await svc.update(
        tenant_id=user.tenant_id,
        user_id=user.id,
        supplier_id=supplier_id,
        data=payload,
        ip=_ip(request),
    )
    return SupplierOut.model_validate(supplier)


@router.delete("/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_supplier(
    supplier_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.SUPPLIER_UPDATE)),
    svc: SupplierService = Depends(get_supplier_service),
) -> Response:
    await svc.delete(
        tenant_id=user.tenant_id,
        user_id=user.id,
        supplier_id=supplier_id,
        ip=_ip(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
