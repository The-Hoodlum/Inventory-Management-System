"""Unit tests for password hashing and JWT tokens (no DB, no async)."""
from __future__ import annotations

import datetime as dt
import uuid

import jwt
import pytest

from app.core import security
from app.core.config import settings


def test_password_hash_roundtrip():
    h = security.hash_password("S3cret!pass")
    assert h != "S3cret!pass"
    assert security.verify_password("S3cret!pass", h) is True
    assert security.verify_password("wrong", h) is False


def test_verify_password_handles_garbage_hash():
    assert security.verify_password("anything", "not-a-bcrypt-hash") is False


def test_access_token_roundtrip():
    uid, tid = uuid.uuid4(), uuid.uuid4()
    token = security.create_access_token(uid, tid)
    payload = security.decode_token(token)
    assert payload["sub"] == str(uid)
    assert payload["tenant_id"] == str(tid)
    assert payload["type"] == security.ACCESS


def test_refresh_token_type():
    # create_refresh_token requires a session id (jti) + rotation family and
    # returns (token, expires_at) since the auth-hardening / refresh-session work.
    token, _expires_at = security.create_refresh_token(
        uuid.uuid4(), uuid.uuid4(), jti=uuid.uuid4(), family=uuid.uuid4()
    )
    assert security.decode_token(token)["type"] == security.REFRESH


def test_expired_token_is_rejected():
    now = dt.datetime.now(dt.timezone.utc)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "type": security.ACCESS,
            "iat": now - dt.timedelta(hours=2),
            "exp": now - dt.timedelta(hours=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_token(token)


def test_tampered_token_is_rejected():
    token = security.create_access_token(uuid.uuid4(), uuid.uuid4())
    with pytest.raises(jwt.PyJWTError):
        jwt.decode(token + "x", settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
