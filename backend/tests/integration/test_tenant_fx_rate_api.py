"""Integration: the USD->billing exchange rate is an editable tenant setting.

Confirms an admin can read + update the rate over HTTP, that a non-positive rate is
rejected, and that updates require settings.manage. Requires a live DB + seed.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal

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


@pytest_asyncio.fixture(autouse=True)
async def _restore_rate(client):
    """Sales tests assume the tenant rate is 1 (ZMW == USD); reset it after each test."""
    yield
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await client.put("/api/v1/tenant/settings", headers=h, json={"fx_rate": "1"})


async def _role_id(client, admin_h, name) -> str:
    r = await client.get("/api/v1/users/roles", headers=admin_h)
    role = next((x for x in r.json() if x["name"] == name), None)
    assert role, f"role {name} missing — re-seed"
    return role["id"]


async def test_admin_can_read_and_update_rate(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.get("/api/v1/tenant/settings", headers=admin_h)
    assert r.status_code == 200, r.text
    assert "fx_rate" in r.json()

    r = await client.put("/api/v1/tenant/settings", headers=admin_h, json={"fx_rate": "23.750000"})
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["fx_rate"]) == Decimal("23.75")

    # Persisted for the next read.
    r = await client.get("/api/v1/tenant/settings", headers=admin_h)
    assert Decimal(r.json()["fx_rate"]) == Decimal("23.75")


async def test_non_positive_rate_rejected(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.put("/api/v1/tenant/settings", headers=admin_h, json={"fx_rate": "0"})
    assert r.status_code == 422, r.text


async def test_update_requires_settings_manage(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    # A cashier has no settings.manage permission.
    role_id = await _role_id(client, admin_h, "Cashier")
    email = f"fxcashier-{uuid.uuid4().hex[:8]}@demo.com"
    pw = "CashierPass123"
    r = await client.post("/api/v1/users", headers=admin_h, json={
        "email": email, "full_name": "FX Cashier", "password": pw, "role_ids": [role_id]})
    assert r.status_code == 201, r.text
    cashier_h = await _headers(client, email, pw)
    r = await client.put("/api/v1/tenant/settings", headers=cashier_h, json={"fx_rate": "30"})
    assert r.status_code == 403, r.text
