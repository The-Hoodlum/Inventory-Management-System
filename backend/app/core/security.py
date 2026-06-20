"""Password hashing (bcrypt) and JWT creation/verification.

Token encoding/decoding is delegated to ``app.core.tokens`` (PyJWT-only, no
settings) so the core logic is unit-testable in isolation; this module wires it
to the configured secret/algorithm/expiry and adds password hashing.

Uses the ``bcrypt`` library directly (no passlib) so it stays compatible with
the bcrypt hashes generated in-database by pgcrypto's ``crypt()`` in the demo
seed.
"""
from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any

import bcrypt

from app.core import tokens
from app.core.config import settings

# Re-exported so existing imports (`from app.core.security import ACCESS`) work.
ACCESS = tokens.ACCESS
REFRESH = tokens.REFRESH
TokenTypeError = tokens.TokenTypeError
new_jti = tokens.new_jti


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt; returns the encoded hash string."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def create_access_token(subject: uuid.UUID | str, tenant_id: uuid.UUID | str) -> str:
    now = _now()
    return tokens.encode_token(
        subject=subject,
        tenant_id=tenant_id,
        token_type=ACCESS,
        secret=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        issued_at=now,
        expires_at=now + _dt.timedelta(minutes=settings.access_token_expire_minutes),
        jti=tokens.new_jti(),
    )


def create_refresh_token(
    subject: uuid.UUID | str,
    tenant_id: uuid.UUID | str,
    *,
    jti: uuid.UUID | str,
    family: uuid.UUID | str,
) -> tuple[str, _dt.datetime]:
    """Build a refresh token carrying ``jti`` (the server-side session id) and
    its rotation ``family``. Returns ``(token, expires_at)`` so the caller can
    persist a matching session row with the same expiry."""
    now = _now()
    expires_at = now + _dt.timedelta(days=settings.refresh_token_expire_days)
    token = tokens.encode_token(
        subject=subject,
        tenant_id=tenant_id,
        token_type=REFRESH,
        secret=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        issued_at=now,
        expires_at=expires_at,
        jti=str(jti),
        extra={"family": str(family)},
    )
    return token, expires_at


def decode_token(token: str) -> dict[str, Any]:
    """Decode + verify a JWT with the configured secret. Raises ``jwt.PyJWTError``."""
    return tokens.decode_token(
        token, secret=settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and require an access token. Raises ``jwt.PyJWTError`` or ``TokenTypeError``."""
    return tokens.require_type(decode_token(token), ACCESS)


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Decode and require a refresh token. Raises ``jwt.PyJWTError`` or ``TokenTypeError``."""
    return tokens.require_type(decode_token(token), REFRESH)
