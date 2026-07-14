"""Integration: selling a motorcycle BEFORE it is assembled.

- a unit can be sold straight from 'unassembled'; it becomes 'sold' with assembly still
  owed (assembly_pending) and shows up in the assembly queue;
- marking it assembled clears the flag + records the date, and it leaves the queue;
- a reseller sale (assembly_required=false) leaves no assembly owed;
- voiding a before-assembly sale returns the unit to 'unassembled', not 'assembled'.

Requires a live database; skipped otherwise.
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


async def _unassembled_unit(client, h, *, price: float) -> dict:
    model = (await client.post("/api/v1/motorcycles/models", headers=h,
             json={"name": _rand("Model"), "brand": "TVS"})).json()
    r = await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "engine_number": _rand("EN"),
        "model_id": model["id"], "selling_price": price, "assembly_required": True})
    assert r.status_code == 201, r.text
    u = r.json()
    assert u["status"] == "unassembled" and u["assembled_date"] is None
    return u


async def _unit(client, h, unit_id):
    return (await client.get(f"/api/v1/motorcycles/units/{unit_id}", headers=h)).json()


async def test_sell_unassembled_queues_assembly_then_clears(client):
    h = await _headers(client)
    await _enable_sales(client, h)
    unit = await _unassembled_unit(client, h, price=20000)

    # Sell it while unassembled (dealership will assemble -> assembly owed).
    r = await client.post("/api/v1/sales/bike-sale", headers=h, json={"unit_id": unit["id"], "price": 20000})
    assert r.status_code == 201, r.text

    u = await _unit(client, h, unit["id"])
    assert u["status"] == "sold"            # the sale status still becomes 'sold'
    assert u["assembly_pending"] is True    # ... but assembly is still owed
    assert u["assembled_date"] is None

    # It appears in the assembly queue.
    q = (await client.get("/api/v1/motorcycles/units", headers=h, params={"assembly_pending": "true", "page_size": 200})).json()
    assert unit["id"] in {it["id"] for it in q["items"]}

    # Mark it assembled — stays 'sold', clears the flag, records the date, leaves the queue.
    r = await client.post(f"/api/v1/motorcycles/units/{unit['id']}/assemble", headers=h, json={"note": "built"})
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["status"] == "sold" and u["assembly_pending"] is False and u["assembled_date"] is not None
    q = (await client.get("/api/v1/motorcycles/units", headers=h, params={"assembly_pending": "true", "page_size": 200})).json()
    assert unit["id"] not in {it["id"] for it in q["items"]}


async def test_reseller_sale_owes_no_assembly(client):
    h = await _headers(client)
    await _enable_sales(client, h)
    unit = await _unassembled_unit(client, h, price=20000)

    # A reseller assembles it themselves -> assembly_required False -> nothing owed.
    r = await client.post("/api/v1/sales/bike-sale", headers=h,
                          json={"unit_id": unit["id"], "price": 20000, "assembly_required": False})
    assert r.status_code == 201, r.text
    u = await _unit(client, h, unit["id"])
    assert u["status"] == "sold" and u["assembly_pending"] is False


async def test_voiding_before_assembly_sale_returns_to_unassembled(client):
    h = await _headers(client)
    await _enable_sales(client, h)
    unit = await _unassembled_unit(client, h, price=20000)
    inv = (await client.post("/api/v1/sales/bike-sale", headers=h,
           json={"unit_id": unit["id"], "price": 20000})).json()["invoice"]

    r = await client.post(f"/api/v1/sales/invoices/{inv['id']}/void", headers=h, json={"reason": "test"})
    assert r.status_code == 200, r.text
    u = await _unit(client, h, unit["id"])
    assert u["status"] == "unassembled"     # NOT 'assembled' — it was never assembled
    assert u["assembly_pending"] is False and u["sold_ref"] is None
