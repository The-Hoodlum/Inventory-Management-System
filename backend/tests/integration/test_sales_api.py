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
    # These flow/mechanics tests assert pre-VAT totals; neutralise VAT here (VAT math is
    # covered by tests/unit/test_sales_vat.py and test_vat_* integration tests).
    r = await client.put("/api/v1/tenant/settings", headers=admin_h,
                         json={"feature_flags": flags, "vat_rate": 0})
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


async def _ledger(client, h, product_id, wh_id) -> tuple[float, int]:
    """(signed sum of all stock movements, total count) for a product+location."""
    r = await client.get("/api/v1/inventory/movements", headers=h,
                         params={"product_id": product_id, "warehouse_id": wh_id, "page_size": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    return sum(float(m["quantity"]) for m in body["items"]), body["total"]


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

    # Quotation. VAT is neutralised in this flow test (see _enable_sales); VAT itself is
    # covered by test_vat_applied_and_frozen_on_parts_sale. Per-line tax_pct is ignored —
    # VAT is a tenant setting applied by product treatment.
    r = await client.post("/api/v1/sales/quotations", headers=admin_h, json={
        "customer_id": customer_id,
        "lines": [{"product_id": product_id, "qty": 5, "unit_price": 100}],
    })
    assert r.status_code == 201, r.text
    quote = r.json()
    assert quote["grand_total"] == 500.0  # 5*100, VAT neutralised

    # Convert -> the part lines become a sales order (bike lines, if any, are sold).
    r = await client.post(f"/api/v1/sales/quotations/{quote['id']}/convert", headers=admin_h,
                          json={"location_id": location_id})
    assert r.status_code == 201, r.text
    conv = r.json()
    assert conv["quotation_id"] == quote["id"] and conv["bike_sales"] == []
    so = conv["sales_order"]
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
    assert invoice["grand_total"] == 500.0 and invoice["balance"] == 500.0
    inv3 = await _inv(client, admin_h, product_id, location_id)
    assert inv3["qty_on_hand"] == inv2["qty_on_hand"]  # invoice never moves stock

    # Split payment -> receipt, invoice paid
    r = await client.post("/api/v1/sales/payments", headers=admin_h, json={
        "invoice_id": invoice["id"],
        "payments": [{"method": "cash", "amount": 300}, {"method": "card", "amount": 200}],
    })
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["amount_paid"] == 500.0 and receipt["balance"] == 0.0
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


# ---- single stock-write path: sales moves stock ONLY through the ledger ---- #
async def test_sales_uses_single_inventory_ledger_path(client):
    """A sale and a return change on-hand by EXACTLY the net of the stock-movement
    ledger they write — proving sales no longer has its own write path and that the
    reserve/issue/receipt entries reconcile (Δon_hand == Δledger). The delivery 'issue'
    has the same shape a manual InventoryService.issue() would write."""
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    customer_id = await _customer(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=10)

    onhand0 = (await _inv(client, admin_h, product_id, location_id))["qty_on_hand"]
    sum0, total0 = await _ledger(client, admin_h, product_id, location_id)
    if total0 > 180:  # keep the whole ledger within one page so the sum is exact
        pytest.skip("too many pre-existing movements to bound the ledger sum on one page")

    # Order 4 -> confirm (reserve) -> deliver (issue, consumes the hold).
    so_id = (await client.post("/api/v1/sales/orders", headers=admin_h, json={
        "customer_id": customer_id, "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": 4, "unit_price": 100}],
    })).json()["id"]
    await client.post(f"/api/v1/sales/orders/{so_id}/confirm", headers=admin_h)
    delivery = (await client.post(f"/api/v1/sales/orders/{so_id}/deliver",
                                  headers=admin_h, json={})).json()
    assert delivery["status"] == "delivered"

    onhand1 = (await _inv(client, admin_h, product_id, location_id))["qty_on_hand"]
    sum1, _ = await _ledger(client, admin_h, product_id, location_id)
    assert onhand1 == onhand0 - 4
    # reserve(-4) + unreserve(+4) net 0, issue(-4) => ledger net == on-hand change.
    assert (sum1 - sum0) == (onhand1 - onhand0) == -4

    # The delivery wrote a single 'issue' movement of -4, just like a manual issue.
    r = await client.get("/api/v1/inventory/movements", headers=admin_h,
                         params={"product_id": product_id, "warehouse_id": location_id, "page_size": 10})
    issues = [m for m in r.json()["items"]
              if m["movement_type"] == "issue" and float(m["quantity"]) == -4]
    assert any(m["reference_type"] == "sales_delivery" for m in issues)

    # Invoice, then return all 4 -> restock 'receipt' through the same inventory path.
    invoice = (await client.post("/api/v1/sales/invoices", headers=admin_h,
                                 json={"delivery_note_id": delivery["id"]})).json()
    r = await client.post("/api/v1/sales/returns", headers=admin_h, json={
        "invoice_id": invoice["id"], "location_id": location_id, "reason": "damaged",
        "lines": [{"product_id": product_id, "qty": 4}]})
    assert r.status_code == 201, r.text

    onhand2 = (await _inv(client, admin_h, product_id, location_id))["qty_on_hand"]
    sum2, _ = await _ledger(client, admin_h, product_id, location_id)
    assert onhand2 == onhand0  # full deliver + return cycle nets to zero
    assert (sum2 - sum0) == (onhand2 - onhand0) == 0


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


# ------------------------------ VAT (spare parts) -------------------------- #
async def test_vat_applied_and_frozen_on_parts_sale(client):
    """A spare part is VAT-EXCLUSIVE: 16% is added on top and net/vat/gross are frozen on
    the invoice + line. Moving the tenant rate afterwards does NOT re-price the document."""
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)  # sets vat_rate 0 ...
    # ... now turn VAT on at 16% for this test.
    r = await client.put("/api/v1/tenant/settings", headers=admin_h, json={"vat_rate": "0.16"})
    assert r.status_code == 200, r.text
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=3)

    # POS sale: 2 x 100 -> net 200, VAT 32, gross 232 (customer pays 232).
    r = await client.post("/api/v1/sales/pos/checkout", headers=admin_h, json={
        "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": 2, "unit_price": 100}],
        "payments": [{"method": "cash", "amount": 232}],
    })
    assert r.status_code == 201, r.text
    inv = r.json()["invoice"]
    assert inv["net_total"] == 200.0
    assert inv["tax_total"] == 32.0
    assert inv["grand_total"] == 232.0        # payable (net + VAT)
    assert inv["vat_rate"] == 0.16
    assert inv["status"] == "paid"
    line = inv["lines"][0]
    assert line["vat_treatment"] == "exclusive"
    assert line["net_amount"] == 200.0 and line["vat_amount"] == 32.0
    assert line["line_total"] == 232.0

    # Move the tenant VAT rate — the issued invoice must not budge.
    await client.put("/api/v1/tenant/settings", headers=admin_h, json={"vat_rate": "0.2"})
    again = (await client.get(f"/api/v1/sales/invoices/{inv['id']}", headers=admin_h)).json()
    assert again["tax_total"] == 32.0 and again["grand_total"] == 232.0 and again["vat_rate"] == 0.16

    # Hand VAT back to 0 for other tests.
    await client.put("/api/v1/tenant/settings", headers=admin_h, json={"vat_rate": 0})
