"""Assistant endpoints (mounted at /api/v1/assistant).

Phase 1: a channel-agnostic engine exposed via `POST /ask` (authenticated user) and a
`POST /whatsapp/mock` that simulates an inbound WhatsApp message (phone -> user via
whatsapp_identities) so the whole flow is testable before the Meta Cloud API is wired.
Both require the `assistant.use` permission.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    get_assistant_service,
    get_current_user,
    get_db,
    require_permission,
)
from app.assistant.repository import AssistantRepository
from app.assistant.schemas import AskRequest, AskResponse, WhatsAppInbound, WhatsAppReply
from app.assistant.service import AssistantService
from app.assistant.whatsapp import build_whatsapp_adapter, normalize_inbound
from app.core.config import settings
from app.core.logging import get_logger
from app.core.permissions import P

logger = get_logger(__name__)
router = APIRouter()


@router.post("/ask", response_model=AskResponse)
async def ask(
    payload: AskRequest,
    user: CurrentUser = Depends(require_permission(P.ASSISTANT_USE)),
    svc: AssistantService = Depends(get_assistant_service),
) -> AskResponse:
    return await svc.ask(
        tenant_id=user.tenant_id, user_id=user.id, question=payload.question, channel="api"
    )


class NotificationOut(BaseModel):
    kind: str
    severity: str  # 'info' | 'warning' | 'critical'
    title: str
    detail: str | None = None
    count: int
    href: str  # frontend route the bell links to


class NotificationsOut(BaseModel):
    total: int
    items: list[NotificationOut]


@router.get("/notifications", response_model=NotificationsOut)
async def notifications(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationsOut:
    """Operational alerts for the shell's notifications bell — derived from EXISTING
    data (low stock, pending approvals) via the RLS-scoped assistant repository. Each
    source is gated by the relevant read permission, so users only see what they can act
    on. This reuses the same signals the WhatsApp alert scheduler broadcasts."""
    repo = AssistantRepository(db)
    warehouse_ids = await repo.all_warehouse_ids()
    perms = user.permissions
    items: list[NotificationOut] = []

    if perms & {P.INVENTORY_READ, P.REORDER_READ}:
        low = await repo.low_stock(warehouse_ids)
        if low["count"]:
            preview = ", ".join(f"{i['name']} ({i['branch']})" for i in low["items"][:3])
            items.append(NotificationOut(
                kind="low_stock", severity="warning",
                title=f"{low['count']} item(s) at or below reorder point",
                detail=preview or None, count=low["count"], href="/reorder",
            ))

    if perms & {P.PO_READ, P.PO_APPROVE}:
        pending_po = await repo.pending_purchase_requests(warehouse_ids)
        if pending_po["count"]:
            items.append(NotificationOut(
                kind="pending_purchase_request", severity="info",
                title=f"{pending_po['count']} purchase request(s) awaiting approval",
                count=pending_po["count"], href="/purchase-orders",
            ))

    if perms & {P.ORDER_REQUEST_READ, P.ORDER_REQUEST_APPROVE}:
        pending_or = await repo.pending_order_requests(warehouse_ids)
        if pending_or["count"]:
            items.append(NotificationOut(
                kind="pending_order_request", severity="info",
                title=f"{pending_or['count']} order request(s) awaiting approval",
                count=pending_or["count"], href="/order-requests",
            ))

    return NotificationsOut(total=sum(i.count for i in items), items=items)


@router.post("/whatsapp/mock", response_model=WhatsAppReply)
async def whatsapp_mock(
    payload: WhatsAppInbound,
    user: CurrentUser = Depends(require_permission(P.ASSISTANT_USE)),
    svc: AssistantService = Depends(get_assistant_service),
) -> WhatsAppReply:
    # Simulates Meta's inbound webhook: route a phone-number message through the engine.
    # The real Cloud API webhook (below) normalises to the same WhatsAppInbound shape.
    return await svc.whatsapp_reply(tenant_id=user.tenant_id, phone=payload.from_, text=payload.text)


# --------------------------------------------------------------------------- #
# Meta WhatsApp Cloud API webhook (unauthenticated — Meta calls it).
# Inert until configured: GET verifies with WHATSAPP_VERIFY_TOKEN; POST only routes
# when WHATSAPP_DEFAULT_TENANT_ID is set. The engine (whatsapp_reply) is unchanged —
# this handler just normalises Meta's payload and replies via the cloud adapter.
# Production note: also verify the X-Hub-Signature-256 header before processing.
# --------------------------------------------------------------------------- #
@router.get("/whatsapp/webhook", include_in_schema=False)
async def whatsapp_webhook_verify(request: Request) -> PlainTextResponse:
    p = request.query_params
    if (
        p.get("hub.mode") == "subscribe"
        and settings.whatsapp_verify_token
        and p.get("hub.verify_token") == settings.whatsapp_verify_token
    ):
        return PlainTextResponse(p.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    svc: AssistantService = Depends(get_assistant_service),
) -> dict:
    payload = await request.json()
    inbound = normalize_inbound(payload)
    if inbound is None:
        return {"status": "ignored"}  # status callback or non-text message
    tenant_id = settings.whatsapp_default_tenant_id
    if not tenant_id:
        logger.info("whatsapp_webhook_unrouted")  # acknowledged but no tenant configured
        return {"status": "received"}
    await db.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": tenant_id})
    reply = await svc.whatsapp_reply(tenant_id=uuid.UUID(tenant_id), phone=inbound.from_, text=inbound.text)
    await build_whatsapp_adapter(settings).send(to=inbound.from_, text=reply.reply)
    return {"status": "processed"}
