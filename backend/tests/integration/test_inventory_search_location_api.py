"""Integration: inventory search (name / SKU / location) + product storage location.

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


async def _headers(client) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _rand(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


async def test_product_location_roundtrip_and_inventory_search(client):
    h = await _headers(client)
    loc = _rand("BIN")
    sku = _rand("SKU")

    # A product carrying a storage location.
    p = (await client.post("/api/v1/products", headers=h, json={
        "sku": sku, "name": f"Locatable {sku}", "location": loc})).json()
    assert p["location"] == loc
    pid = p["id"]

    # Receive some stock so it shows in inventory.
    wh = (await client.get("/api/v1/warehouses", headers=h)).json()["items"][0]["id"]
    r = await client.post("/api/v1/inventory/receive", headers=h, json={
        "warehouse_id": wh, "lines": [{"product_id": pid, "quantity": "5"}]})
    assert r.status_code == 201, r.text

    # Search finds it by SKU, by a name fragment, and by location.
    for term in (sku, "Locatable", loc):
        rows = (await client.get("/api/v1/inventory", headers=h, params={"search": term})).json()["items"]
        assert any(x["product_id"] == pid for x in rows), (term, rows)

    # A non-matching search excludes it.
    none = (await client.get("/api/v1/inventory", headers=h, params={"search": _rand("ZZZ")})).json()["items"]
    assert all(x["product_id"] != pid for x in none)

    # Location is editable.
    new_loc = _rand("BIN2")
    upd = await client.patch(f"/api/v1/products/{pid}", headers=h, json={"location": new_loc})
    assert upd.status_code == 200 and upd.json()["location"] == new_loc
