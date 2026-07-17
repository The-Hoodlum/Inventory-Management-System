"""Per-user notification channel preferences. In-app is always on; this stores opt-outs for
side channels (the WhatsApp push of critical events). Sparse — no row means defaults. See
``database/sql/notification_prefs.sql``."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, ForeignKey, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


class NotificationPref(Base):
    __tablename__ = "notification_prefs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    whatsapp_push: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
