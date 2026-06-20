"""Unit tests for JWT token primitives (uses PyJWT; no settings/bcrypt)."""
from __future__ import annotations

import datetime as dt
import uuid

import jwt

from app.core import tokens

SECRET = "unit-test-secret-value-1234567890"
ALG = "HS256"


def _now() -> dt.datetime:
    # Real current time: PyJWT validates exp/iat against the actual clock.
    return dt.datetime.now(dt.UTC)


def _make(token_type: str, *, secret: str = SECRET, ttl_seconds: int = 900, extra=None) -> str:
    now = _now()
    return tokens.encode_token(
        subject=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        token_type=token_type,
        secret=secret,
        algorithm=ALG,
        issued_at=now,
        expires_at=now + dt.timedelta(seconds=ttl_seconds),
        jti=tokens.new_jti(),
        extra=extra,
    )


def test_encode_decode_round_trip():
    sub = uuid.uuid4()
    now = _now()
    token = tokens.encode_token(
        subject=sub,
        tenant_id=uuid.uuid4(),
        token_type=tokens.ACCESS,
        secret=SECRET,
        algorithm=ALG,
        issued_at=now,
        expires_at=now + dt.timedelta(minutes=15),
        jti=tokens.new_jti(),
    )
    payload = tokens.decode_token(token, secret=SECRET, algorithms=[ALG])
    assert payload["sub"] == str(sub)
    assert payload["type"] == tokens.ACCESS
    assert "jti" in payload


def test_require_type_passes_and_fails():
    token = _make(tokens.REFRESH)
    payload = tokens.decode_token(token, secret=SECRET, algorithms=[ALG])
    assert tokens.require_type(payload, tokens.REFRESH) is payload
    try:
        tokens.require_type(payload, tokens.ACCESS)
        raise AssertionError("expected TokenTypeError")
    except tokens.TokenTypeError:
        pass


def test_wrong_secret_rejected():
    token = _make(tokens.ACCESS)
    try:
        tokens.decode_token(token, secret="a-different-secret-value-0987654321", algorithms=[ALG])
        raise AssertionError("expected signature error")
    except jwt.PyJWTError:
        pass


def test_expired_token_rejected():
    token = _make(tokens.ACCESS, ttl_seconds=-10)  # already expired
    try:
        tokens.decode_token(token, secret=SECRET, algorithms=[ALG])
        raise AssertionError("expected expired error")
    except jwt.ExpiredSignatureError:
        pass


def test_extra_claims_round_trip():
    fam = str(uuid.uuid4())
    token = _make(tokens.REFRESH, extra={"family": fam})
    payload = tokens.decode_token(token, secret=SECRET, algorithms=[ALG])
    assert payload["family"] == fam
