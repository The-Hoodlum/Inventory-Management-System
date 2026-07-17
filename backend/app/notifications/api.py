"""Notifications endpoints (mounted at /api/v1/notifications).

The bell reads one payload: the current user's stored notifications (unread + recent) AND
the computed operational signals, with a combined badge count. Reads are scoped to the
caller — no extra permission gate beyond being signed in (you only ever see your own).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, get_current_user, get_db, get_notification_service
from app.notifications.schemas import (
    NotificationPrefsIn,
    NotificationPrefsOut,
    NotificationsResponse,
)
from app.notifications.service import NotificationService
from app.notifications.signals import operational_signals

router = APIRouter()


@router.get("/prefs", response_model=NotificationPrefsOut)
async def get_prefs(
    user: CurrentUser = Depends(get_current_user),
    svc: NotificationService = Depends(get_notification_service),
) -> NotificationPrefsOut:
    return NotificationPrefsOut(**await svc.get_prefs(user.id))


@router.put("/prefs", response_model=NotificationPrefsOut)
async def set_prefs(
    payload: NotificationPrefsIn,
    user: CurrentUser = Depends(get_current_user),
    svc: NotificationService = Depends(get_notification_service),
) -> NotificationPrefsOut:
    return NotificationPrefsOut(**await svc.set_prefs(user.tenant_id, user.id, whatsapp_push=payload.whatsapp_push))


async def _bell(
    user: CurrentUser, db: AsyncSession, svc: NotificationService,
    limit: int = 30, unread_only: bool = False,
) -> NotificationsResponse:
    items = await svc.list_for_user(user.id, limit=limit, unread_only=unread_only)
    unread = await svc.unread_count(user.id)
    signals = await operational_signals(db, user.permissions)
    return NotificationsResponse(
        unread_count=unread, badge_count=unread + len(signals), items=items, signals=signals
    )


@router.get("", response_model=NotificationsResponse)
async def list_notifications(
    limit: int = Query(default=30, ge=1, le=100),
    unread_only: bool = Query(default=False),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    svc: NotificationService = Depends(get_notification_service),
) -> NotificationsResponse:
    return await _bell(user, db, svc, limit, unread_only)


@router.post("/{notification_id}/read", response_model=NotificationsResponse)
async def mark_read(
    notification_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    svc: NotificationService = Depends(get_notification_service),
) -> NotificationsResponse:
    if not await svc.mark_read(user.id, notification_id):
        raise HTTPException(status_code=404, detail="Notification not found")
    return await _bell(user, db, svc)


@router.post("/read-all", response_model=NotificationsResponse)
async def mark_all_read(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    svc: NotificationService = Depends(get_notification_service),
) -> NotificationsResponse:
    await svc.mark_all_read(user.id)
    return await _bell(user, db, svc)
