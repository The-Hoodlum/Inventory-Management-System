"""Integration: notifications Phase 3 — WhatsApp opt-in push + the inbox unread filter.

- a CRITICAL notification pushes to a recipient who registered a WhatsApp number; a
  lower-severity one does not; a recipient without a number gets in-app only;
- GET /notifications?unread_only=true returns only unread stored items.

Requires a live DB; skipped otherwise.
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


async def _notify(tenant_id, adapter, **kw) -> int:
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal
    from app.notifications.repository import NotificationRepository
    from app.notifications.service import NotificationService

    async with AsyncSessionLocal() as s:
        await s.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": str(tenant_id)})
        n = await NotificationService(NotificationRepository(s), adapter).notify(
            tenant_id=uuid.UUID(str(tenant_id)), **kw)
        await s.commit()
    return n


# ------------------------------------------------------------------------- #
async def test_critical_pushes_to_registered_number(client):
    from app.assistant.whatsapp import MockWhatsAppAdapter

    _, claims = await _login(client)
    tenant_id, admin_id = claims["tenant_id"], uuid.UUID(claims["sub"])
    phone = f"+2609{uuid.uuid4().int % 10_000_000:07d}"
    await _register_whatsapp(tenant_id, admin_id, phone)

    adapter = MockWhatsAppAdapter()
    await _notify(tenant_id, adapter, event_type="test.crit", title="Critical thing", severity="critical",
                  body="act now", recipient_user_ids=[admin_id])
    assert len(adapter.sent) == 1
    assert adapter.sent[0]["to"] == phone and "Critical thing" in adapter.sent[0]["text"]


async def test_lower_severity_does_not_push(client):
    from app.assistant.whatsapp import MockWhatsAppAdapter

    _, claims = await _login(client)
    tenant_id, admin_id = claims["tenant_id"], uuid.UUID(claims["sub"])
    await _register_whatsapp(tenant_id, admin_id, f"+2609{uuid.uuid4().int % 10_000_000:07d}")

    adapter = MockWhatsAppAdapter()
    await _notify(tenant_id, adapter, event_type="test.warn", title="Just a warning", severity="warning",
                  recipient_user_ids=[admin_id])
    assert adapter.sent == []   # only critical severities push


async def test_unread_only_filter(client):
    h, claims = await _login(client)
    tenant_id, admin_id = claims["tenant_id"], uuid.UUID(claims["sub"])
    et = f"inbox.{uuid.uuid4().hex[:8]}"
    await _notify(tenant_id, None, event_type=et, title="One", recipient_user_ids=[admin_id])
    await _notify(tenant_id, None, event_type=et, title="Two", recipient_user_ids=[admin_id])

    unread = (await client.get("/api/v1/notifications", headers=h, params={"unread_only": "true", "limit": 100})).json()
    mine = [i for i in unread["items"] if i["event_type"] == et]
    assert len(mine) == 2 and all(i["is_read"] is False for i in mine)

    # Read one; the unread view drops it, the full view keeps both.
    await client.post(f"/api/v1/notifications/{mine[0]['id']}/read", headers=h)
    unread2 = (await client.get("/api/v1/notifications", headers=h, params={"unread_only": "true", "limit": 100})).json()
    assert len([i for i in unread2["items"] if i["event_type"] == et]) == 1
    allv = (await client.get("/api/v1/notifications", headers=h, params={"limit": 100})).json()
    assert len([i for i in allv["items"] if i["event_type"] == et]) == 2


# --------------- explicit push policy + role-based recipients --------------- #
async def test_push_true_pushes_a_routine_info_event(client):
    """A completed sale is genuinely `info`, not `critical` — push is opted into
    explicitly so severity keeps meaning "how urgent", not "does it leave the app"."""
    from app.assistant.whatsapp import MockWhatsAppAdapter

    _, claims = await _login(client)
    tenant_id, admin_id = claims["tenant_id"], uuid.UUID(claims["sub"])
    phone = f"+2609{uuid.uuid4().int % 10_000_000:07d}"
    await _register_whatsapp(tenant_id, admin_id, phone)

    adapter = MockWhatsAppAdapter()
    await _notify(tenant_id, adapter, event_type="bike.sold", title="Bike sold: CG125 — ZMW 18,000.00",
                  severity="info", push=True, body="Chassis CH123\nCustomer: Grace",
                  recipient_user_ids=[admin_id])
    assert len(adapter.sent) == 1
    sent = adapter.sent[0]["text"]
    assert "Bike sold" in sent and "Chassis CH123" in sent and "Grace" in sent


async def test_push_false_suppresses_even_a_critical_event(client):
    from app.assistant.whatsapp import MockWhatsAppAdapter

    _, claims = await _login(client)
    tenant_id, admin_id = claims["tenant_id"], uuid.UUID(claims["sub"])
    await _register_whatsapp(tenant_id, admin_id, f"+2609{uuid.uuid4().int % 10_000_000:07d}")

    adapter = MockWhatsAppAdapter()
    await _notify(tenant_id, adapter, event_type="test.quiet", title="Critical but in-app only",
                  severity="critical", push=False, recipient_user_ids=[admin_id])
    assert adapter.sent == []


async def test_role_based_recipients_reach_branch_managers(client):
    """Some audiences are a job, not a permission — resolve by role name."""
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal
    from app.notifications.repository import NotificationRepository

    h, claims = await _login(client)
    tenant_id = claims["tenant_id"]
    roles = (await client.get("/api/v1/users/roles", headers=h)).json()
    bm_role = next(r["id"] for r in roles if r["name"] == "Branch Manager")
    email = f"bm-{uuid.uuid4().hex[:8]}@demo.com"
    created = await client.post("/api/v1/users", headers=h, json={
        "email": email, "full_name": "Branch Boss", "password": "ScopeTest123!",
        "role_ids": [bm_role]})
    assert created.status_code in (200, 201), created.text
    bm_id = uuid.UUID(created.json()["id"])

    async with AsyncSessionLocal() as s:
        await s.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": str(tenant_id)})
        ids = await NotificationRepository(s).recipients_with_role("Branch Manager")
    assert bm_id in ids
