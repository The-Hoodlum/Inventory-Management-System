"""Integration tests for the product wholesale price: create/read via API + catalog import.

Requires a live database (DATABASE_URL) with the RBAC + demo seed; skipped otherwise.
"""
from __future__ import annotations

import io
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


async def test_create_and_update_product_carries_wholesale_price(client):
    h = await _headers(client)
    sku = _rand("SKU")
    r = await client.post("/api/v1/products", headers=h, json={
        "sku": sku, "name": "Trade item", "cost_price": "2.26",
        "selling_price": "6.44", "wholesale_price": "5.08"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["wholesale_price"] in ("5.08", "5.0800")

    got = await client.get(f"/api/v1/products/{pid}", headers=h)
    assert float(got.json()["wholesale_price"]) == 5.08

    upd = await client.patch(f"/api/v1/products/{pid}", headers=h, json={"wholesale_price": "4.00"})
    assert upd.status_code == 200 and float(upd.json()["wholesale_price"]) == 4.0

    # Default when omitted -> 0.
    r2 = await client.post("/api/v1/products", headers=h, json={"sku": _rand("SKU"), "name": "No wholesale"})
    assert float(r2.json()["wholesale_price"]) == 0.0


async def test_catalog_import_loads_wholesale_from_the_sheet(client):
    h = await _headers(client)
    sku = _rand("SKU")
    buf = io.StringIO()
    import csv
    w = csv.writer(buf)
    w.writerow(["SKU", "Item Name", "Quantity On Hand", "Cost Price", "Retail", "Wholesale"])
    w.writerow([sku, "Imported trade item", "0", "2.26", "6.44", "5.08"])
    files = {"file": ("catalog.csv", buf.getvalue().encode("utf-8"), "text/csv")}

    up = (await client.post("/api/v1/imports/inventory/upload", headers=h, files=files)).json()
    body = {"mapping": up["detected_mapping"],
            "options": {"warehouse_mode": "create", "default_warehouse": _rand("WH"), "value_maps": []}}
    await client.post(f"/api/v1/imports/inventory/{up['job_id']}/preview", headers=h, json=body)
    await client.post(f"/api/v1/imports/inventory/{up['job_id']}/confirm", headers=h, json=body)

    # The inventory import is the streaming target (background runner) — poll to completion.
    import asyncio
    for _ in range(50):
        job = (await client.get(f"/api/v1/imports/{up['job_id']}", headers=h)).json()
        if job["status"] in ("completed", "failed", "cancelled"):
            break
        await asyncio.sleep(0.1)
    assert job["status"] == "completed", job

    found = (await client.get("/api/v1/products", headers=h, params={"search": sku})).json()["items"]
    assert found and float(found[0]["wholesale_price"]) == 5.08  # 'Wholesale' alias detected
