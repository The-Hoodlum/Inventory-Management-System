"""Customer endpoints (mounted at /api/v1/customers). Gated on the sales module."""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.v1.deps import (
    CurrentUser,
    get_customer_service,
    require_feature,
    require_permission,
)
from app.core.permissions import P
from app.schemas.common import Page
from app.schemas.customer import (
    CustomerAddressBase,
    CustomerCreate,
    CustomerOut,
    CustomerSummaryOut,
    CustomerUpdate,
)
from app.services.customer_service import CustomerService

router = APIRouter(dependencies=[Depends(require_feature("sales_orders"))])


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    user: CurrentUser = Depends(require_permission(P.CUSTOMER_MANAGE)),
    svc: CustomerService = Depends(get_customer_service),
) -> CustomerOut:
    customer = await svc.create(tenant_id=user.tenant_id, user_id=user.id, data=payload)
    return CustomerOut.model_validate(customer)


@router.get("", response_model=Page[CustomerOut])
async def list_customers(
    search: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.CUSTOMER_READ)),
    svc: CustomerService = Depends(get_customer_service),
) -> Page[CustomerOut]:
    items, total = await svc.list(search=search, active_only=active_only, page=page, page_size=page_size)
    return Page[CustomerOut](
        items=[CustomerOut.model_validate(c) for c in items],
        page=page, page_size=page_size, total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{customer_id}", response_model=CustomerSummaryOut)
async def get_customer(
    customer_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.CUSTOMER_READ)),
    svc: CustomerService = Depends(get_customer_service),
) -> CustomerSummaryOut:
    return await svc.get_summary(customer_id)


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: uuid.UUID,
    payload: CustomerUpdate,
    user: CurrentUser = Depends(require_permission(P.CUSTOMER_MANAGE)),
    svc: CustomerService = Depends(get_customer_service),
) -> CustomerOut:
    customer = await svc.update(
        tenant_id=user.tenant_id, user_id=user.id, customer_id=customer_id, data=payload
    )
    return CustomerOut.model_validate(customer)


@router.post("/{customer_id}/addresses", response_model=CustomerOut)
async def add_customer_address(
    customer_id: uuid.UUID,
    payload: CustomerAddressBase,
    user: CurrentUser = Depends(require_permission(P.CUSTOMER_MANAGE)),
    svc: CustomerService = Depends(get_customer_service),
) -> CustomerOut:
    customer = await svc.add_address(tenant_id=user.tenant_id, customer_id=customer_id, data=payload)
    return CustomerOut.model_validate(customer)


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_customer(
    customer_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.CUSTOMER_MANAGE)),
    svc: CustomerService = Depends(get_customer_service),
) -> Response:
    await svc.delete(tenant_id=user.tenant_id, user_id=user.id, customer_id=customer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
