"""Assistant endpoints (mounted at /api/v1/assistant).

Phase 1: a channel-agnostic engine exposed via `POST /ask` (authenticated user) and a
`POST /whatsapp/mock` that simulates an inbound WhatsApp message (phone -> user via
whatsapp_identities) so the whole flow is testable before the Meta Cloud API is wired.
Both require the `assistant.use` permission.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import CurrentUser, get_assistant_service, require_permission
from app.assistant.schemas import AskRequest, AskResponse, WhatsAppInbound, WhatsAppReply
from app.assistant.service import AssistantService
from app.core.permissions import P

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


@router.post("/whatsapp/mock", response_model=WhatsAppReply)
async def whatsapp_mock(
    payload: WhatsAppInbound,
    user: CurrentUser = Depends(require_permission(P.ASSISTANT_USE)),
    svc: AssistantService = Depends(get_assistant_service),
) -> WhatsAppReply:
    # Simulates Meta's inbound webhook: route a phone-number message through the engine.
    # The real Cloud API webhook (Phase 2) normalises to the same WhatsAppInbound shape.
    return await svc.whatsapp_reply(tenant_id=user.tenant_id, phone=payload.from_, text=payload.text)
