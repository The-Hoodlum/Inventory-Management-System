"""Branch -> customer/reseller delivery endpoints (mounted at /api/v1/customer-deliveries)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response

from app.api.v1.deps import CurrentUser, get_customer_delivery_service, require_permission
from app.core.permissions import P
from app.customer_delivery.schemas import (
    CancelBody,
    CustomerDeliveryCreate,
    CustomerDeliveryOut,
    CustomerDeliverySettle,
    DeliverBody,
)
from app.customer_delivery.service import CustomerDeliveryService

router = APIRouter()


@router.post("", response_model=CustomerDeliveryOut, status_code=201)
async def create_delivery(
    payload: CustomerDeliveryCreate,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_DISPATCH)),
    svc: CustomerDeliveryService = Depends(get_customer_delivery_service),
) -> CustomerDeliveryOut:
    return await svc.create(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("", response_model=list[CustomerDeliveryOut])
async def list_deliveries(
    customer_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    mode: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_READ)),
    svc: CustomerDeliveryService = Depends(get_customer_delivery_service),
) -> list[CustomerDeliveryOut]:
    return await svc.list_deliveries(customer_id=customer_id, status=status_filter, mode=mode, limit=limit)


@router.get("/{delivery_id}", response_model=CustomerDeliveryOut)
async def get_delivery(
    delivery_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_READ)),
    svc: CustomerDeliveryService = Depends(get_customer_delivery_service),
) -> CustomerDeliveryOut:
    return await svc.get(delivery_id)


@router.post("/{delivery_id}/deliver", response_model=CustomerDeliveryOut)
async def deliver_delivery(
    delivery_id: uuid.UUID,
    payload: DeliverBody,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_DISPATCH)),
    svc: CustomerDeliveryService = Depends(get_customer_delivery_service),
) -> CustomerDeliveryOut:
    return await svc.deliver(tenant_id=user.tenant_id, user_id=user.id, delivery_id=delivery_id, received_by=payload.received_by)


@router.post("/{delivery_id}/settle", response_model=CustomerDeliveryOut)
async def settle_delivery(
    delivery_id: uuid.UUID,
    payload: CustomerDeliverySettle,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_RECEIVE)),
    svc: CustomerDeliveryService = Depends(get_customer_delivery_service),
) -> CustomerDeliveryOut:
    return await svc.settle(tenant_id=user.tenant_id, user_id=user.id, delivery_id=delivery_id, payload=payload)


@router.post("/{delivery_id}/cancel", response_model=CustomerDeliveryOut)
async def cancel_delivery(
    delivery_id: uuid.UUID,
    payload: CancelBody,
    user: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_DISPATCH)),
    svc: CustomerDeliveryService = Depends(get_customer_delivery_service),
) -> CustomerDeliveryOut:
    return await svc.cancel(tenant_id=user.tenant_id, user_id=user.id, delivery_id=delivery_id, reason=payload.reason)


@router.get("/{delivery_id}/pdf")
async def delivery_pdf(
    delivery_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.DELIVERY_NOTE_READ)),
    svc: CustomerDeliveryService = Depends(get_customer_delivery_service),
) -> Response:
    from app.customer_delivery.pdf import build_customer_delivery_pdf

    cd = await svc.get(delivery_id)
    pdf = build_customer_delivery_pdf(cd)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{cd.delivery_number}.pdf"'})
