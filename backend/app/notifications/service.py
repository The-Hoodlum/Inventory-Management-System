"""Notification orchestration.

``emit`` is the single entry point producers call when something happens: it resolves
recipients (or takes an explicit set), stores one row per recipient, and returns how many
were created. It is deliberately best-effort and side-effect-free beyond writing rows — a
producer must never fail its business transaction because a notification could not be sent.

Read helpers back the bell + inbox: list, unread count, mark one/all read.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable

from app.models import Notification
from app.notifications.repository import NotificationRepository
from app.notifications.schemas import NotificationOut

_SEVERITIES = {"info", "warning", "critical"}


class NotificationService:
    def __init__(self, repo: NotificationRepository) -> None:
        self.repo = repo

    # ------------------------------- emit ------------------------------ #
    async def emit(
        self,
        *,
        tenant_id: uuid.UUID,
        event_type: str,
        title: str,
        recipient_user_ids: Iterable[uuid.UUID],
        severity: str = "info",
        body: str | None = None,
        href: str | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> int:
        """Store one notification per DISTINCT recipient. Returns the number created (0 when
        there are no recipients — a valid, silent outcome)."""
        if severity not in _SEVERITIES:
            severity = "info"
        recipients = {u for u in recipient_user_ids if u is not None}
        rows = [
            Notification(
                tenant_id=tenant_id, recipient_user_id=uid, event_type=event_type,
                severity=severity, title=title, body=body, href=href,
                entity_type=entity_type, entity_id=entity_id, branch_id=branch_id,
                actor_user_id=actor_user_id,
            )
            for uid in recipients
        ]
        await self.repo.create_many(rows)
        return len(rows)

    async def resolve_recipients(
        self, *, permission: str, branch_id: uuid.UUID | None = None,
        exclude: Iterable[uuid.UUID] | None = None,
    ) -> list[uuid.UUID]:
        """Users to notify for a permission (+ optional branch). ``exclude`` drops actors who
        needn't be told about their own action."""
        ids = await self.repo.recipients_with_permission(permission, branch_id=branch_id)
        drop = {u for u in (exclude or []) if u is not None}
        return [u for u in ids if u not in drop]

    # ------------------------------- reads ----------------------------- #
    async def list_for_user(self, user_id: uuid.UUID, *, limit: int = 30) -> list[NotificationOut]:
        rows = await self.repo.list_for_user(user_id, limit=limit)
        return [
            NotificationOut(
                id=n.id, event_type=n.event_type, severity=n.severity, title=n.title,
                body=n.body, href=n.href, entity_type=n.entity_type, entity_id=n.entity_id,
                is_read=n.read_at is not None, created_at=n.created_at,
            )
            for n in rows
        ]

    async def unread_count(self, user_id: uuid.UUID) -> int:
        return await self.repo.unread_count(user_id)

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
        return await self.repo.mark_read(user_id, notification_id)

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        return await self.repo.mark_all_read(user_id)
