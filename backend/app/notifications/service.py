"""Notification orchestration.

``emit`` is the single entry point producers call when something happens: it resolves
recipients (or takes an explicit set), stores one row per recipient, and returns how many
were created. It is deliberately best-effort and side-effect-free beyond writing rows — a
producer must never fail its business transaction because a notification could not be sent.

Read helpers back the bell + inbox: list, unread count, mark one/all read.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Notification
from app.notifications.repository import NotificationRepository
from app.notifications.schemas import NotificationOut

logger = get_logger(__name__)
_SEVERITIES = {"info", "warning", "critical"}
# Which severities also push to WhatsApp (for recipients who registered a number). Kept
# conservative — only the most urgent events reach someone's phone.
_PUSH_SEVERITIES = {"critical"}


class NotificationService:
    def __init__(self, repo: NotificationRepository, whatsapp=None) -> None:
        self.repo = repo
        self.whatsapp = whatsapp   # optional WhatsAppAdapter for opt-in push; None -> in-app only

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

    async def resolve_recipients_by_role(
        self, *, role: str, branch_id: uuid.UUID | None = None,
        exclude: Iterable[uuid.UUID] | None = None,
    ) -> list[uuid.UUID]:
        """Users to notify for a named ROLE (+ optional branch) — for audiences defined by
        job rather than by a permission code (e.g. 'Branch Manager')."""
        ids = await self.repo.recipients_with_role(role, branch_id=branch_id)
        drop = {u for u in (exclude or []) if u is not None}
        return [u for u in ids if u not in drop]

    async def notify(
        self, *, tenant_id: uuid.UUID, event_type: str, title: str,
        permission: str | None = None, role: str | None = None,
        recipient_user_ids: Iterable[uuid.UUID] | None = None,
        severity: str = "info", body: str | None = None, href: str | None = None,
        entity_type: str | None = None, entity_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None, actor_user_id: uuid.UUID | None = None,
        push: bool | None = None,
        template: str | None = None, template_params: Sequence[object] | None = None,
    ) -> int:
        """Best-effort emit for a PRODUCER: resolve recipients (an explicit set, and/or every
        holder of ``permission``, and/or everyone with ``role`` — all within ``branch_id`` and
        minus the actor) and store one row each — inside a SAVEPOINT so a notification failure
        can NEVER roll back the caller's business transaction. Returns rows created (0 on any
        problem; logged, not raised).

        ``push`` controls the WhatsApp side channel explicitly:
          None  -> fall back to severity (critical only), the historic behaviour;
          True  -> push regardless of severity (for routine-but-wanted events like a sale);
          False -> in-app only, even if critical.
        Keeping this separate from ``severity`` means "how loud is this?" and "should it
        leave the app?" stay independent — a sale is genuinely `info`, not `critical`.

        ``template``/``template_params`` name an approved Meta template for the push. Events
        the system raises on its own schedule (a sale logged first thing in the morning) fall
        outside Meta's 24-hour window, where free-form text is simply not delivered. Producers
        with a purpose-built template pass it; everything else uses the generic one, and with
        none configured the push stays free-form exactly as it is today.
        """
        recipients: list[uuid.UUID] = []
        created = 0
        try:
            async with self.repo.session.begin_nested():
                recipients = list(recipient_user_ids or [])
                exclude = [actor_user_id] if actor_user_id else None
                if permission is not None:
                    recipients += await self.resolve_recipients(
                        permission=permission, branch_id=branch_id, exclude=exclude,
                    )
                if role is not None:
                    recipients += await self.resolve_recipients_by_role(
                        role=role, branch_id=branch_id, exclude=exclude,
                    )
                created = await self.emit(
                    tenant_id=tenant_id, event_type=event_type, title=title, severity=severity,
                    body=body, href=href, entity_type=entity_type, entity_id=entity_id,
                    branch_id=branch_id, actor_user_id=actor_user_id, recipient_user_ids=recipients,
                )
        except Exception:  # noqa: BLE001 — a notification must never break the producer
            logger.warning("notification_emit_failed", extra={"event_type": event_type})
            return 0
        # WhatsApp push — a side channel, outside the DB savepoint and fully best-effort
        # (the adapter itself swallows delivery errors).
        should_push = (severity in _PUSH_SEVERITIES) if push is None else push
        if created and should_push and self.whatsapp is not None:
            await self._push_whatsapp(recipients, title, body, template, template_params)
        return created

    async def _push_whatsapp(
        self, recipient_ids, title: str, body: str | None,
        template: str | None = None, params: Sequence[object] | None = None,
    ) -> None:
        from app.assistant.whatsapp import deliver

        try:
            ids = [u for u in {*recipient_ids} if u is not None]
            phones = await self.repo.phones_for_push(ids)
            if not phones:
                return
            text = f"🔔 {title}" + (f"\n{body}" if body else "")
            name = template or settings.whatsapp_template_notification
            # The generic template takes (title, body); a producer-supplied one brings its own
            # positional values, which must match that template's variable count.
            values = params if template and params is not None else (title, body or "-")
            for phone in set(phones.values()):
                await deliver(self.whatsapp, to=phone, text=text, template=name, params=values)
        except Exception:  # noqa: BLE001 — push is best-effort
            logger.warning("notification_push_failed")

    # ------------------------------- reads ----------------------------- #
    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int = 30, unread_only: bool = False
    ) -> list[NotificationOut]:
        rows = await self.repo.list_for_user(user_id, limit=limit, unread_only=unread_only)
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

    # ---------------------------- preferences -------------------------- #
    async def get_prefs(self, user_id: uuid.UUID) -> dict:
        pref = await self.repo.get_pref(user_id)
        return {"whatsapp_push": pref.whatsapp_push if pref is not None else True}

    async def set_prefs(self, tenant_id: uuid.UUID, user_id: uuid.UUID, *, whatsapp_push: bool) -> dict:
        pref = await self.repo.upsert_pref(tenant_id, user_id, whatsapp_push=whatsapp_push)
        return {"whatsapp_push": pref.whatsapp_push}
