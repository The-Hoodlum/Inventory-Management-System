"""Persistence for stored notifications + recipient resolution.

Every query runs under the tenant GUC, so PostgreSQL RLS keeps tenants apart; reads are
further scoped to a single recipient user. Recipient resolution maps a permission (+ an
optional branch) to the set of users who should be notified — reusing the same role and
branch-access model the rest of the app uses (a user with no branch grants is unrestricted).
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Notification,
    NotificationPref,
    Permission,
    Role,
    RolePermission,
    User,
    UserBranchAccess,
    UserRole,
    WhatsAppIdentity,
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_many(self, rows: Sequence[Notification]) -> None:
        if rows:
            self.session.add_all(list(rows))
            await self.session.flush()

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int = 30, unread_only: bool = False
    ) -> list[Notification]:
        stmt = select(Notification).where(Notification.recipient_user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        rows = await self.session.scalars(stmt.order_by(Notification.created_at.desc()).limit(limit))
        return list(rows.all())

    async def unread_count(self, user_id: uuid.UUID) -> int:
        return int(await self.session.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.recipient_user_id == user_id, Notification.read_at.is_(None)
            )
        ) or 0)

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
        row = await self.session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.recipient_user_id == user_id,
            )
        )
        if row is None:
            return False
        if row.read_at is None:
            row.read_at = _now()
            await self.session.flush()
        return True

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        res = await self.session.execute(
            update(Notification)
            .where(Notification.recipient_user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=_now())
        )
        await self.session.flush()
        return int(res.rowcount or 0)

    async def phones_for_push(self, user_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        """WhatsApp number per user who (a) registered one — the opt-in — AND (b) hasn't turned
        the push off in their preferences (no pref row = default on). RLS-scoped."""
        wanted = [u for u in {*user_ids} if u is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(WhatsAppIdentity.user_id, WhatsAppIdentity.phone)
            .outerjoin(NotificationPref, NotificationPref.user_id == WhatsAppIdentity.user_id)
            .where(
                WhatsAppIdentity.user_id.in_(wanted),
                func.coalesce(NotificationPref.whatsapp_push, True).is_(True),
            )
        )
        return {uid: phone for uid, phone in rows}

    # ------------------------------ preferences ------------------------ #
    async def get_pref(self, user_id: uuid.UUID) -> NotificationPref | None:
        return await self.session.get(NotificationPref, user_id)

    async def upsert_pref(self, tenant_id: uuid.UUID, user_id: uuid.UUID, *, whatsapp_push: bool) -> NotificationPref:
        pref = await self.session.get(NotificationPref, user_id)
        if pref is None:
            pref = NotificationPref(tenant_id=tenant_id, user_id=user_id, whatsapp_push=whatsapp_push)
            self.session.add(pref)
        else:
            pref.whatsapp_push = whatsapp_push
            pref.updated_at = _now()
        await self.session.flush()
        return pref

    async def recipients_with_permission(
        self, permission_code: str, *, branch_id: uuid.UUID | None = None
    ) -> list[uuid.UUID]:
        """Active users who hold ``permission_code`` (via any of their roles), optionally
        limited to those who can see ``branch_id`` (unrestricted users, or those explicitly
        granted the branch). RLS scopes this to the current tenant."""
        stmt = (
            select(User.id)
            .distinct()
            .join(UserRole, UserRole.user_id == User.id)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(Permission.code == permission_code, User.is_active.is_(True))
        )
        if branch_id is not None:
            unrestricted = ~exists().where(UserBranchAccess.user_id == User.id)
            has_branch = exists().where(
                and_(UserBranchAccess.user_id == User.id, UserBranchAccess.branch_id == branch_id)
            )
            stmt = stmt.where(or_(unrestricted, has_branch))
        return [uid for (uid,) in (await self.session.execute(stmt)).all()]

    async def recipients_with_role(
        self, role_name: str, *, branch_id: uuid.UUID | None = None
    ) -> list[uuid.UUID]:
        """Active users holding a named ROLE (e.g. 'Branch Manager'), optionally limited to
        those who can see ``branch_id``. Some audiences are a job, not a permission — a
        branch manager should hear about their branch's sales even though no single
        permission code identifies them. Branch filtering matches
        :meth:`recipients_with_permission` exactly. RLS scopes this to the current tenant."""
        stmt = (
            select(User.id)
            .distinct()
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name == role_name, User.is_active.is_(True))
        )
        if branch_id is not None:
            unrestricted = ~exists().where(UserBranchAccess.user_id == User.id)
            has_branch = exists().where(
                and_(UserBranchAccess.user_id == User.id, UserBranchAccess.branch_id == branch_id)
            )
            stmt = stmt.where(or_(unrestricted, has_branch))
        return [uid for (uid,) in (await self.session.execute(stmt)).all()]
