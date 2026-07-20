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
import re
from collections.abc import Sequence

from app.assistant.schemas import WhatsAppInbound
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Meta rejects a template parameter (error 132000/131008) that contains a newline, a tab,
# or 4+ consecutive spaces. A proactive message is therefore NOT simply the free-form text
# stuffed into one variable — every value has to be flattened first. Meta also caps a
# parameter at 1024 characters.
_PARAM_WHITESPACE = re.compile(r"\s+")
_PARAM_MAX_CHARS = 1024


def template_param(value: object, *, max_chars: int = _PARAM_MAX_CHARS) -> str:
    """Coerce a value into something Meta will accept as a template variable.

    Flattens all whitespace runs to single spaces (newlines/tabs are rejected outright) and
    truncates. Empty values become ``"-"`` because Meta also rejects blank parameters, which
    would silently fail an entire alert over one missing field like a customer's address.
    """
    text = _PARAM_WHITESPACE.sub(" ", str(value if value is not None else "")).strip()
    if not text:
        return "-"
    return text[: max_chars - 1] + "…" if len(text) > max_chars else text


def template_params(*values: object) -> list[str]:
    """Flatten an ordered set of values into Meta template parameters.

    Order matters and the COUNT must match the approved template exactly — Meta fails the
    send otherwise. Keep each call site's tuple next to the template body in docs/WHATSAPP.md.
    """
    return [template_param(v) for v in values]


class WhatsAppAdapter(abc.ABC):
    @abc.abstractmethod
    async def send(self, *, to: str, text: str) -> None:
        """Deliver a free-form message. Meta permits this only inside the 24-hour window."""

    async def send_template(
        self, *, to: str, template: str, params: Sequence[str], language: str = "en",
    ) -> None:
        """Deliver a pre-approved template — the only thing Meta accepts OUTSIDE the
        24-hour customer-service window, i.e. for anything the system initiates.

        Default implementation degrades to free-form so adapters that have no concept of
        templates (the mock) still deliver something readable.
        """
        await self.send(to=to, text=f"[{template}] " + " | ".join(params))


class MockWhatsAppAdapter(WhatsAppAdapter):
    """Records outbound messages instead of calling Meta — for local testing/alerts."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, text: str) -> None:
        self.sent.append({"to": to, "text": text})
        logger.info("whatsapp_mock_send", to=to, chars=len(text))

    async def send_template(
        self, *, to: str, template: str, params: Sequence[str], language: str = "en",
    ) -> None:
        # Record the structured form so tests can assert on template + params, not prose.
        self.sent.append({
            "to": to, "template": template, "language": language,
            "text": " | ".join(params),
        })
        logger.info("whatsapp_mock_send_template", to=to, template=template, params=len(params))


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
        await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }, kind="text")

    async def send_template(
        self, *, to: str, template: str, params: Sequence[str], language: str = "en",
    ) -> None:
        await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": language},
                # Body parameters are POSITIONAL: params[0] fills {{1}}, and the count must
                # match the approved template or Meta rejects the whole send.
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in params],
                }],
            },
        }, kind="template", template=template)

    async def _post(self, payload: dict, *, kind: str, template: str = "") -> None:
        import httpx

        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    # Log Meta's reason: a template failure is almost always a fixable
                    # config error (wrong name, wrong language, wrong parameter count),
                    # and without the body it is indistinguishable from a network fault.
                    logger.warning(
                        "whatsapp_cloud_send_failed", status=resp.status_code, kind=kind,
                        template=template, detail=resp.text[:300],
                    )
        except Exception as exc:  # noqa: BLE001 — delivery is best-effort; never crash the caller
            logger.warning("whatsapp_cloud_send_error", error_type=type(exc).__name__, kind=kind)


async def deliver(
    adapter: WhatsAppAdapter, *, to: str, text: str,
    template: str = "", params: Sequence[object] = (),
) -> None:
    """Send a SYSTEM-INITIATED message the most reliable way available.

    With a template name configured, the message goes out as that approved template — the
    only form Meta delivers outside the 24-hour window. Without one it falls back to
    free-form text, which reaches only recipients who happen to have messaged recently.

    The fallback is deliberate: templates need Meta's approval, so the platform must work
    (as it does today) before any are configured, and improve when they are. Callers pass
    BOTH forms so neither path is second-class.
    """
    if template:
        await adapter.send_template(
            to=to, template=template, params=template_params(*params),
            language=getattr(settings, "whatsapp_template_language", "en"),
        )
    else:
        await adapter.send(to=to, text=text)


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
