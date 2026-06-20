"""Integration tests for RBAC role enforcement over HTTP.

Verifies the seeded system roles grant the right access:
  * Viewer is read-only (reads 200, writes 403).
  * Warehouse Manager can run the core operational flows (create supplier /
    product / PO, run reorder) but cannot administer users.

Requires a live database (DATABASE_URL) with the RBAC + demo seed; skipped
otherwise. Sub-users are created via the admin account (needs user.manage).

NOTE: the Warehouse Manager assertions depend on the broadened permission set in
``database/sql/seed_rbac.sql``. If you upgraded an existing database, re-seed it
(``docker compose down -v && docker compose up``) so the new grants apply.
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


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


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


async def _role_id(client, admin_h, name) -> str:
    r = await client.get("/api/v1/users/roles", headers=admin_h)
    assert r.status_code == 200, r.text
    role = next((x for x in r.json() if x["name"] == name), None)
    assert role, f"system role {name!r} not found — re-seed the database"
    return role["id"]


async def _make_user(client, admin_h, role_name, password) -> str:
    role_id = await _role_id(client, admin_h, role_name)
    email = f"{role_name.lower().replace(' ', '')}-{uuid.uuid4().hex[:8]}@demo.com"
    r = await client.post(
        "/api/v1/users",
        headers=admin_h,
        json={
            "email": email,
            "full_name": f"Test {role_name}",
            "password": password,
            "role_ids": [role_id],
        },
    )
    assert r.status_code == 201, r.text
    return email


async def test_viewer_is_read_only(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    email = await _make_user(client, admin_h, "Viewer", "ViewerPass123")
    vh = await _headers(client, email, "ViewerPass123")

    # Reads are allowed.
    r = await client.get("/api/v1/products", headers=vh)
    assert r.status_code == 200, r.text

    # Writes are denied.
    r = await client.post("/api/v1/suppliers", headers=vh, json={"name": _uniq("Nope")})
    assert r.status_code == 403, r.text


async def test_warehouse_manager_can_operate_but_not_admin(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    email = await _make_user(client, admin_h, "Warehouse Manager", "WarehousePass123")
    wh = await _headers(client, email, "WarehousePass123")

    # Operational writes are allowed (these were 403 before the RBAC fix).
    r = await client.post("/api/v1/suppliers", headers=wh, json={"name": _uniq("WM-Supplier")})
    assert r.status_code == 201, r.text
    supplier_id = r.json()["id"]

    r = await client.post(
        "/api/v1/products",
        headers=wh,
        json={"sku": _uniq("WM-SKU"), "name": "WM Widget", "primary_supplier_id": supplier_id},
    )
    assert r.status_code == 201, r.text
    product_id = r.json()["id"]

    r = await client.get("/api/v1/warehouses", headers=wh, params={"page_size": 1})
    assert r.status_code == 200 and r.json()["items"], r.text
    warehouse_id = r.json()["items"][0]["id"]

    r = await client.post(
        "/api/v1/purchase-orders",
        headers=wh,
        json={
            "supplier_id": supplier_id,
            "warehouse_id": warehouse_id,
            "lines": [{"product_id": product_id, "ordered_qty": "5", "unit_cost": "1.00"}],
        },
    )
    assert r.status_code == 201, r.text

    r = await client.post("/api/v1/reorder/run", headers=wh, json={})
    assert r.status_code == 200, r.text

    # But administering users is forbidden (no user.manage).
    r = await client.post(
        "/api/v1/users",
        headers=wh,
        json={
            "email": f"x-{uuid.uuid4().hex[:6]}@demo.com",
            "full_name": "x",
            "password": "Whatever123",
            "role_ids": [],
        },
    )
    assert r.status_code == 403, r.text
