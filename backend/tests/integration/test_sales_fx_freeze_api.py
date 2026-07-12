"""Integration: the USD->ZMW rate is FROZEN onto each sales document at issue.

The load-bearing guarantee: editing the tenant's current rate never re-prices an
existing quotation or invoice; only NEW documents pick up the new rate. Also proves
line ZMW sums to the document ZMW total, and that payments settle in ZMW against the
frozen payable. Requires a live DB + seed.
"""
from __future__ import annotations

import os

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


async def _headers(client, email, password) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest_asyncio.fixture
async def admin_h(client):
    return await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest_asyncio.fixture(autouse=True)
async def _restore_rate(client, admin_h):
    """Other sales tests assume rate 1 (ZMW == USD); always hand it back at 1."""
    yield
    await client.put("/api/v1/tenant/settings", headers=admin_h, json={"fx_rate": "1"})


async def _set_rate(client, admin_h, rate: str) -> None:
    r = await client.put("/api/v1/tenant/settings", headers=admin_h, json={"fx_rate": rate})
    assert r.status_code == 200, r.text


async def _enable_sales(client, admin_h) -> None:
    r = await client.get("/api/v1/tenant/settings", headers=admin_h)
    flags = dict(r.json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    # These fx-freeze tests assert pre-VAT totals; neutralise VAT to isolate the fx rate.
    r = await client.put("/api/v1/tenant/settings", headers=admin_h,
                         json={"feature_flags": flags, "vat_rate": 0})
    assert r.status_code == 200, r.text


async def _customer(client, admin_h) -> str:
    r = await client.post("/api/v1/customers", headers=admin_h, json={"name": "FX Buyer"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _find_stocked(client, admin_h, min_qty=6.0) -> tuple[str, str]:
    r = await client.get("/api/v1/inventory", headers=admin_h, params={"page_size": 200})
    assert r.status_code == 200, r.text
    for row in r.json()["items"]:
        if float(row["qty_available"]) >= min_qty:
            return row["product_id"], row["warehouse_id"]
    pytest.skip("no inventory with enough available stock in the demo data")


async def _invoice_via_flow(client, admin_h, customer_id, product_id, location_id, qty, price):
    so_id = (await client.post("/api/v1/sales/orders", headers=admin_h, json={
        "customer_id": customer_id, "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": qty, "unit_price": price}],
    })).json()["id"]
    await client.post(f"/api/v1/sales/orders/{so_id}/confirm", headers=admin_h)
    dn = (await client.post(f"/api/v1/sales/orders/{so_id}/deliver", headers=admin_h, json={})).json()
    inv = (await client.post("/api/v1/sales/invoices", headers=admin_h,
                             json={"delivery_note_id": dn["id"]})).json()
    return inv


async def test_rate_freezes_on_invoice_and_survives_a_rate_change(client, admin_h):
    await _enable_sales(client, admin_h)
    customer_id = await _customer(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=6)

    await _set_rate(client, admin_h, "20")
    inv = await _invoice_via_flow(client, admin_h, customer_id, product_id, location_id, 3, 100)
    inv_id = inv["id"]
    # USD grand total 300; frozen rate 20 -> ZMW 6000; lines sum to the ZMW total.
    assert inv["fx_rate"] == 20.0
    assert inv["grand_total"] == 300.0
    assert inv["grand_total_zmw"] == 6000.0
    assert round(sum(ln["line_total_zmw"] for ln in inv["lines"]), 2) == inv["grand_total_zmw"]
    assert inv["balance"] == 6000.0  # payable is ZMW

    # Move the CURRENT rate — the issued invoice must not budge.
    await _set_rate(client, admin_h, "25")
    again = (await client.get(f"/api/v1/sales/invoices/{inv_id}", headers=admin_h)).json()
    assert again["fx_rate"] == 20.0
    assert again["grand_total_zmw"] == 6000.0  # NOT re-priced to 300*25

    # A NEW invoice now uses the new rate.
    inv2 = await _invoice_via_flow(client, admin_h, customer_id, product_id, location_id, 1, 100)
    assert inv2["fx_rate"] == 25.0
    assert inv2["grand_total_zmw"] == 2500.0


async def test_payment_settles_in_zmw_against_frozen_total(client, admin_h):
    await _enable_sales(client, admin_h)
    customer_id = await _customer(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=2)

    await _set_rate(client, admin_h, "20")
    inv = await _invoice_via_flow(client, admin_h, customer_id, product_id, location_id, 2, 50)
    assert inv["grand_total"] == 100.0 and inv["grand_total_zmw"] == 2000.0

    # Underpay in ZMW: 1500 of 2000 -> partially paid, ZMW balance 500.
    r = await client.post("/api/v1/sales/payments", headers=admin_h, json={
        "invoice_id": inv["id"], "payments": [{"method": "cash", "amount": 1500}]})
    assert r.status_code == 201, r.text
    assert r.json()["balance"] == 500.0
    got = (await client.get(f"/api/v1/sales/invoices/{inv['id']}", headers=admin_h)).json()
    assert got["status"] == "partially_paid" and got["balance"] == 500.0

    # Paying the remaining ZMW clears it; overpaying beyond the ZMW payable is rejected.
    over = await client.post("/api/v1/sales/payments", headers=admin_h, json={
        "invoice_id": inv["id"], "payments": [{"method": "cash", "amount": 600}]})
    assert over.status_code == 400 and "exceeds" in over.text.lower()
    r = await client.post("/api/v1/sales/payments", headers=admin_h, json={
        "invoice_id": inv["id"], "payments": [{"method": "cash", "amount": 500}]})
    assert r.status_code == 201, r.text
    got = (await client.get(f"/api/v1/sales/invoices/{inv['id']}", headers=admin_h)).json()
    assert got["status"] == "paid" and got["balance"] == 0.0


async def test_quotation_freezes_its_rate(client, admin_h):
    await _enable_sales(client, admin_h)
    customer_id = await _customer(client, admin_h)
    product_id, _loc = await _find_stocked(client, admin_h, min_qty=1)

    await _set_rate(client, admin_h, "20")
    quote = (await client.post("/api/v1/sales/quotations", headers=admin_h, json={
        "customer_id": customer_id,
        "lines": [{"product_id": product_id, "qty": 2, "unit_price": 100}],
    })).json()
    assert quote["fx_rate"] == 20.0
    assert quote["grand_total_zmw"] == 4000.0  # 200 USD * 20

    await _set_rate(client, admin_h, "30")
    again = (await client.get(f"/api/v1/sales/quotations/{quote['id']}", headers=admin_h)).json()
    assert again["fx_rate"] == 20.0 and again["grand_total_zmw"] == 4000.0
