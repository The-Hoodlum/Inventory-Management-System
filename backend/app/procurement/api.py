"""HTTP endpoints for purchase-order management and goods receiving.

Mounted by the v1 aggregator at /api/v1/purchase-orders. RBAC is enforced per
route via ``require_permission`` (see PROCUREMENT_MODULE.md for the mapping).
"""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.v1.deps import CurrentUser, get_procurement_service, require_permission
from app.core.permissions import P
from app.procurement.schemas import (
    EmailPORequest,
    EmailResult,
    POActionRequest,
    POCreate,
    POEventOut,
    POOut,
    POUpdate,
    ReceiptResult,
    ReceiveRequest,
)
from app.procurement.service import ProcurementService
from app.schemas.common import Page

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# --------------------------------- create ---------------------------------- #
@router.post("", response_model=POOut, status_code=201)
async def create_purchase_order(
    payload: POCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PO_CREATE)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> POOut:
    return await svc.create_po(
        tenant_id=user.tenant_id, user_id=user.id, data=payload, ip=_ip(request)
    )


# ---------------------------------- read ------------------------------------ #
@router.get("", response_model=Page[POOut])
async def list_purchase_orders(
    status_: str | None = Query(default=None, alias="status"),
    supplier_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_permission(P.PO_READ)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> Page[POOut]:
    items, total = await svc.list_pos(
        status=status_, supplier_id=supplier_id, warehouse_id=warehouse_id,
        page=page, page_size=page_size,
    )
    return Page[POOut](
        items=[svc._po_out(po, []) for po in items],  # list view omits lines (avoids N+1)
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{po_id}", response_model=POOut)
async def get_purchase_order(
    po_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.PO_READ)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> POOut:
    return await svc.get_po(po_id)


@router.get("/{po_id}/events", response_model=list[POEventOut])
async def list_purchase_order_events(
    po_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.PO_READ)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> list[POEventOut]:
    events = await svc.list_events(po_id)
    return [POEventOut.model_validate(e) for e in events]


# --------------------------------- update ----------------------------------- #
@router.patch("/{po_id}", response_model=POOut)
async def update_purchase_order(
    po_id: uuid.UUID,
    payload: POUpdate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PO_UPDATE)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> POOut:
    return await svc.update_po(
        tenant_id=user.tenant_id, user_id=user.id, po_id=po_id, data=payload, ip=_ip(request)
    )


# --------------------------- approval workflow ------------------------------ #
@router.post("/{po_id}/submit", response_model=POOut)
async def submit_purchase_order(
    po_id: uuid.UUID,
    payload: POActionRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PO_CREATE)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> POOut:
    return await svc.submit(
        po_id=po_id, comment=payload.comment, actor=user.id, tenant=user.tenant_id, ip=_ip(request)
    )


@router.post("/{po_id}/approve", response_model=POOut)
async def approve_purchase_order(
    po_id: uuid.UUID,
    payload: POActionRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PO_APPROVE)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> POOut:
    return await svc.approve(
        po_id=po_id, comment=payload.comment, actor=user.id, tenant=user.tenant_id, ip=_ip(request)
    )


@router.post("/{po_id}/reject", response_model=POOut)
async def reject_purchase_order(
    po_id: uuid.UUID,
    payload: POActionRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PO_APPROVE)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> POOut:
    return await svc.reject(
        po_id=po_id, comment=payload.comment, actor=user.id, tenant=user.tenant_id, ip=_ip(request)
    )


@router.post("/{po_id}/cancel", response_model=POOut)
async def cancel_purchase_order(
    po_id: uuid.UUID,
    payload: POActionRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PO_UPDATE)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> POOut:
    return await svc.cancel(
        po_id=po_id, comment=payload.comment, actor=user.id, tenant=user.tenant_id, ip=_ip(request)
    )


@router.post("/{po_id}/send", response_model=POOut)
async def send_purchase_order(
    po_id: uuid.UUID,
    payload: POActionRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PO_APPROVE)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> POOut:
    return await svc.send(
        po_id=po_id, comment=payload.comment, actor=user.id, tenant=user.tenant_id, ip=_ip(request)
    )


# ------------------------------- receiving ---------------------------------- #
@router.post("/{po_id}/receipts", response_model=ReceiptResult)
async def receive_goods(
    po_id: uuid.UUID,
    payload: ReceiveRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.INVENTORY_RECEIVE)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> ReceiptResult:
    return await svc.receive(
        tenant_id=user.tenant_id, user_id=user.id, po_id=po_id, req=payload, ip=_ip(request)
    )


# ------------------------------- pdf & email -------------------------------- #
@router.get("/{po_id}/pdf")
async def purchase_order_pdf(
    po_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.PO_READ)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> Response:
    pdf_bytes = await svc.build_pdf(po_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="PO-{po_id}.pdf"'},
    )


@router.post("/{po_id}/email", response_model=EmailResult)
async def email_purchase_order(
    po_id: uuid.UUID,
    payload: EmailPORequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.PO_APPROVE)),
    svc: ProcurementService = Depends(get_procurement_service),
) -> EmailResult:
    return await svc.email_po(
        tenant_id=user.tenant_id, user_id=user.id, po_id=po_id, req=payload, ip=_ip(request)
    )
