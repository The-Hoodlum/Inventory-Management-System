"""Order-request endpoints (mounted at /api/v1/order-requests).

Whole module is gated on the tenant's `order_requests` feature flag. Branch users create
+ view their own requests; approvers (admins/managers) see all and can approve/reject/issue.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import (
    CurrentUser,
    get_order_request_service,
    require_feature,
    require_permission,
)
from app.core.permissions import P
from app.order_requests.schemas import (
    ApproveRequest,
    AuditEntryOut,
    CancelRequest,
    CompleteRequest,
    IssueRequest,
    OrderRequestCreate,
    OrderRequestOut,
    ReceiveRequest,
    RejectRequest,
    TransferLedgerEntryOut,
)
from app.order_requests.service import OrderRequestService

# Every route requires the order_requests module to be enabled for the tenant.
router = APIRouter(dependencies=[Depends(require_feature("order_requests"))])


def _is_admin(user: CurrentUser) -> bool:
    return P.ORDER_REQUEST_APPROVE in user.permissions


@router.post("", response_model=OrderRequestOut, status_code=status.HTTP_201_CREATED)
async def create_request(
    payload: OrderRequestCreate,
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_CREATE)),
    svc: OrderRequestService = Depends(get_order_request_service),
) -> OrderRequestOut:
    return await svc.create(
        tenant_id=user.tenant_id, user_id=user.id, payload=payload,
        user_permissions=user.permissions, user_branch_ids=set(user.branch_ids),
    )


@router.get("", response_model=list[OrderRequestOut])
async def list_requests(
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_READ)),
    svc: OrderRequestService = Depends(get_order_request_service),
    branch_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    purpose: str | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    product_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[OrderRequestOut]:
    filters = {k: v for k, v in {
        "branch_id": branch_id, "status": status_filter, "purpose": purpose,
        "date_from": date_from, "date_to": date_to, "product_id": product_id, "limit": limit,
    }.items() if v is not None}
    return await svc.history(viewer_id=user.id, is_admin=_is_admin(user), filters=filters)


@router.get("/dashboard")
async def dashboard(
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_READ)),
    svc: OrderRequestService = Depends(get_order_request_service),
) -> dict:
    return await svc.dashboard(viewer_id=user.id, is_admin=_is_admin(user))


@router.get("/{request_id}", response_model=OrderRequestOut)
async def get_request(
    request_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_READ)),
    svc: OrderRequestService = Depends(get_order_request_service),
) -> OrderRequestOut:
    return await svc.get(request_id=request_id, viewer_id=user.id, is_admin=_is_admin(user))


@router.get("/{request_id}/audit", response_model=list[AuditEntryOut])
async def request_audit(
    request_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_READ)),
    svc: OrderRequestService = Depends(get_order_request_service),
) -> list[AuditEntryOut]:
    return await svc.audit_trail(request_id=request_id, viewer_id=user.id, is_admin=_is_admin(user))


@router.get("/{request_id}/ledger", response_model=list[TransferLedgerEntryOut])
async def request_ledger(
    request_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_READ)),
    svc: OrderRequestService = Depends(get_order_request_service),
) -> list[TransferLedgerEntryOut]:
    # The immutable per-line movement log (reserved/released/consumed/issued/received).
    return await svc.ledger(request_id=request_id, viewer_id=user.id, is_admin=_is_admin(user))


@router.post("/{request_id}/submit", response_model=OrderRequestOut)
async def submit_request(
    request_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_CREATE)),
    svc: OrderRequestService = Depends(get_order_request_service),
) -> OrderRequestOut:
    # A requester (or admin) moves their own draft to pending (submitted for approval).
    return await svc.submit(
        tenant_id=user.tenant_id, actor_id=user.id, request_id=request_id, is_admin=_is_admin(user)
    )


@router.post("/{request_id}/approve", response_model=OrderRequestOut)
async def approve_request(
    request_id: uuid.UUID,
    payload: ApproveRequest,
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_APPROVE)),
    svc: OrderRequestService = Depends(get_order_request_service),
) -> OrderRequestOut:
    return await svc.approve(tenant_id=user.tenant_id, actor_id=user.id, request_id=request_id, payload=payload)


@router.post("/{request_id}/reject", response_model=OrderRequestOut)
async def reject_request(
    request_id: uuid.UUID,
    payload: RejectRequest,
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_APPROVE)),
    svc: OrderRequestService = Depends(get_order_request_service),
) -> OrderRequestOut:
    return await svc.reject(tenant_id=user.tenant_id, actor_id=user.id, request_id=request_id, payload=payload)


@router.post("/{request_id}/issue", response_model=OrderRequestOut)
async def issue_request(
    request_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_ISSUE)),
    svc: OrderRequestService = Depends(get_order_request_service),
    payload: IssueRequest | None = None,
) -> OrderRequestOut:
    # Optional per-line quantities support a partial issue; omitting the body issues
    # the full approved (outstanding) quantity for every line.
    return await svc.issue(
        tenant_id=user.tenant_id, actor_id=user.id, request_id=request_id, payload=payload
    )


@router.post("/{request_id}/receive", response_model=OrderRequestOut)
async def receive_request(
    request_id: uuid.UUID,
    payload: ReceiveRequest,
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_RECEIVE)),
    svc: OrderRequestService = Depends(get_order_request_service),
) -> OrderRequestOut:
    # Capture per-line received/missing/damaged/extra; each line must reconcile.
    return await svc.receive(
        tenant_id=user.tenant_id, actor_id=user.id, request_id=request_id, payload=payload
    )


@router.post("/{request_id}/cancel", response_model=OrderRequestOut)
async def cancel_request(
    request_id: uuid.UUID,
    payload: CancelRequest,
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_READ)),
    svc: OrderRequestService = Depends(get_order_request_service),
) -> OrderRequestOut:
    # A requester can cancel their own request; an admin/approver can cancel any.
    # Allowed only before issue (pending / approved / partially_approved) — enforced in the service.
    return await svc.cancel(
        tenant_id=user.tenant_id, actor_id=user.id, request_id=request_id,
        is_admin=_is_admin(user), payload=payload,
    )


@router.post("/{request_id}/complete", response_model=OrderRequestOut)
async def complete_request(
    request_id: uuid.UUID,
    payload: CompleteRequest,
    user: CurrentUser = Depends(require_permission(P.ORDER_REQUEST_COMPLETE)),
    svc: OrderRequestService = Depends(get_order_request_service),
) -> OrderRequestOut:
    # Receiving user confirms receipt and closes an ISSUED request (records discrepancies).
    return await svc.complete(
        tenant_id=user.tenant_id, actor_id=user.id, request_id=request_id, payload=payload,
    )
