"""Integration: selling a serialized bike from Sales/POS via POST /sales/bike-sale.

Creates a bike invoice, marks the unit sold + linked, and (with payments) settles into a
receipt. Requires a live database; skipped otherwise.
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


async def _assembled_unit(client, h, *, price: float) -> dict:
    brand = (await client.post("/api/v1/motorcycles/models", headers=h,
             json={"name": _rand("Model"), "brand": "TVS"})).json()
    r = await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "engine_number": _rand("EN"),
        "model_id": brand["id"], "selling_price": price})   # assembly_required omitted -> assembled
    assert r.status_code == 201, r.text
    return r.json()


async def test_bike_sale_invoices_marks_sold_and_receipts(client):
    h = await _headers(client)
    unit = await _assembled_unit(client, h, price=25000)
    assert unit["status"] == "assembled"

    # Sell it with a full cash payment (fx defaults to 1 on a fresh tenant -> ZMW == USD).
    r = await client.post("/api/v1/sales/bike-sale", headers=h, json={
        "unit_id": unit["id"], "price": 25000,
        "payments": [{"method": "cash", "amount": 25000}]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["chassis_number"] == unit["chassis_number"]
    assert body["invoice"]["id"]
    assert body["receipt"] is not None                       # payment settled -> receipt

    # The unit is now sold and linked to that invoice.
    u = (await client.get(f"/api/v1/motorcycles/units/{unit['id']}", headers=h)).json()
    assert u["status"] == "sold"
    assert u["sold_ref"] == body["invoice"]["id"]
    assert float(u["price_charged"]) == 25000

    # A non-sellable (already sold) unit is rejected.
    r2 = await client.post("/api/v1/sales/bike-sale", headers=h, json={"unit_id": unit["id"], "price": 100})
    assert r2.status_code == 400, r2.text


async def test_bike_sale_without_payment_is_invoice_only(client):
    h = await _headers(client)
    unit = await _assembled_unit(client, h, price=18000)

    r = await client.post("/api/v1/sales/bike-sale", headers=h, json={"unit_id": unit["id"], "price": 18000})
    assert r.status_code == 201, r.text
    assert r.json()["receipt"] is None                       # no payment -> no receipt
    u = (await client.get(f"/api/v1/motorcycles/units/{unit['id']}", headers=h)).json()
    assert u["status"] == "sold"
