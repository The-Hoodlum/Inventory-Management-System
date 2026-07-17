"""Integration: notifications Phase 4 — per-user preferences.

- GET/PUT /notifications/prefs (default whatsapp_push=true; can be turned off);
- turning the WhatsApp push off actually stops the push, even for a critical event to a
  recipient who has a registered number.

Requires a live DB with the notification_prefs table; skipped otherwise.
"""
from __future__ import annotations

import base64
import json
import os
import uuid

import pytest
import pytest_asyncio

RUN_DB = bool(os.getenv("DATABASE_URL"))
pytestmark = pytest.mark.skipif(
    not RUN_DB, reason="DATABASE_URL not set; integration test needs a live Postgres"
)

ADMIN_EMAIL = os.getenv("DEMO_ADMIN_EMAIL", "admin@demo.com")
ADMIN_PASSWORD = os.getenv("DEMO_ADMIN_PASSWORD", "ChangeMe123!")


@pytest_asyncio.fixture
async def client():
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _claims(token: str) -> dict:
    p = token.split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))


async def _login(client):
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}, _claims(tok)


async def _register_whatsapp(tenant_id, user_id, phone) -> None:
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal
    from app.models import WhatsAppIdentity

    async with AsyncSessionLocal() as s:
        await s.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": str(tenant_id)})
        s.add(WhatsAppIdentity(tenant_id=uuid.UUID(str(tenant_id)), phone=phone, user_id=uuid.UUID(str(user_id))))
        await s.commit()


async def _notify_critical(tenant_id, adapter, recipient) -> int:
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal
    from app.notifications.repository import NotificationRepository
    from app.notifications.service import NotificationService

    async with AsyncSessionLocal() as s:
        await s.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": str(tenant_id)})
        n = await NotificationService(NotificationRepository(s), adapter).notify(
            tenant_id=uuid.UUID(str(tenant_id)), event_type="test.crit", title="Critical",
            severity="critical", recipient_user_ids=[recipient])
        await s.commit()
    return n


# ------------------------------------------------------------------------- #
async def test_prefs_default_and_update(client):
    h, _ = await _login(client)
    # Default (no row) is on.
    assert (await client.get("/api/v1/notifications/prefs", headers=h)).json()["whatsapp_push"] is True
    # Turn it off, then back on.
    assert (await client.put("/api/v1/notifications/prefs", headers=h, json={"whatsapp_push": False})).json()["whatsapp_push"] is False
    assert (await client.get("/api/v1/notifications/prefs", headers=h)).json()["whatsapp_push"] is False
    assert (await client.put("/api/v1/notifications/prefs", headers=h, json={"whatsapp_push": True})).json()["whatsapp_push"] is True


async def test_push_respects_the_pref(client):
    from app.assistant.whatsapp import MockWhatsAppAdapter

    h, claims = await _login(client)
    tenant_id, admin_id = claims["tenant_id"], claims["sub"]
    await _register_whatsapp(tenant_id, admin_id, f"+2609{uuid.uuid4().int % 10_000_000:07d}")

    # Push OFF -> a critical event does NOT reach WhatsApp (still stored in-app).
    await client.put("/api/v1/notifications/prefs", headers=h, json={"whatsapp_push": False})
    off = MockWhatsAppAdapter()
    await _notify_critical(tenant_id, off, admin_id)
    assert off.sent == []

    # Push ON -> it does.
    await client.put("/api/v1/notifications/prefs", headers=h, json={"whatsapp_push": True})
    on = MockWhatsAppAdapter()
    await _notify_critical(tenant_id, on, admin_id)
    assert len(on.sent) == 1
