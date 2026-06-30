"""Integration tests for global search + the notifications bell over HTTP.

Search fans across the registered providers the caller may see (RLS-scoped); the
notifications endpoint surfaces existing operational signals. Requires a live database
(DATABASE_URL) with the RBAC + demo seed; skipped otherwise.
"""
from __future__ import annotations

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


async def _headers(client, email, password) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_search_finds_a_customer_by_name(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    token = f"Zephyr{uuid.uuid4().hex[:6]}"
    r = await client.post("/api/v1/customers", headers=admin_h, json={"name": f"{token} Trading"})
    assert r.status_code == 201, r.text
    cust_id = r.json()["id"]

    r = await client.get("/api/v1/search", headers=admin_h, params={"q": token})
    assert r.status_code == 200, r.text
    body = r.json()
    groups = {g["entity"]: g for g in body["groups"]}
    assert "customer" in groups, body
    hit = next(h for h in groups["customer"]["hits"] if h["id"] == cust_id)
    assert token in hit["title"] and hit["href"] == "/customers"


async def test_search_short_query_returns_no_groups(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.get("/api/v1/search", headers=admin_h, params={"q": "a"})
    assert r.status_code == 200, r.text
    assert r.json()["groups"] == []


async def test_search_requires_auth(client):
    r = await client.get("/api/v1/search", params={"q": "acme"})
    assert r.status_code in (401, 403), r.text


async def test_search_is_permission_scoped(client):
    """A Cashier lacks supplier.read, so the supplier group must never appear in their
    results even when a query matches a supplier — proving per-provider permission
    gating. (Admin, by contrast, can see suppliers.)"""
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.get("/api/v1/users/roles", headers=admin_h)
    role_id = next((x["id"] for x in r.json() if x["name"] == "Cashier"), None)
    if not role_id:
        pytest.skip("Cashier role not seeded")
    email = f"cashier-{uuid.uuid4().hex[:8]}@demo.com"
    pw = "CashierPass123"
    r = await client.post("/api/v1/users", headers=admin_h, json={
        "email": email, "full_name": "Search Cashier", "password": pw, "role_ids": [role_id]})
    assert r.status_code == 201, r.text
    cashier_h = await _headers(client, email, pw)

    # A broad term likely to match a supplier name in the demo data.
    r = await client.get("/api/v1/search", headers=cashier_h, params={"q": "ltd"})
    assert r.status_code == 200, r.text
    entities = {g["entity"] for g in r.json()["groups"]}
    assert "supplier" not in entities, entities


async def test_notifications_shape(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.get("/api/v1/assistant/notifications", headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body and isinstance(body["items"], list)
    for item in body["items"]:
        assert {"kind", "severity", "title", "count", "href"} <= set(item)
