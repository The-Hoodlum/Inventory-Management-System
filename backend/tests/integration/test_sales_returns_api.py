"""Integration tests for customer returns + credit notes over HTTP:

sell -> invoice -> return goods (restock at a chosen location) -> credit note ->
approve -> apply (offsets the invoice without editing it). Plus a permission boundary.

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
    r = await client.post("/api/v1/customers", headers=admin_h, json={"name": "Returns Co"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _find_stocked(client, admin_h, min_qty=10.0) -> tuple[str, str]:
    r = await client.get("/api/v1/inventory", headers=admin_h, params={"page_size": 200})
    for row in r.json()["items"]:
        if float(row["qty_available"]) >= min_qty:
            return row["product_id"], row["warehouse_id"]
    pytest.skip("no inventory with enough available stock")


async def _on_hand(client, h, product_id, wh_id) -> float:
    r = await client.get("/api/v1/inventory", headers=h,
                         params={"product_id": product_id, "warehouse_id": wh_id})
    items = r.json()["items"]
    return float(items[0]["qty_on_hand"]) if items else 0.0


async def _invoiced_order(client, admin_h, customer_id, product_id, location_id, qty=5):
    r = await client.post("/api/v1/sales/orders", headers=admin_h, json={
        "customer_id": customer_id, "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": qty, "unit_price": 100}]})
    so_id = r.json()["id"]
    await client.post(f"/api/v1/sales/orders/{so_id}/confirm", headers=admin_h)
    d = await client.post(f"/api/v1/sales/orders/{so_id}/deliver", headers=admin_h, json={})
    inv = await client.post("/api/v1/sales/invoices", headers=admin_h,
                            json={"delivery_note_id": d.json()["id"]})
    return inv.json()


async def test_return_restocks_and_credit_note_offsets_invoice(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    customer_id = await _customer(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=10)

    invoice = await _invoiced_order(client, admin_h, customer_id, product_id, location_id, qty=5)
    assert invoice["grand_total"] == 500.0 and invoice["balance"] == 500.0
    on_hand_after_sale = await _on_hand(client, admin_h, product_id, location_id)

    # Return 2 of the 5 units back into the same location.
    r = await client.post("/api/v1/sales/returns", headers=admin_h, json={
        "invoice_id": invoice["id"], "location_id": location_id, "reason": "damaged",
        "lines": [{"product_id": product_id, "qty": 2}]})
    assert r.status_code == 201, r.text
    ret = r.json()
    assert ret["status"] == "received" and ret["reason"] == "damaged"
    # Stock restocked (+2) via the inventory ledger.
    assert await _on_hand(client, admin_h, product_id, location_id) == on_hand_after_sale + 2

    # Credit note from the return, priced from the invoice (2 × 100 = 200).
    r = await client.post("/api/v1/sales/credit-notes", headers=admin_h, json={"return_id": ret["id"]})
    assert r.status_code == 201, r.text
    cn = r.json()
    assert cn["status"] == "draft" and cn["grand_total"] == 200.0

    # Approve then apply -> offsets the invoice (never edits its lines).
    r = await client.post(f"/api/v1/sales/credit-notes/{cn['id']}/approve", headers=admin_h)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = await client.post(f"/api/v1/sales/credit-notes/{cn['id']}/apply", headers=admin_h)
    assert r.status_code == 200 and r.json()["status"] == "applied"

    r = await client.get(f"/api/v1/sales/invoices/{invoice['id']}", headers=admin_h)
    after = r.json()
    assert after["credit_total"] == 200.0
    assert after["balance"] == 300.0                 # 500 - 0 paid - 200 credit
    assert after["status"] == "partially_paid"
    assert len(after["lines"]) == 1 and after["lines"][0]["qty"] == 5  # invoice lines untouched


async def test_returns_require_permission(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    customer_id = await _customer(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=2)
    invoice = await _invoiced_order(client, admin_h, customer_id, product_id, location_id, qty=1)

    # A Salesperson can quote/order but not process returns.
    r = await client.get("/api/v1/users/roles", headers=admin_h)
    role_id = next(x["id"] for x in r.json() if x["name"] == "Salesperson")
    email = f"sp-{uuid.uuid4().hex[:8]}@demo.com"
    pw = "SalesPass123"
    await client.post("/api/v1/users", headers=admin_h, json={
        "email": email, "full_name": "Sales Person", "password": pw, "role_ids": [role_id]})
    sp_h = await _headers(client, email, pw)

    r = await client.post("/api/v1/sales/returns", headers=sp_h, json={
        "invoice_id": invoice["id"], "location_id": location_id, "reason": "other",
        "lines": [{"product_id": product_id, "qty": 1}]})
    assert r.status_code == 403, r.text
