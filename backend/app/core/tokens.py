"""JWT primitives — depends only on PyJWT + the standard library (NOT on
settings or bcrypt), so the encode/decode/type logic is unit-testable in
isolation. ``app.core.security`` wraps these with the configured secret."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import jwt

ACCESS = "access"
REFRESH = "refresh"


class TokenTypeError(Exception):
    """Raised when a token's ``type`` claim is not the expected one."""


def new_jti() -> str:
    return str(uuid.uuid4())


def encode_token(
    *,
    subject: uuid.UUID | str,
    tenant_id: uuid.UUID | str,
    token_type: str,
    secret: str,
    algorithm: str,
    issued_at: dt.datetime,
    expires_at: dt.datetime,
    jti: str,
    extra: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "sub": str(subject),
        "tenant_id": str(tenant_id),
        "type": token_type,
        "jti": jti,
        "iat": issued_at,
        "exp": expires_at,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_token(token: str, *, secret: str, algorithms: list[str]) -> dict[str, Any]:
    """Decode and verify signature + expiry. Raises ``jwt.PyJWTError`` on any problem."""
    return jwt.decode(token, secret, algorithms=algorithms)


def require_type(payload: dict[str, Any], expected: str) -> dict[str, Any]:
    if payload.get("type") != expected:
        raise TokenTypeError(f"expected '{expected}' token, got '{payload.get('type')}'")
    return payload
