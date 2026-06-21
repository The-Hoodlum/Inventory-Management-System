"""Pure helpers for the WhatsApp channel: webhook verification and inbound parsing.

No DB, no network — unit-tested in isolation. ``parse_inbound`` is defensive: Meta's
payloads vary and include delivery/read status callbacks and non-text messages, all of
which return None so the caller ignores them.
"""
from __future__ import annotations

import datetime as dt

from app.integrations.channel import InboundMessage

CHANNEL = "whatsapp"


def verify_subscription(*, mode: str | None, token: str | None, challenge: str | None,
                        verify_token: str | None) -> str | None:
    """Meta GET handshake: echo back ``challenge`` only when the token matches a
    configured verify token. Returns None to signal a 403."""
    if mode == "subscribe" and verify_token and token == verify_token:
        return challenge or ""
    return None


def _to_datetime(ts) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(int(ts), tz=dt.UTC)
    except (TypeError, ValueError):
        return None


def parse_inbound(payload: dict) -> InboundMessage | None:
    """Extract the first inbound *text* message (sender, id, text, timestamp).

    Returns None for status callbacks, non-text messages, and malformed payloads.
    """
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {}) or {}
                if "messages" not in value:
                    continue  # statuses / other events
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue  # images, audio, buttons, ... not supported yet
                    body = ((msg.get("text") or {}).get("body") or "").strip()
                    sender = (msg.get("from") or "").strip()
                    if body and sender:
                        return InboundMessage(
                            channel=CHANNEL, sender=sender, text=body,
                            message_id=msg.get("id"), timestamp=_to_datetime(msg.get("timestamp")),
                        )
    except (AttributeError, TypeError):
        return None
    return None
