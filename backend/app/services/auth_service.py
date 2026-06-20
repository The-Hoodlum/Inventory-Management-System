"""Authentication service: credential checks with lockout, and refresh-token
rotation with revocation + reuse detection.

Security decisions (lockout maths, rotate/reject/reuse) live in the pure
``app.core.auth_policy`` module and are unit-tested there; this service performs
the I/O (load user, persist counters, read/rotate sessions).
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

import jwt

from app.core import auth_policy
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    TokenTypeError,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    verify_password,
)
from app.models import User
from app.repositories.refresh_repo import RefreshSessionRepository
from app.repositories.user_repo import UserRepository


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, users: UserRepository, sessions: RefreshSessionRepository) -> None:
        self.users = users
        self.sessions = sessions
        self.lockout = auth_policy.LockoutConfig(
            max_attempts=settings.lockout_max_attempts,
            window_seconds=settings.lockout_window_seconds,
            lockout_seconds=settings.lockout_duration_seconds,
        )

    # ------------------------------ login ------------------------------ #
    async def authenticate(
        self, email: str, password: str, tenant_slug: str | None = None
    ) -> User:
        email = email.strip().lower()
        tenant_id: uuid.UUID | None = None
        if tenant_slug:
            tenant = await self.users.get_tenant_by_slug(tenant_slug.strip().lower())
            if tenant is None:
                raise AuthenticationError("Invalid credentials")
            tenant_id = tenant.id

        candidates = await self.users.find_by_email(email, tenant_id)
        if len(candidates) > 1:
            raise AuthenticationError(
                "Multiple accounts found for this email; specify tenant_slug"
            )
        user = candidates[0] if candidates else None
        now = _utcnow()

        # Locked accounts are rejected before any password check.
        if user is not None and auth_policy.is_locked(user.locked_until, now):
            raise AuthenticationError(
                "Account temporarily locked due to repeated failed logins; try again later"
            )

        if user is None or not verify_password(password, user.password_hash):
            if user is not None:
                new_count, locked_until = auth_policy.register_failure(
                    failed_count=user.failed_login_count,
                    last_failed_at=user.last_failed_login_at,
                    now=now,
                    config=self.lockout,
                )
                user.failed_login_count = new_count
                user.last_failed_login_at = now
                user.locked_until = locked_until
                await self.users.session.flush()
            raise AuthenticationError("Invalid credentials")

        if not user.is_active:
            raise AuthenticationError("Account is disabled")

        # Success: clear throttling state and stamp the login.
        user.failed_login_count = 0
        user.locked_until = None
        await self.users.touch_last_login(user)
        await self.users.session.flush()
        return user

    # ------------------------------ tokens ------------------------------ #
    async def _issue(
        self,
        user: User,
        *,
        family_id: uuid.UUID,
        jti: uuid.UUID,
        user_agent: str | None,
        ip: str | None,
    ) -> TokenPair:
        refresh_token, expires_at = create_refresh_token(
            user.id, user.tenant_id, jti=jti, family=family_id
        )
        await self.sessions.create(
            id=jti,
            user_id=user.id,
            tenant_id=user.tenant_id,
            family_id=family_id,
            issued_at=_utcnow(),
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
        )
        access = create_access_token(user.id, user.tenant_id)
        return TokenPair(
            access_token=access,
            refresh_token=refresh_token,
            expires_in=settings.access_token_expire_minutes * 60,
        )

    async def issue_tokens(
        self, user: User, *, user_agent: str | None = None, ip: str | None = None
    ) -> TokenPair:
        # A fresh login starts a new rotation family.
        return await self._issue(
            user, family_id=uuid.uuid4(), jti=uuid.uuid4(), user_agent=user_agent, ip=ip
        )

    async def refresh(
        self, refresh_token: str, *, user_agent: str | None = None, ip: str | None = None
    ) -> TokenPair:
        try:
            payload = decode_refresh_token(refresh_token)
        except (jwt.PyJWTError, TokenTypeError) as exc:
            raise AuthenticationError("Invalid or expired refresh token") from exc
        try:
            jti = uuid.UUID(payload["jti"])
            sub = uuid.UUID(payload["sub"])
            family = uuid.UUID(payload["family"])
        except (KeyError, ValueError) as exc:
            raise AuthenticationError("Malformed refresh token") from exc

        now = _utcnow()
        session = await self.sessions.get(jti)
        outcome = auth_policy.evaluate_refresh(
            found=session is not None,
            revoked=bool(session and session.revoked_at is not None),
            expired=bool(session and session.expires_at <= now),
        )

        if outcome == auth_policy.REUSE and session is not None:
            # Replay of an already-rotated token: revoke the entire family.
            await self.sessions.revoke_family(session.family_id, now=now)
            raise AuthenticationError("Refresh token already used; sessions revoked")
        if outcome != auth_policy.ROTATE or session is None:
            raise AuthenticationError("Invalid or expired refresh token")

        # Defence in depth: token claims must match the stored session.
        if session.user_id != sub or session.family_id != family:
            raise AuthenticationError("Refresh token does not match session")

        user = await self.users.get(sub)
        if user is None or not user.is_active:
            raise AuthenticationError("Account not found or disabled")

        # Rotate: revoke the presented session and issue a new one in the family.
        new_jti = uuid.uuid4()
        await self.sessions.revoke(session, now=now, replaced_by=new_jti)
        return await self._issue(
            user, family_id=session.family_id, jti=new_jti, user_agent=user_agent, ip=ip
        )

    async def logout(self, refresh_token: str) -> None:
        """Revoke the presented refresh session. Idempotent and never raises for
        an already-invalid token (logout should always 'succeed')."""
        try:
            payload = decode_refresh_token(refresh_token)
            jti = uuid.UUID(payload["jti"])
        except (jwt.PyJWTError, TokenTypeError, KeyError, ValueError):
            return
        session = await self.sessions.get(jti)
        if session is not None and session.revoked_at is None:
            await self.sessions.revoke(session, now=_utcnow())
