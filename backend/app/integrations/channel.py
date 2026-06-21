"""Channel abstraction.

A *channel* is any interface a user talks to the assistant through — WhatsApp today,
and (by following this contract) Telegram, a mobile app, web chat, email, or Teams
later. A channel does only two things: turn its inbound payload into an
``InboundMessage`` and send text back. ALL intelligence, tools, prompts, and the LLM
client live in the single ``AssistantService`` — channels never duplicate them.
"""
from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass


@dataclass
class InboundMessage:
    """A user message normalised across channels."""

    channel: str            # "whatsapp", "telegram", ...
    sender: str             # channel-native id (e.g. phone number)
    text: str
    message_id: str | None = None
    timestamp: dt.datetime | None = None


class ChannelTransport(abc.ABC):
    """Transport contract for a channel adapter. Parsing + sending only — no business logic."""

    channel: str

    @abc.abstractmethod
    def parse(self, payload: dict) -> InboundMessage | None:
        """Normalise an inbound webhook payload, or None for events to ignore
        (delivery/read receipts, unsupported message types, malformed input)."""

    @abc.abstractmethod
    async def send(self, *, to: str, text: str) -> None:
        """Deliver a text reply to the recipient on this channel."""
