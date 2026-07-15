"""Integration: assembly events fire notifications (notifications Phase 2).

- selling a bike BEFORE assembly notifies the workshop (motorcycle.manage), not the actor;
- assembling a sold-before-assembly bike notifies the salesperson who sold it;
- a manager override that dispatches an unassembled bike notifies managers (sales.manage);
- a reseller sale (assembly not owed) notifies no one.

A Branch Manager holds both motorcycle.manage and sales.manage, so one extra user receives
all the branch-targeted events. Requires a live DB; skipped otherwise.
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


async def _make_manager(client, admin_h, password) -> dict:
    roles = (await client.get("/api/v1/users/roles", headers=admin_h)).json()
    role_id = next(r["id"] for r in roles if r["name"] == "Branch Manager")
    email = _rand("mgr") + "@demo.com"
    r = await client.post("/api/v1/users", headers=admin_h, json={
        "email": email, "full_name": "Branch Mgr", "password": password, "role_ids": [role_id]})
    assert r.status_code == 201, r.text
    return {"email": email, "password": password}


async def _enable_sales(client, h) -> None:
    flags = dict((await client.get("/api/v1/tenant/settings", headers=h)).json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    assert (await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags})).status_code == 200


async def _warehouse(client, h) -> tuple[str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    wh = (await client.post("/api/v1/warehouses", headers=h, json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": br, "is_active": True})).json()["id"]
    return wh, br


async def _unassembled_unit(client, h, wh, br) -> dict:
    model = (await client.post("/api/v1/motorcycles/models", headers=h, json={"brand": _rand("Br"), "name": _rand("Md")})).json()["id"]
    return (await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "model_id": model, "warehouse_id": wh, "branch_id": br,
        "selling_price": 20000, "assembly_required": True})).json()


async def _notifs(client, h, event_type: str, chassis: str | None = None) -> list[dict]:
    items = (await client.get("/api/v1/notifications", headers=h)).json()["items"]
    return [i for i in items if i["event_type"] == event_type and (chassis is None or chassis in i["title"])]


# ------------------------------------------------------------------------- #
async def test_sold_before_assembly_notifies_workshop_not_actor(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    mgr = await _make_manager(client, admin_h, "MgrPass123")
    mgr_h = await _headers(client, mgr["email"], mgr["password"])
    wh, br = await _warehouse(client, admin_h)
    unit = await _unassembled_unit(client, admin_h, wh, br)

    await client.post("/api/v1/sales/bike-sale", headers=admin_h, json={"unit_id": unit["id"], "price": 20000})

    ch = unit["chassis_number"]
    assert len(await _notifs(client, mgr_h, "bike.sold_before_assembly", ch)) == 1   # workshop notified
    assert await _notifs(client, admin_h, "bike.sold_before_assembly", ch) == []     # actor excluded


async def test_assembled_notifies_the_salesperson(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    mgr = await _make_manager(client, admin_h, "MgrPass123")
    mgr_h = await _headers(client, mgr["email"], mgr["password"])
    wh, br = await _warehouse(client, admin_h)
    unit = await _unassembled_unit(client, admin_h, wh, br)

    # Admin sells (is the salesperson); the manager assembles it.
    await client.post("/api/v1/sales/bike-sale", headers=admin_h, json={"unit_id": unit["id"], "price": 20000})
    assert (await client.post(f"/api/v1/motorcycles/units/{unit['id']}/assemble", headers=mgr_h, json={})).status_code == 200

    ch = unit["chassis_number"]
    assert len(await _notifs(client, admin_h, "bike.assembled", ch)) == 1   # the seller is told it's ready


async def test_dispatch_override_notifies_managers(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    mgr = await _make_manager(client, admin_h, "MgrPass123")
    mgr_h = await _headers(client, mgr["email"], mgr["password"])
    wh, br = await _warehouse(client, admin_h)
    unit = await _unassembled_unit(client, admin_h, wh, br)

    sale = (await client.post("/api/v1/sales/bike-sale", headers=admin_h, json={"unit_id": unit["id"], "price": 20000})).json()
    cd = (await client.post("/api/v1/customer-deliveries", headers=admin_h, json={
        "delivery_mode": "sale", "from_warehouse_id": wh, "invoice_id": sale["invoice"]["id"]})).json()
    r = await client.post(f"/api/v1/customer-deliveries/{cd['id']}/deliver", headers=admin_h,
                          json={"received_by": "x", "override_unassembled": True})
    assert r.status_code == 200, r.text

    assert len(await _notifs(client, mgr_h, "bike.dispatched_unassembled")) >= 1
    assert await _notifs(client, admin_h, "bike.dispatched_unassembled") == []   # actor excluded


async def test_reseller_sale_notifies_no_one(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    mgr = await _make_manager(client, admin_h, "MgrPass123")
    mgr_h = await _headers(client, mgr["email"], mgr["password"])
    wh, br = await _warehouse(client, admin_h)
    unit = await _unassembled_unit(client, admin_h, wh, br)

    # assembly_required=False -> nothing owed -> no notification.
    await client.post("/api/v1/sales/bike-sale", headers=admin_h,
                      json={"unit_id": unit["id"], "price": 20000, "assembly_required": False})
    assert await _notifs(client, mgr_h, "bike.sold_before_assembly", unit["chassis_number"]) == []
