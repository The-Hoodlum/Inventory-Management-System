"""The WhatsApp webhook authenticates inbound payloads (X-Hub-Signature-256).

The endpoint has no bearer auth (Meta calls it), so the HMAC over the RAW body is what
stops a third party who learns the URL from posting a crafted payload and making the bot
reply to a number of their choosing. Exercised through the real ASGI app.

Requires a live database (DATABASE_URL); skipped otherwise.
"""
from __future__ import annotations

import hashlib
import hmac
import os

import pytest
import pytest_asyncio

RUN_DB = bool(os.getenv("DATABASE_URL"))
pytestmark = pytest.mark.skipif(
    not RUN_DB, reason="DATABASE_URL not set; integration test needs a live Postgres"
)

SECRET = "test-app-secret"
WEBHOOK = "/api/v1/whatsapp/webhook"
BODY = b'{"entry":[{"changes":[{"value":{"messaging_product":"whatsapp"}}]}]}'


@pytest_asyncio.fixture
async def client():
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def signed(monkeypatch):
    """Turn signature verification ON for the app under test."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "whatsapp_app_secret", SECRET, raising=False)
    return lambda body, secret=SECRET: (
        "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    )


# ------------------------------------------------------------------------- #
async def test_genuine_signature_is_accepted(client, signed):
    r = await client.post(WEBHOOK, content=BODY,
                          headers={"X-Hub-Signature-256": signed(BODY),
                                   "Content-Type": "application/json"})
    assert r.status_code == 200, r.text


async def test_missing_signature_is_rejected(client, signed):
    r = await client.post(WEBHOOK, content=BODY, headers={"Content-Type": "application/json"})
    assert r.status_code == 403, r.text


async def test_wrong_secret_is_rejected(client, signed):
    r = await client.post(WEBHOOK, content=BODY,
                          headers={"X-Hub-Signature-256": signed(BODY, "attacker-secret"),
                                   "Content-Type": "application/json"})
    assert r.status_code == 403, r.text


async def test_tampered_body_is_rejected(client, signed):
    """Signature captured from a genuine payload, replayed over a different body."""
    r = await client.post(WEBHOOK, content=b'{"entry":[{"evil":true}]}',
                          headers={"X-Hub-Signature-256": signed(BODY),
                                   "Content-Type": "application/json"})
    assert r.status_code == 403, r.text


async def test_verification_disabled_when_no_secret_configured(client, monkeypatch):
    """Unset app secret -> check is off (mock/local setups keep working)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "whatsapp_app_secret", None, raising=False)
    r = await client.post(WEBHOOK, content=BODY, headers={"Content-Type": "application/json"})
    assert r.status_code == 200, r.text
