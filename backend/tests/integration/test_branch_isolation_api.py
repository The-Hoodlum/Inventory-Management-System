"""Integration tests for server-side branch isolation (the Lusaka-sees-Solwezi bug).

A user assigned to one branch: (1) /auth/me reports that branch, (2) is rejected when it
asks for another branch's data, (3) sees only its own branch when it gives no filter, while
an unrestricted admin sees both. Also: the user-admin API assigns + returns branch_ids.

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


async def _branch_with_wh(client, h) -> tuple[str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()
    wh = (await client.post("/api/v1/warehouses", headers=h, json={
        "code": _rand("WH"), "name": _rand("WH"), "branch_id": br["id"], "is_active": True})).json()
    return br["id"], wh["id"]


async def _make_unit(client, h, branch_id, wh_id) -> str:
    model = (await client.post("/api/v1/motorcycles/models", headers=h,
                               json={"brand": _rand("Br"), "name": _rand("Md")})).json()["id"]
    return (await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "model_id": model, "warehouse_id": wh_id, "branch_id": branch_id})).json()["id"]


async def _admin_role_id(client, h) -> str:
    roles = (await client.get("/api/v1/users/roles", headers=h)).json()
    admin = next((r for r in roles if r["name"] == "Admin"), roles[0])
    return admin["id"]


async def _enable_sales(client, admin_h) -> None:
    r = await client.get("/api/v1/tenant/settings", headers=admin_h)
    flags = dict(r.json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    r = await client.put("/api/v1/tenant/settings", headers=admin_h, json={"feature_flags": flags})
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------------- #
async def test_branch_scoped_user_cannot_see_other_branch(client):
    admin = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    lusaka_br, lusaka_wh = await _branch_with_wh(client, admin)
    solwezi_br, solwezi_wh = await _branch_with_wh(client, admin)
    lusaka_unit = await _make_unit(client, admin, lusaka_br, lusaka_wh)
    solwezi_unit = await _make_unit(client, admin, solwezi_br, solwezi_wh)

    # Create a user scoped to Lusaka only (Admin role for read perms; branch_ids restricts data).
    role_id = await _admin_role_id(client, admin)
    email = _rand("lusaka") + "@demo.com"
    pw = "ScopeTest123!"
    created = await client.post("/api/v1/users", headers=admin, json={
        "email": email, "full_name": "Lusaka Mgr", "password": pw,
        "role_ids": [role_id], "branch_ids": [lusaka_br]})
    assert created.status_code == 201, created.text
    assert created.json()["branch_ids"] == [lusaka_br]  # admin API round-trips the grant

    u = await _headers(client, email, pw)

    # (1) /auth/me reports the assigned branch.
    me = (await client.get("/api/v1/auth/me", headers=u)).json()
    assert me["accessible_branch_ids"] == [lusaka_br]

    # (2) asking for Solwezi is rejected server-side (never trust the client branch).
    r = await client.get("/api/v1/motorcycles/units", headers=u, params={"branch_id": solwezi_br})
    assert r.status_code == 403, r.text

    # (3) no filter -> only Lusaka units; Solwezi's unit is invisible.
    seen = (await client.get("/api/v1/motorcycles/units", headers=u, params={"page_size": 200})).json()
    ids = {it["id"] for it in seen["items"]}
    assert lusaka_unit in ids and solwezi_unit not in ids

    # The unrestricted admin still sees both.
    both = (await client.get("/api/v1/motorcycles/units", headers=admin, params={"page_size": 200})).json()
    admin_ids = {it["id"] for it in both["items"]}
    assert lusaka_unit in admin_ids and solwezi_unit in admin_ids

    # (4) WRITES are branch-scoped too — a scoped user can't sell into another branch.
    await _enable_sales(client, admin)
    # Bike-sale for a Solwezi unit -> 403 (scope checked before sellability).
    r = await client.post("/api/v1/sales/bike-sale", headers=u,
                          json={"unit_id": solwezi_unit, "price": 1000})
    assert r.status_code == 403, r.text
    assert "assigned" in r.text.lower()  # the branch check, not a permission/feature 403
    # POS checkout at a Solwezi location -> 403 (never trust the client-supplied location).
    r = await client.post("/api/v1/sales/pos/checkout", headers=u, json={
        "location_id": solwezi_wh,
        "lines": [{"product_id": str(uuid.uuid4()), "qty": 1, "unit_price": 1}],
        "payments": [{"method": "cash", "amount": 1}]})
    assert r.status_code == 403, r.text
    assert "assigned" in r.text.lower()


async def test_admin_can_update_a_users_branch_assignment(client):
    admin = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    a_br, _ = await _branch_with_wh(client, admin)
    b_br, _ = await _branch_with_wh(client, admin)
    role_id = await _admin_role_id(client, admin)
    email = _rand("u") + "@demo.com"
    uid = (await client.post("/api/v1/users", headers=admin, json={
        "email": email, "full_name": "U", "password": "ScopeTest123!",
        "role_ids": [role_id], "branch_ids": [a_br]})).json()["id"]

    # Reassign to branch B.
    upd = await client.patch(f"/api/v1/users/{uid}", headers=admin, json={"branch_ids": [b_br]})
    assert upd.status_code == 200 and upd.json()["branch_ids"] == [b_br]

    # Clear the scope (empty = all branches).
    cleared = await client.patch(f"/api/v1/users/{uid}", headers=admin, json={"branch_ids": []})
    assert cleared.status_code == 200 and cleared.json()["branch_ids"] == []
