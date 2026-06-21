"""Conversational-assistant models: conversation log, branch access, WhatsApp identity.

The assistant answers via function-calling over the read services; these tables are
for logging/audit, branch-based access control, and phone->user resolution. All are
tenant-scoped and protected by RLS. See ``sql/assistant.sql``.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


class AssistantConversation(Base):
    __tablename__ = "assistant_conversations"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'api'"))
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class UserWarehouseAccess(Base):
    __tablename__ = "user_warehouse_access"

    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("warehouses.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class WhatsAppIdentity(Base):
    __tablename__ = "whatsapp_identities"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
