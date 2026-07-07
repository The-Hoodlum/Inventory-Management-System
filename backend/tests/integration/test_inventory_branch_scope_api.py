"""Integration tests for branch-scoped inventory reads (the warehouse-scope follow-up).

A branch-scoped user only sees inventory/movements for warehouses in their branch(es), and
is rejected when asking for a warehouse in another branch; an unrestricted admin sees all.

Requires a live database (DATABASE_URL) with the RBAC + demo seed; skipped otherwise.
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


def _rand(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


async def _headers(client, email, password) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _branch_wh(client, h) -> tuple[str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()
    wh = (await client.post("/api/v1/warehouses", headers=h, json={
        "code": _rand("WH"), "name": _rand("WH"), "branch_id": br["id"], "is_active": True})).json()
    return br["id"], wh["id"]


async def _role_id(client, h, name) -> str:
    roles = (await client.get("/api/v1/users/roles", headers=h)).json()
    return next(r["id"] for r in roles if r["name"] == name)


async def _receive(client, h, wh, product, qty):
    await client.post("/api/v1/inventory/receive", headers=h, json={
        "warehouse_id": wh, "reference_type": "manual", "lines": [{"product_id": product, "quantity": qty}]})


# ------------------------------------------------------------------------- #
async def test_scoped_user_only_sees_their_branch_inventory(client):
    admin = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    lusaka_br, lusaka_wh = await _branch_wh(client, admin)
    solwezi_br, solwezi_wh = await _branch_wh(client, admin)
    product = (await client.post("/api/v1/products", headers=admin, json={"sku": _rand("SKU"), "name": "Part"})).json()["id"]
    await _receive(client, admin, lusaka_wh, product, 5)
    await _receive(client, admin, solwezi_wh, product, 7)

    email, pw = _rand("lu") + "@demo.com", "ScopeTest123!"
    await client.post("/api/v1/users", headers=admin, json={
        "email": email, "full_name": "Lusaka", "password": pw,
        "role_ids": [await _role_id(client, admin, "Admin")], "branch_ids": [lusaka_br]})
    u = await _headers(client, email, pw)

    # No filter -> only the Lusaka warehouse row; the Solwezi row is invisible.
    rows = (await client.get("/api/v1/inventory", headers=u, params={"product_id": product, "page_size": 100})).json()["items"]
    whs = {r["warehouse_id"] for r in rows}
    assert lusaka_wh in whs and solwezi_wh not in whs

    # Asking for the Solwezi warehouse is rejected server-side.
    r = await client.get("/api/v1/inventory", headers=u, params={"warehouse_id": solwezi_wh})
    assert r.status_code == 403, r.text
    # Movements for another branch's warehouse are rejected too.
    m = await client.get("/api/v1/inventory/movements", headers=u, params={"warehouse_id": solwezi_wh})
    assert m.status_code == 403, m.text

    # The user's own warehouse is fine.
    ok = await client.get("/api/v1/inventory", headers=u, params={"warehouse_id": lusaka_wh})
    assert ok.status_code == 200

    # The unrestricted admin sees both warehouses' rows.
    admin_rows = (await client.get("/api/v1/inventory", headers=admin, params={"product_id": product, "page_size": 100})).json()["items"]
    admin_whs = {r["warehouse_id"] for r in admin_rows}
    assert lusaka_wh in admin_whs and solwezi_wh in admin_whs
