"""WhatsApp webhook routes (mounted at /api/v1/whatsapp).

No bearer auth — Meta calls these. GET verifies the subscription with the configured verify
token; POST is authenticated by the X-Hub-Signature-256 HMAC over the RAW request body
(keyed with the Meta app secret) and then delegates to AssistantService. Beyond that
signature check, POST always returns HTTP 200 so Meta does not retry.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.api.v1.deps import get_whatsapp_channel_service
from app.core.logging import get_logger
from app.integrations.whatsapp.schemas import WebhookAck
from app.integrations.whatsapp.service import WhatsAppChannelService
from app.integrations.whatsapp.utils import SIGNATURE_HEADER

logger = get_logger(__name__)
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
    # Authenticate FIRST, against the raw bytes — re-serialising the parsed JSON would not
    # reproduce Meta's exact payload and the HMAC would never match.
    body = await request.body()
    if not svc.verify_signature(body=body, header=request.headers.get(SIGNATURE_HEADER)):
        logger.warning("whatsapp_bad_signature")
        raise HTTPException(status_code=403, detail="invalid signature")
    try:
        payload = json.loads(body)
    except ValueError:
        return WebhookAck(status="ignored")   # not JSON; nothing to route
    return await svc.handle_webhook(payload)
