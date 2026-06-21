"""Request/response models for the WhatsApp webhook.

Inbound Meta payloads are deeply nested and variable, so they're parsed defensively in
``utils.parse_inbound`` (returning the channel-generic ``InboundMessage``) rather than
with a strict model. These schemas cover the small, stable response surface.
"""
from __future__ import annotations

from pydantic import BaseModel


class WebhookAck(BaseModel):
    """Acknowledgement returned to Meta. Always HTTP 200 so Meta doesn't retry."""

    status: str  # processed | received | ignored


class SendResult(BaseModel):
    ok: bool
    to: str
    error: str | None = None
