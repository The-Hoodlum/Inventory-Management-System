"""Refresh-session persistence for token rotation, revocation and reuse
detection. Not under RLS (refresh happens before tenant context exists), so
every access is keyed by session id / family / user id explicitly.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshSession


class RefreshSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        id: uuid.UUID,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        family_id: uuid.UUID,
        issued_at: dt.datetime,
        expires_at: dt.datetime,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> RefreshSession:
        row = RefreshSession(
            id=id,
            user_id=user_id,
            tenant_id=tenant_id,
            family_id=family_id,
            issued_at=issued_at,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, jti: uuid.UUID) -> RefreshSession | None:
        return await self.session.get(RefreshSession, jti)

    async def revoke(
        self,
        row: RefreshSession,
        *,
        now: dt.datetime,
        replaced_by: uuid.UUID | None = None,
    ) -> None:
        row.revoked_at = now
        if replaced_by is not None:
            row.replaced_by = replaced_by
        await self.session.flush()

    async def revoke_family(self, family_id: uuid.UUID, *, now: dt.datetime) -> None:
        """Revoke every still-active session in a rotation family (reuse/theft)."""
        await self.session.execute(
            update(RefreshSession)
            .where(RefreshSession.family_id == family_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await self.session.flush()
