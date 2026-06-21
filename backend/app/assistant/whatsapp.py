"""WhatsApp channel adapter.

The assistant engine is channel-agnostic. Inbound messages are normalised to
``schemas.WhatsAppInbound`` and outbound replies go through ``WhatsAppAdapter.send``.
Phase 1 ships ``MockWhatsAppAdapter`` (records sends; the reply is returned over HTTP
so we can test without Meta). Phase 2 swaps in ``CloudWhatsAppAdapter`` (Meta
WhatsApp Cloud API) with NO change to the engine or the API handlers.
"""
from __future__ import annotations

import abc


class WhatsAppAdapter(abc.ABC):
    @abc.abstractmethod
    async def send(self, *, to: str, text: str) -> None:
        """Deliver a message to a phone number (free-form reply or approved template)."""


class MockWhatsAppAdapter(WhatsAppAdapter):
    """Records outbound messages instead of calling Meta — for local testing."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, text: str) -> None:
        self.sent.append({"to": to, "text": text})


class CloudWhatsAppAdapter(WhatsAppAdapter):
    """Phase 2: Meta WhatsApp Cloud API. Free-form replies are allowed only within the
    24-hour customer-service window; business-initiated/proactive messages require
    pre-approved templates. Not implemented yet."""

    def __init__(self, *, phone_number_id: str, access_token: str) -> None:
        self._phone_number_id = phone_number_id
        self._access_token = access_token

    async def send(self, *, to: str, text: str) -> None:  # pragma: no cover - Phase 2
        raise NotImplementedError("CloudWhatsAppAdapter lands in Phase 2 (needs a Meta account).")
