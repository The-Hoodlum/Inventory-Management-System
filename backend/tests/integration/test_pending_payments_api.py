"""Integration test for the accounts-receivable endpoint:

GET /api/v1/sales/invoices/outstanding lists invoices that still owe money (balance
> 0), across parts and bike invoices, and drops them the moment they are settled or
voided.

Requires a live database (DATABASE_URL) with the RBAC + demo seed; skipped otherwise.
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


async def _enable_sales(client, admin_h) -> None:
    r = await client.get("/api/v1/tenant/settings", headers=admin_h)
    flags = dict(r.json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    # Neutralise VAT so the asserted balances are the raw line totals (VAT math is covered
    # by the VAT tests); the AR math is orthogonal to it.
    r = await client.put("/api/v1/tenant/settings", headers=admin_h,
                         json={"feature_flags": flags, "vat_rate": 0})
    assert r.status_code == 200, r.text


async def _customer(client, admin_h, name="AR Customer") -> str:
    r = await client.post("/api/v1/customers", headers=admin_h, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _find_stocked(client, admin_h, min_qty=6.0) -> tuple[str, str]:
    r = await client.get("/api/v1/inventory", headers=admin_h, params={"page_size": 200})
    assert r.status_code == 200, r.text
    for row in r.json()["items"]:
        if float(row["qty_available"]) >= min_qty:
            return row["product_id"], row["warehouse_id"]
    pytest.skip("no inventory with enough available stock in the demo data")


async def _make_invoice(client, admin_h, customer_id, product_id, location_id, *, qty, price) -> dict:
    """order -> confirm (reserve) -> deliver (issue) -> invoice; returns the unpaid invoice."""
    so_id = (await client.post("/api/v1/sales/orders", headers=admin_h, json={
        "customer_id": customer_id, "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": qty, "unit_price": price}],
    })).json()["id"]
    await client.post(f"/api/v1/sales/orders/{so_id}/confirm", headers=admin_h)
    delivery = (await client.post(f"/api/v1/sales/orders/{so_id}/deliver",
                                  headers=admin_h, json={})).json()
    r = await client.post("/api/v1/sales/invoices", headers=admin_h,
                          json={"delivery_note_id": delivery["id"]})
    assert r.status_code == 201, r.text
    return r.json()


async def _outstanding(client, admin_h, **params) -> list[dict]:
    r = await client.get("/api/v1/sales/invoices/outstanding", headers=admin_h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_outstanding_tracks_balance_and_excludes_settled_and_voided(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    customer_id = await _customer(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=6)

    # A fresh unpaid invoice of 300 shows up with its full balance.
    invoice = await _make_invoice(client, admin_h, customer_id, product_id, location_id, qty=3, price=100)
    assert invoice["balance"] == 300.0

    def find(rows, iid):
        return next((x for x in rows if x["id"] == iid), None)

    row = find(await _outstanding(client, admin_h, customer_id=customer_id), invoice["id"])
    assert row is not None, "unpaid invoice missing from the AR list"
    assert row["balance"] == 300.0
    assert row["status"] in ("draft", "sent", "partially_paid", "overdue")

    # Part-pay 120 -> still outstanding, balance 180, status partially_paid.
    r = await client.post("/api/v1/sales/payments", headers=admin_h, json={
        "invoice_id": invoice["id"], "payments": [{"method": "cash", "amount": 120}]})
    assert r.status_code == 201, r.text
    row = find(await _outstanding(client, admin_h, customer_id=customer_id), invoice["id"])
    assert row is not None and row["balance"] == 180.0
    assert row["status"] == "partially_paid"

    # Settle the remaining 180 -> the invoice leaves the AR list entirely.
    r = await client.post("/api/v1/sales/payments", headers=admin_h, json={
        "invoice_id": invoice["id"], "payments": [{"method": "card", "amount": 180}]})
    assert r.status_code == 201, r.text
    rows = await _outstanding(client, admin_h, customer_id=customer_id)
    assert find(rows, invoice["id"]) is None, "paid invoice must not appear in AR"

    # A voided invoice is never receivable: create another, void it, assert it's absent.
    inv2 = await _make_invoice(client, admin_h, customer_id, product_id, location_id, qty=2, price=100)
    assert find(await _outstanding(client, admin_h, customer_id=customer_id), inv2["id"]) is not None
    r = await client.post(f"/api/v1/sales/invoices/{inv2['id']}/void", headers=admin_h,
                          json={"reason": "AR test cleanup"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "voided"
    assert find(await _outstanding(client, admin_h, customer_id=customer_id), inv2["id"]) is None
