"""Integration tests for branch-scoped report aggregations.

A MULTI-branch user must see ALL their branches in the aggregations (not just one — the bug
the single-branch default caused), a specific allowed branch when asked, a 403 on a branch
they aren't scoped to, while an unrestricted admin sees every branch.

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


def _branches_for_product(rows, product_id):
    return {r["branch_id"] for r in rows if r["product_id"] == product_id}


# ------------------------------------------------------------------------- #
async def test_multi_branch_user_sees_all_their_branches_in_stock_position(client):
    admin = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    a_br, a_wh = await _branch_wh(client, admin)
    b_br, b_wh = await _branch_wh(client, admin)
    c_br, c_wh = await _branch_wh(client, admin)
    product = (await client.post("/api/v1/products", headers=admin, json={"sku": _rand("SKU"), "name": "Part"})).json()["id"]
    for wh in (a_wh, b_wh, c_wh):
        await _receive(client, admin, wh, product, 3)

    # A user scoped to TWO branches (A and B).
    email, pw = _rand("mgr") + "@demo.com", "ScopeTest123!"
    await client.post("/api/v1/users", headers=admin, json={
        "email": email, "full_name": "Regional", "password": pw,
        "role_ids": [await _role_id(client, admin, "Admin")], "branch_ids": [a_br, b_br]})
    u = await _headers(client, email, pw)

    # Sees BOTH A and B (not just one), never C.
    rows = (await client.get("/api/v1/reports/stock-position", headers=u)).json()["rows"]
    seen = _branches_for_product(rows, product)
    assert a_br in seen and b_br in seen and c_br not in seen

    # A specific allowed branch narrows correctly.
    only_a = (await client.get("/api/v1/reports/stock-position", headers=u, params={"branch_id": a_br})).json()["rows"]
    assert _branches_for_product(only_a, product) == {a_br}

    # A branch they aren't scoped to is rejected (both report endpoints).
    assert (await client.get("/api/v1/reports/stock-position", headers=u, params={"branch_id": c_br})).status_code == 403
    assert (await client.get("/api/v1/reports/sales-log", headers=u, params={"branch_id": c_br})).status_code == 403

    # The unrestricted admin sees all three branches.
    admin_rows = (await client.get("/api/v1/reports/stock-position", headers=admin)).json()["rows"]
    admin_seen = _branches_for_product(admin_rows, product)
    assert {a_br, b_br, c_br}.issubset(admin_seen)
