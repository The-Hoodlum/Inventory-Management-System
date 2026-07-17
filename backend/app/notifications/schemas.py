"""Schemas for the notifications API (mounted at /api/v1/notifications)."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel

from app.notifications.signals import OperationalSignal


class NotificationOut(BaseModel):
    """One stored, event-driven notification for the current user."""

    id: uuid.UUID
    event_type: str
    severity: str  # info | warning | critical
    title: str
    body: str | None = None
    href: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    is_read: bool
    created_at: dt.datetime


class NotificationsResponse(BaseModel):
    """The bell payload: stored notifications + the computed operational signals, plus a
    combined unread count for the badge."""

    unread_count: int                     # unread STORED notifications
    badge_count: int                      # unread stored + number of live signals
    items: list[NotificationOut] = []     # stored (unread + recent), newest first
    signals: list[OperationalSignal] = []  # computed operational alerts


class NotificationPrefsOut(BaseModel):
    whatsapp_push: bool = True   # receive the WhatsApp push of critical events


class NotificationPrefsIn(BaseModel):
    whatsapp_push: bool
