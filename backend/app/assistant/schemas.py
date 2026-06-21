"""Pydantic request/response models for the assistant API."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AskResponse(BaseModel):
    answer: str
    ok: bool = True
    conversation_id: uuid.UUID | None = None
    tools_used: list[str] = []


class WhatsAppInbound(BaseModel):
    """A mock WhatsApp inbound message (same shape the real webhook will normalise to)."""

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from", min_length=3, max_length=32, description="Sender phone number")
    text: str = Field(min_length=1, max_length=2000)


class WhatsAppReply(BaseModel):
    reply: str
    ok: bool = True
    matched_user: bool = True
