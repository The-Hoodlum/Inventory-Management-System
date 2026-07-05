"""Integration tests for branch -> customer/reseller delivery (Type 3, sale | consignment).

Verifies the CORE RULE — the delivery note is PAPER and never mutates stock itself:

  * sale mode: it is proof of a handover the SALE already deducted. Creating/delivering it
    does NOT re-deduct on_hand or available.
  * consignment mode: DELIVER holds parts (available down, on_hand unchanged) and consigns
    bikes (out, not sellable, not deducted); SETTLE turns the sold portion into a real
    deduction / bike sale and RETURN releases the unsold hold.

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


async def _headers(client, email, password) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _rand(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


async def _enable_sales(client, h) -> None:
    r = await client.get("/api/v1/tenant/settings", headers=h)
    flags = dict(r.json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags})


async def _warehouse(client, h) -> tuple[str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    wh = (await client.post("/api/v1/warehouses", headers=h, json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": br, "is_active": True})).json()["id"]
    return wh, br


async def _product(client, h) -> str:
    return (await client.post("/api/v1/products", headers=h, json={"sku": _rand("SKU"), "name": "Reseller item"})).json()["id"]


async def _receive(client, h, wh, product, qty):
    r = await client.post("/api/v1/inventory/receive", headers=h, json={
        "warehouse_id": wh, "lines": [{"product_id": product, "quantity": qty}], "reference_type": "manual"})
    assert r.status_code == 201, r.text


async def _inv(client, h, wh, product) -> dict:
    r = await client.get("/api/v1/inventory", headers=h, params={"warehouse_id": wh, "product_id": product})
    it = r.json()["items"][0]
    return {"on_hand": float(it["qty_on_hand"]), "available": float(it["qty_available"])}


async def _customer(client, h) -> str:
    await _enable_sales(client, h)
    return (await client.post("/api/v1/customers", headers=h, json={"name": "Reseller"})).json()["id"]


async def _unit(client, h, wh, branch) -> dict:
    model = (await client.post("/api/v1/motorcycles/models", headers=h, json={"brand": _rand("Br"), "name": _rand("Md")})).json()["id"]
    return (await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "model_id": model, "warehouse_id": wh, "branch_id": branch})).json()


async def _get_unit(client, h, uid) -> dict:
    return (await client.get(f"/api/v1/motorcycles/units/{uid}", headers=h)).json()


async def _sale_invoice(client, h, wh, product) -> dict:
    """Run the real sales flow to a genuine invoice (this is what deducts stock)."""
    await _enable_sales(client, h)
    customer_id = (await client.post("/api/v1/customers", headers=h, json={"name": "Buyer"})).json()["id"]
    so = (await client.post("/api/v1/sales/orders", headers=h, json={
        "customer_id": customer_id, "location_id": wh,
        "lines": [{"product_id": product, "qty": 3, "unit_price": 100}]})).json()
    so_id = so["id"]
    await client.post(f"/api/v1/sales/orders/{so_id}/confirm", headers=h)
    d = await client.post(f"/api/v1/sales/orders/{so_id}/deliver", headers=h, json={})
    inv = await client.post("/api/v1/sales/invoices", headers=h, json={"delivery_note_id": d.json()["id"]})
    assert inv.status_code == 201, inv.text
    return {"invoice": inv.json(), "customer_id": customer_id}


# ------------------------------------------------------------------------- #
async def test_sale_mode_is_proof_only_no_re_deduction(client):
    """A sale delivery documents the handover; it must NOT deduct stock a second time."""
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, _br = await _warehouse(client, h)
    product = await _product(client, h)
    await _receive(client, h, wh, product, 10)

    sale = await _sale_invoice(client, h, wh, product)   # deducts 3 -> on_hand 7
    after_sale = await _inv(client, h, wh, product)
    assert after_sale["on_hand"] == 7.0

    cd = (await client.post("/api/v1/customer-deliveries", headers=h, json={
        "delivery_mode": "sale", "from_warehouse_id": wh, "invoice_id": sale["invoice"]["id"]})).json()
    assert cd["delivery_mode"] == "sale" and cd["status"] == "draft"
    # the invoice's part line is mirrored as proof
    assert any(ln["line_kind"] == "part" and ln["qty"] == 3.0 for ln in cd["lines"])

    r = await client.post(f"/api/v1/customer-deliveries/{cd['id']}/deliver", headers=h, json={"received_by": "Reseller rep"})
    assert r.status_code == 200 and r.json()["status"] == "delivered"

    # NO re-deduction: on_hand is still 7, available still 7.
    after_deliver = await _inv(client, h, wh, product)
    assert after_deliver == after_sale


async def test_consignment_holds_on_deliver_and_settle_deducts_sold_portion(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, _br = await _warehouse(client, h)
    product = await _product(client, h)
    customer = await _customer(client, h)
    await _receive(client, h, wh, product, 10)
    inv0 = await _inv(client, h, wh, product)

    cd = (await client.post("/api/v1/customer-deliveries", headers=h, json={
        "delivery_mode": "consignment", "from_warehouse_id": wh, "customer_id": customer,
        "part_lines": [{"product_id": product, "qty": 6}]})).json()
    line_id = cd["lines"][0]["id"]

    # DELIVER -> held: available down 6, on_hand unchanged.
    r = await client.post(f"/api/v1/customer-deliveries/{cd['id']}/deliver", headers=h, json={})
    assert r.status_code == 200 and r.json()["status"] == "out_at_reseller"
    held = await _inv(client, h, wh, product)
    assert held["available"] == inv0["available"] - 6 and held["on_hand"] == inv0["on_hand"]

    # SETTLE: 4 sold (real deduction), 2 returned (hold released).
    r = await client.post(f"/api/v1/customer-deliveries/{cd['id']}/settle", headers=h, json={
        "part_lines": [{"line_id": line_id, "settled_qty": 4, "returned_qty": 2}]})
    assert r.status_code == 200 and r.json()["status"] == "settled"
    ln = r.json()["lines"][0]
    assert ln["settled_qty"] == 4.0 and ln["returned_qty"] == 2.0

    final = await _inv(client, h, wh, product)
    assert final["on_hand"] == inv0["on_hand"] - 4      # only the sold 4 deducted
    assert final["available"] == inv0["available"] - 4  # hold fully cleared; net -4


async def test_consigned_bike_not_sellable_then_sold_via_settle(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, br = await _warehouse(client, h)
    customer = await _customer(client, h)
    unit = await _unit(client, h, wh, br)

    cd = (await client.post("/api/v1/customer-deliveries", headers=h, json={
        "delivery_mode": "consignment", "from_warehouse_id": wh, "customer_id": customer,
        "bike_lines": [{"unit_id": unit["id"]}]})).json()
    line_id = cd["lines"][0]["id"]

    await client.post(f"/api/v1/customer-deliveries/{cd['id']}/deliver", headers=h, json={})
    # Out on consignment -> not deducted, not sellable.
    u = await _get_unit(client, h, unit["id"])
    assert u["status"] == "assembled"
    r = await client.post(f"/api/v1/motorcycles/units/{unit['id']}/reserve", headers=h, json={"customer_id": customer})
    assert r.status_code == 400 and "consignment" in r.text.lower()

    # Settle as SOLD against a real invoice -> unit becomes SOLD.
    product = await _product(client, h)
    await _receive(client, h, wh, product, 5)
    sale = await _sale_invoice(client, h, wh, product)
    r = await client.post(f"/api/v1/customer-deliveries/{cd['id']}/settle", headers=h, json={
        "bike_lines": [{"line_id": line_id, "outcome": "sold", "invoice_id": sale["invoice"]["id"]}]})
    assert r.status_code == 200 and r.json()["status"] == "settled"
    u = await _get_unit(client, h, unit["id"])
    assert u["status"] == "sold"


async def test_consigned_bike_returned_unsold_is_sellable_again(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, br = await _warehouse(client, h)
    customer = await _customer(client, h)
    unit = await _unit(client, h, wh, br)

    cd = (await client.post("/api/v1/customer-deliveries", headers=h, json={
        "delivery_mode": "consignment", "from_warehouse_id": wh, "customer_id": customer,
        "bike_lines": [{"unit_id": unit["id"]}]})).json()
    line_id = cd["lines"][0]["id"]
    await client.post(f"/api/v1/customer-deliveries/{cd['id']}/deliver", headers=h, json={})

    r = await client.post(f"/api/v1/customer-deliveries/{cd['id']}/settle", headers=h, json={
        "bike_lines": [{"line_id": line_id, "outcome": "returned"}]})
    assert r.status_code == 200 and r.json()["status"] == "returned"
    # Back off consignment -> reservable/sellable again.
    r = await client.post(f"/api/v1/motorcycles/units/{unit['id']}/reserve", headers=h, json={"customer_id": customer})
    assert r.status_code == 200, r.text
