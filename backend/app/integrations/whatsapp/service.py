"""WhatsApp channel service — transport + formatting only.

Validates/parses inbound WhatsApp webhooks, hands the text to the single
``AssistantService`` (which owns the LLM, tools, prompt, and business logic), and sends
the reply back via the WhatsApp adapter. Contains NO business logic and NO second AI.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.service import AssistantService
from app.assistant.whatsapp import WhatsAppAdapter
from app.core.logging import get_logger
from app.integrations.whatsapp.schemas import SendResult, WebhookAck
from app.integrations.whatsapp.utils import (
    parse_inbound,
    verify_signature,
    verify_subscription,
)

logger = get_logger(__name__)


class WhatsAppChannelService:
    def __init__(
        self, *, assistant: AssistantService, adapter: WhatsAppAdapter, session: AsyncSession,
        default_tenant_id: str | None, verify_token: str | None, app_secret: str | None = None,
    ) -> None:
        self._assistant = assistant
        self._adapter = adapter
        self._session = session
        self._default_tenant_id = default_tenant_id
        self._verify_token = verify_token
        self._app_secret = app_secret

    # ----------------------------- verification ------------------------ #
    def verify(self, *, mode: str | None, token: str | None, challenge: str | None) -> str | None:
        return verify_subscription(mode=mode, token=token, challenge=challenge,
                                   verify_token=self._verify_token)

    def verify_signature(self, *, body: bytes, header: str | None) -> bool:
        """Authenticate an inbound webhook against the Meta app secret. True when the
        request is genuine (or when no app secret is configured, i.e. verification off)."""
        return verify_signature(body=body, header=header, app_secret=self._app_secret)

    # ------------------------------- outbound -------------------------- #
    async def send_text_message(self, to: str, text_body: str) -> SendResult:
        """Send a free-form text reply (Graph API via the configured adapter)."""
        try:
            await self._adapter.send(to=to, text=text_body)
            return SendResult(ok=True, to=to)
        except Exception as exc:  # noqa: BLE001 — adapter is best-effort; report, don't raise
            logger.warning("whatsapp_send_failed", error_type=type(exc).__name__)
            return SendResult(ok=False, to=to, error=type(exc).__name__)

    # ------------------------------- inbound --------------------------- #
    async def handle_webhook(self, payload: dict) -> WebhookAck:
        msg = parse_inbound(payload)
        if msg is None:
            return WebhookAck(status="ignored")  # status callback or non-text message
        logger.info(
            "whatsapp_message_received",
            sender=msg.sender, message_id=msg.message_id,
            ts=msg.timestamp.isoformat() if msg.timestamp else None, chars=len(msg.text),
        )
        if not self._default_tenant_id:
            # Acknowledged but not routed — set WHATSAPP_DEFAULT_TENANT_ID to enable replies.
            logger.info("whatsapp_unrouted")
            return WebhookAck(status="received")
        try:
            await self._session.execute(
                text("SELECT set_config('app.current_tenant', :t, true)"),
                {"t": self._default_tenant_id},
            )
            reply = await self._assistant.whatsapp_reply(
                tenant_id=uuid.UUID(self._default_tenant_id), phone=msg.sender, text=msg.text
            )
            await self.send_text_message(msg.sender, reply.reply)
            return WebhookAck(status="processed")
        except Exception as exc:  # noqa: BLE001 — never 500 Meta; it would retry endlessly
            logger.warning("whatsapp_handle_failed", error_type=type(exc).__name__)
            return WebhookAck(status="received")
