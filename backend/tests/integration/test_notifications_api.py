"""Integration tests for the notifications core (Phase 1 — shipped inert, no producers).

Exercises the API + service directly: emit stores one row per recipient; the bell lists a
user's own stored notifications (with unread + badge counts) alongside the computed signals;
read / read-all clear personal state; recipients are strictly scoped to the addressee; and
the role+branch recipient resolver finds the right users.

Requires a live database (DATABASE_URL) with the RBAC + demo seed; skipped otherwise.
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
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


async def _login(client, email, password) -> tuple[dict, dict]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}, _claims(tok)


async def _make_user(client, admin_h, password) -> str:
    # A role-less user still authenticates and can read their OWN notifications (the bell has
    # no permission gate) — enough to prove recipient scoping.
    email = f"notif-{uuid.uuid4().hex[:8]}@demo.com"
    r = await client.post("/api/v1/users", headers=admin_h,
                          json={"email": email, "full_name": "Notif User", "password": password, "role_ids": []})
    assert r.status_code == 201, r.text
    return email


async def _emit(tenant_id, **kw) -> int:
    """Emit through the real service on a committed session so the HTTP request sees it."""
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal
    from app.notifications.repository import NotificationRepository
    from app.notifications.service import NotificationService

    async with AsyncSessionLocal() as s:
        await s.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": str(tenant_id)})
        n = await NotificationService(NotificationRepository(s)).emit(tenant_id=uuid.UUID(str(tenant_id)), **kw)
        await s.commit()
    return n


async def _resolve(tenant_id, **kw) -> list[str]:
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal
    from app.notifications.repository import NotificationRepository
    from app.notifications.service import NotificationService

    async with AsyncSessionLocal() as s:
        await s.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": str(tenant_id)})
        ids = await NotificationService(NotificationRepository(s)).resolve_recipients(**kw)
    return [str(i) for i in ids]


# ------------------------------------------------------------------------- #
async def test_emit_list_read_and_read_all(client):
    h, claims = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    tenant_id, admin_id = claims["tenant_id"], uuid.UUID(claims["sub"])
    et = f"test.{uuid.uuid4().hex[:8]}"

    n = await _emit(tenant_id, event_type=et, title="First", severity="warning",
                    recipient_user_ids=[admin_id], href="/assembly-queue")
    assert n == 1
    await _emit(tenant_id, event_type=et, title="Second", severity="info", recipient_user_ids=[admin_id])

    body = (await client.get("/api/v1/notifications", headers=h)).json()
    mine = [i for i in body["items"] if i["event_type"] == et]
    assert len(mine) == 2 and all(i["is_read"] is False for i in mine)
    assert body["unread_count"] >= 2
    assert body["badge_count"] == body["unread_count"] + len(body["signals"])

    # Mark the first read -> it flips, unread drops.
    before = body["unread_count"]
    first_id = next(i["id"] for i in mine if i["title"] == "First")
    after = (await client.post(f"/api/v1/notifications/{first_id}/read", headers=h)).json()
    assert after["unread_count"] == before - 1
    assert next(i for i in after["items"] if i["id"] == first_id)["is_read"] is True

    # Read-all -> nothing unread.
    cleared = (await client.post("/api/v1/notifications/read-all", headers=h)).json()
    assert cleared["unread_count"] == 0
    assert all(i["is_read"] for i in cleared["items"])


async def test_notifications_are_scoped_to_the_recipient(client):
    admin_h, admin_claims = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    tenant_id = admin_claims["tenant_id"]
    pw = "NotifPass123"
    email = await _make_user(client, admin_h, pw)
    _, other_claims = await _login(client, email, pw)
    other_id = uuid.UUID(other_claims["sub"])

    et = f"scoped.{uuid.uuid4().hex[:8]}"
    await _emit(tenant_id, event_type=et, title="For the other user", recipient_user_ids=[other_id])

    # The addressee sees it; the admin never does.
    other_h, _ = await _login(client, email, pw)
    other_items = (await client.get("/api/v1/notifications", headers=other_h)).json()["items"]
    assert any(i["event_type"] == et for i in other_items)
    admin_items = (await client.get("/api/v1/notifications", headers=admin_h)).json()["items"]
    assert not any(i["event_type"] == et for i in admin_items)


async def test_mark_read_unknown_is_404(client):
    h, _ = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.post(f"/api/v1/notifications/{uuid.uuid4()}/read", headers=h)
    assert r.status_code == 404


async def test_resolver_finds_permission_holders(client):
    _, claims = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    tenant_id, admin_id = claims["tenant_id"], claims["sub"]
    # Admin holds every permission, so it resolves for a management permission...
    holders = await _resolve(tenant_id, permission="motorcycle.manage")
    assert admin_id in holders
    # ...and is dropped when excluded (an actor needn't be told of their own action).
    assert admin_id not in await _resolve(tenant_id, permission="motorcycle.manage", exclude=[uuid.UUID(admin_id)])
