"""Integration tests for the Sales & Distribution engine over HTTP:

customer -> quotation -> convert -> sales order -> confirm (RESERVE) -> deliver
(DEDUCT) -> invoice -> split payment -> receipt, plus POS fast-sale, the
reservation/inventory math, and a permission boundary.

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


async def _headers(client, email, password) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _enable_sales(client, admin_h) -> None:
    r = await client.get("/api/v1/tenant/settings", headers=admin_h)
    flags = dict(r.json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    r = await client.put("/api/v1/tenant/settings", headers=admin_h, json={"feature_flags": flags})
    assert r.status_code == 200, r.text


async def _customer(client, admin_h) -> str:
    r = await client.post("/api/v1/customers", headers=admin_h, json={"name": "ACME Ltd"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _find_stocked(client, admin_h, min_qty=10.0) -> tuple[str, str]:
    r = await client.get("/api/v1/inventory", headers=admin_h, params={"page_size": 200})
    assert r.status_code == 200, r.text
    for row in r.json()["items"]:
        if float(row["qty_available"]) >= min_qty:
            return row["product_id"], row["warehouse_id"]
    pytest.skip("no inventory with enough available stock in the demo data")


async def _inv(client, h, product_id, wh_id) -> dict:
    r = await client.get("/api/v1/inventory", headers=h,
                         params={"product_id": product_id, "warehouse_id": wh_id})
    assert r.status_code == 200, r.text
    it = r.json()["items"][0]
    return {k: float(it[k]) for k in ("qty_on_hand", "qty_available", "qty_reserved")}


async def _role_id(client, admin_h, name) -> str:
    r = await client.get("/api/v1/users/roles", headers=admin_h)
    role = next((x for x in r.json() if x["name"] == name), None)
    assert role, f"role {name} missing — re-seed"
    return role["id"]


# --------------------- quote -> SO -> reserve -> deliver -> invoice -> pay -- #
async def test_full_sales_flow(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    customer_id = await _customer(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=10)
    inv0 = await _inv(client, admin_h, product_id, location_id)

    # Quotation
    r = await client.post("/api/v1/sales/quotations", headers=admin_h, json={
        "customer_id": customer_id,
        "lines": [{"product_id": product_id, "qty": 5, "unit_price": 100, "tax_pct": 10}],
    })
    assert r.status_code == 201, r.text
    quote = r.json()
    assert quote["grand_total"] == 550.0  # 5*100 + 10% tax

    # Convert -> sales order
    r = await client.post(f"/api/v1/sales/quotations/{quote['id']}/convert", headers=admin_h,
                          json={"location_id": location_id})
    assert r.status_code == 201, r.text
    so = r.json()
    so_id = so["id"]
    assert so["status"] == "draft" and so["quotation_id"] == quote["id"]

    # Confirm -> reserves stock (available drops, on-hand unchanged)
    r = await client.post(f"/api/v1/sales/orders/{so_id}/confirm", headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"
    inv1 = await _inv(client, admin_h, product_id, location_id)
    assert inv1["qty_on_hand"] == inv0["qty_on_hand"]
    assert inv1["qty_reserved"] == inv0["qty_reserved"] + 5
    assert inv1["qty_available"] == inv0["qty_available"] - 5

    # Deliver -> deducts on-hand (consumes reservation)
    r = await client.post(f"/api/v1/sales/orders/{so_id}/deliver", headers=admin_h, json={})
    assert r.status_code == 201, r.text
    delivery = r.json()
    assert delivery["status"] == "delivered"
    inv2 = await _inv(client, admin_h, product_id, location_id)
    assert inv2["qty_on_hand"] == inv0["qty_on_hand"] - 5
    assert inv2["qty_reserved"] == inv0["qty_reserved"]  # hold consumed

    # SO now delivered
    r = await client.get(f"/api/v1/sales/orders/{so_id}", headers=admin_h)
    assert r.json()["status"] == "delivered"

    # Invoice the delivery (no inventory effect)
    r = await client.post("/api/v1/sales/invoices", headers=admin_h, json={
        "delivery_note_id": delivery["id"]})
    assert r.status_code == 201, r.text
    invoice = r.json()
    assert invoice["grand_total"] == 550.0 and invoice["balance"] == 550.0
    inv3 = await _inv(client, admin_h, product_id, location_id)
    assert inv3["qty_on_hand"] == inv2["qty_on_hand"]  # invoice never moves stock

    # Split payment -> receipt, invoice paid
    r = await client.post("/api/v1/sales/payments", headers=admin_h, json={
        "invoice_id": invoice["id"],
        "payments": [{"method": "cash", "amount": 300}, {"method": "card", "amount": 250}],
    })
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["amount_paid"] == 550.0 and receipt["balance"] == 0.0
    assert len(receipt["methods"]) == 2
    r = await client.get(f"/api/v1/sales/invoices/{invoice['id']}", headers=admin_h)
    assert r.json()["status"] == "paid" and r.json()["balance"] == 0.0


async def test_overpayment_rejected(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    customer_id = await _customer(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=2)

    r = await client.post("/api/v1/sales/orders", headers=admin_h, json={
        "customer_id": customer_id, "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": 1, "unit_price": 100}],
    })
    so_id = r.json()["id"]
    await client.post(f"/api/v1/sales/orders/{so_id}/confirm", headers=admin_h)
    delivery = (await client.post(f"/api/v1/sales/orders/{so_id}/deliver", headers=admin_h, json={})).json()
    invoice = (await client.post("/api/v1/sales/invoices", headers=admin_h,
                                 json={"delivery_note_id": delivery["id"]})).json()
    # grand_total 100; pay 150 -> rejected
    r = await client.post("/api/v1/sales/payments", headers=admin_h, json={
        "invoice_id": invoice["id"], "payments": [{"method": "cash", "amount": 150}]})
    assert r.status_code == 400, r.text
    assert "exceeds" in r.text.lower()


# ------------------------------ POS fast-sale ------------------------------ #
async def test_pos_checkout_deducts_and_receipts(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=3)
    inv0 = await _inv(client, admin_h, product_id, location_id)

    r = await client.post("/api/v1/sales/pos/checkout", headers=admin_h, json={
        "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": 2, "unit_price": 80}],
        "payments": [{"method": "cash", "amount": 160}],
    })
    assert r.status_code == 201, r.text
    result = r.json()
    assert result["invoice"]["status"] == "paid"
    assert result["receipt"]["amount_paid"] == 160.0 and result["receipt"]["balance"] == 0.0
    assert result["delivery_note"]["status"] == "delivered"
    inv1 = await _inv(client, admin_h, product_id, location_id)
    assert inv1["qty_on_hand"] == inv0["qty_on_hand"] - 2  # immediate deduction


# ------------------------------- permissions ------------------------------- #
async def test_cashier_cannot_create_quotation(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    customer_id = await _customer(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=1)

    # A cashier has pos.use + sales.payment but not sales.quote.
    role_id = await _role_id(client, admin_h, "Cashier")
    email = f"cashier-{uuid.uuid4().hex[:8]}@demo.com"
    pw = "CashierPass123"
    r = await client.post("/api/v1/users", headers=admin_h, json={
        "email": email, "full_name": "POS Cashier", "password": pw, "role_ids": [role_id]})
    assert r.status_code == 201, r.text
    cashier_h = await _headers(client, email, pw)

    r = await client.post("/api/v1/sales/quotations", headers=cashier_h, json={
        "customer_id": customer_id,
        "lines": [{"product_id": product_id, "qty": 1, "unit_price": 10}]})
    assert r.status_code == 403, r.text
    # but POS is allowed
    r = await client.post("/api/v1/sales/pos/checkout", headers=cashier_h, json={
        "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": 1, "unit_price": 10}],
        "payments": [{"method": "cash", "amount": 10}]})
    assert r.status_code == 201, r.text
