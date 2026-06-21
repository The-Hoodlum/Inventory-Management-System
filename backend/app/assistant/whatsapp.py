"""WhatsApp channel adapter + Meta Cloud API readiness.

The assistant engine (``AssistantService``) is channel-agnostic: inbound messages are
normalised to ``schemas.WhatsAppInbound`` and outbound replies go through a
``WhatsAppAdapter``. Swapping the mock for Meta's Cloud API is purely a config change
(``WHATSAPP_PROVIDER=cloud`` + credentials) via ``build_whatsapp_adapter`` — no engine
or handler code changes. ``normalize_inbound`` turns a Meta webhook payload into the
same ``WhatsAppInbound`` the mock endpoint already uses, so one handler serves both.
"""
from __future__ import annotations

import abc

from app.assistant.schemas import WhatsAppInbound
from app.core.logging import get_logger

logger = get_logger(__name__)


class WhatsAppAdapter(abc.ABC):
    @abc.abstractmethod
    async def send(self, *, to: str, text: str) -> None:
        """Deliver a message to a phone number (free-form reply or approved template)."""


class MockWhatsAppAdapter(WhatsAppAdapter):
    """Records outbound messages instead of calling Meta — for local testing/alerts."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, text: str) -> None:
        self.sent.append({"to": to, "text": text})
        logger.info("whatsapp_mock_send", to=to, chars=len(text))


class CloudWhatsAppAdapter(WhatsAppAdapter):
    """Meta WhatsApp Cloud API. Free-form replies are allowed only within the 24-hour
    customer-service window; business-initiated/proactive messages require pre-approved
    templates. Credentials come from settings; the engine is unaware of this class."""

    def __init__(self, *, phone_number_id: str, access_token: str, api_base_url: str,
                 timeout_seconds: float = 15.0) -> None:
        self._url = f"{api_base_url.rstrip('/')}/{phone_number_id}/messages"
        self._token = access_token
        self._timeout = timeout_seconds

    def __repr__(self) -> str:  # never leak the token
        return "CloudWhatsAppAdapter(token=***redacted***)"

    async def send(self, *, to: str, text: str) -> None:
        import httpx

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.warning("whatsapp_cloud_send_failed", status=resp.status_code)
        except Exception as exc:  # noqa: BLE001 — delivery is best-effort; never crash the caller
            logger.warning("whatsapp_cloud_send_error", error_type=type(exc).__name__)


def build_whatsapp_adapter(settings) -> WhatsAppAdapter:
    """Select the adapter from config. 'cloud' when configured, else the mock."""
    if getattr(settings, "whatsapp_provider", "mock") == "cloud" and settings.whatsapp_cloud_configured:
        return CloudWhatsAppAdapter(
            phone_number_id=settings.whatsapp_phone_number_id,
            access_token=settings.whatsapp_access_token,
            api_base_url=settings.whatsapp_api_base_url,
        )
    return MockWhatsAppAdapter()


def normalize_inbound(payload: dict) -> WhatsAppInbound | None:
    """Convert a Meta WhatsApp Cloud webhook payload into a WhatsAppInbound.

    Returns None for non-message events (delivery/read status callbacks, etc.) and for
    non-text messages, which the text assistant can't act on yet.
    """
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    if msg.get("type") == "text":
                        body = (msg.get("text") or {}).get("body", "").strip()
                        sender = msg.get("from", "").strip()
                        if body and sender:
                            return WhatsAppInbound(from_=sender, text=body)
    except (AttributeError, TypeError):
        return None
    return None
