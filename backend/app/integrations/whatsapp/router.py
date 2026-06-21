"""WhatsApp webhook routes (mounted at /api/v1/whatsapp).

Unauthenticated — Meta calls these. GET verifies the subscription with the configured
verify token; POST receives messages and delegates to AssistantService. Always returns
HTTP 200 on POST so Meta does not retry. Production note: also verify the
X-Hub-Signature-256 header before processing inbound payloads.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.api.v1.deps import get_whatsapp_channel_service
from app.integrations.whatsapp.schemas import WebhookAck
from app.integrations.whatsapp.service import WhatsAppChannelService

router = APIRouter()


@router.get("/webhook", include_in_schema=False)
async def verify_webhook(
    request: Request,
    svc: WhatsAppChannelService = Depends(get_whatsapp_channel_service),
) -> PlainTextResponse:
    p = request.query_params
    challenge = svc.verify(
        mode=p.get("hub.mode"), token=p.get("hub.verify_token"), challenge=p.get("hub.challenge")
    )
    if challenge is None:
        raise HTTPException(status_code=403, detail="verification failed")
    return PlainTextResponse(challenge)


@router.post("/webhook", response_model=WebhookAck)
async def receive_webhook(
    request: Request,
    svc: WhatsAppChannelService = Depends(get_whatsapp_channel_service),
) -> WebhookAck:
    payload = await request.json()
    return await svc.handle_webhook(payload)
