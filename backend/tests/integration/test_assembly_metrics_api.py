"""Integration: the assembly roll-up on /motorcycles/metrics + the invoice PDF flag.

Uses deltas (the tenant may already hold bikes) to assert that selling a bike before assembly
moves it from 'unassembled in stock' to 'awaiting assembly', that assembling it clears the
count, and that the bike invoice PDF renders (with the NOT-YET-ASSEMBLED flag) throughout.

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


async def _metrics(client, h) -> dict:
    return (await client.get("/api/v1/motorcycles/metrics", headers=h)).json()


async def test_assembly_metrics_and_invoice_pdf(client):
    h = await _headers(client)
    await _enable_sales(client, h)
    base = await _metrics(client, h)
    assert "waiting_for_assembly" in base and "unassembled_in_stock" in base

    model = (await client.post("/api/v1/motorcycles/models", headers=h, json={"brand": _rand("Br"), "name": _rand("Md")})).json()["id"]
    unit = (await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "model_id": model, "selling_price": 20000, "assembly_required": True})).json()
    assert unit["status"] == "unassembled"

    m1 = await _metrics(client, h)
    assert m1["unassembled_in_stock"] == base["unassembled_in_stock"] + 1
    assert m1["waiting_for_assembly"] == base["waiting_for_assembly"]

    # Sell before assembly -> leaves 'unassembled in stock', joins 'awaiting assembly'.
    sale = (await client.post("/api/v1/sales/bike-sale", headers=h, json={"unit_id": unit["id"], "price": 20000})).json()
    m2 = await _metrics(client, h)
    assert m2["unassembled_in_stock"] == base["unassembled_in_stock"]
    assert m2["waiting_for_assembly"] == base["waiting_for_assembly"] + 1

    # The bike invoice PDF renders (carries the NOT-YET-ASSEMBLED flag internally).
    pdf = await client.get(f"/api/v1/sales/invoices/{sale['invoice']['id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    # Assembling it clears the queue count.
    assert (await client.post(f"/api/v1/motorcycles/units/{unit['id']}/assemble", headers=h, json={})).status_code == 200
    m3 = await _metrics(client, h)
    assert m3["waiting_for_assembly"] == base["waiting_for_assembly"]
