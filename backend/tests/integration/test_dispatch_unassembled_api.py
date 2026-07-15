"""Integration: dispatching a bike SOLD before assembly is blocked unless a manager overrides.

A customer SALE delivery is the physical handover. A bike sold before assembly (assembly_pending)
isn't built yet, so the handover is blocked — unless a sales.manage holder overrides, which
records the override on the unit. Consignment (the reseller path) is exempt and covered elsewhere.

Requires a live DB + seed.
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


async def _headers(client) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _enable_sales(client, h) -> None:
    flags = dict((await client.get("/api/v1/tenant/settings", headers=h)).json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    assert (await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags})).status_code == 200


async def _warehouse(client, h) -> tuple[str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    wh = (await client.post("/api/v1/warehouses", headers=h, json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": br, "is_active": True})).json()["id"]
    return wh, br


async def _unit(client, h, wh, br, *, assembly_required: bool) -> dict:
    model = (await client.post("/api/v1/motorcycles/models", headers=h, json={"brand": _rand("Br"), "name": _rand("Md")})).json()["id"]
    r = await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "model_id": model, "warehouse_id": wh, "branch_id": br,
        "selling_price": 20000, "assembly_required": assembly_required})
    assert r.status_code == 201, r.text
    return r.json()


async def _sale_delivery(client, h, wh, invoice_id) -> dict:
    r = await client.post("/api/v1/customer-deliveries", headers=h, json={
        "delivery_mode": "sale", "from_warehouse_id": wh, "invoice_id": invoice_id})
    assert r.status_code == 201, r.text
    return r.json()


async def test_dispatch_blocked_before_assembly_then_manager_override(client):
    h = await _headers(client)
    await _enable_sales(client, h)
    wh, br = await _warehouse(client, h)
    unit = await _unit(client, h, wh, br, assembly_required=True)
    assert unit["status"] == "unassembled"

    # Sell it before assembly -> sold, assembly still owed.
    sale = (await client.post("/api/v1/sales/bike-sale", headers=h, json={"unit_id": unit["id"], "price": 20000})).json()
    inv_id = sale["invoice"]["id"]

    cd = await _sale_delivery(client, h, wh, inv_id)
    # The bike line reports the outstanding assembly.
    bike_line = next(ln for ln in cd["lines"] if ln["line_kind"] == "motorcycle")
    assert bike_line["assembly_pending"] is True

    # Plain dispatch is blocked.
    r = await client.post(f"/api/v1/customer-deliveries/{cd['id']}/deliver", headers=h, json={"received_by": "x"})
    assert r.status_code == 400 and "not yet assembled" in r.text.lower()
    assert (await client.get(f"/api/v1/customer-deliveries/{cd['id']}", headers=h)).json()["status"] == "draft"

    # Manager override (admin holds sales.manage) releases it, and records the override.
    r = await client.post(f"/api/v1/customer-deliveries/{cd['id']}/deliver", headers=h,
                          json={"received_by": "x", "override_unassembled": True})
    assert r.status_code == 200 and r.json()["status"] == "delivered"
    events = (await client.get(f"/api/v1/motorcycles/units/{unit['id']}", headers=h)).json()["events"]
    assert any(e["event_type"] == "dispatched_unassembled" for e in events)


async def test_assembled_bike_dispatches_without_override(client):
    h = await _headers(client)
    await _enable_sales(client, h)
    wh, br = await _warehouse(client, h)
    unit = await _unit(client, h, wh, br, assembly_required=False)   # ready on arrival
    assert unit["status"] == "assembled"

    sale = (await client.post("/api/v1/sales/bike-sale", headers=h, json={"unit_id": unit["id"], "price": 20000})).json()
    cd = await _sale_delivery(client, h, wh, sale["invoice"]["id"])
    bike_line = next(ln for ln in cd["lines"] if ln["line_kind"] == "motorcycle")
    assert bike_line["assembly_pending"] is False

    r = await client.post(f"/api/v1/customer-deliveries/{cd['id']}/deliver", headers=h, json={"received_by": "x"})
    assert r.status_code == 200 and r.json()["status"] == "delivered"
