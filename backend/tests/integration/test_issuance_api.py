"""Integration tests for internal issuance / handover (out-and-back loan).

Verifies the STOCK RULE: a bike goes out-on-loan (not sellable, NOT deducted) and returns
to available on a clean return; a damaged return routes the bike to on_hold with a reason;
a fungible item issuance reduces AVAILABLE but not on_hand and releases on return; a
consumable line deducts at handover and is not expected back; an unreturned shortfall is
converted to a documented loss. Requires a live DB + seed.
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


async def _warehouse(client, h) -> tuple[str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    wh = (await client.post("/api/v1/warehouses", headers=h, json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": br, "is_active": True})).json()["id"]
    return wh, br


async def _product(client, h) -> str:
    return (await client.post("/api/v1/products", headers=h, json={"sku": _rand("SKU"), "name": "Loan item"})).json()["id"]


async def _receive(client, h, wh, product, qty):
    r = await client.post("/api/v1/inventory/receive", headers=h, json={
        "warehouse_id": wh, "lines": [{"product_id": product, "quantity": qty}], "reference_type": "manual"})
    assert r.status_code == 201, r.text


async def _inv(client, h, wh, product) -> dict:
    r = await client.get("/api/v1/inventory", headers=h, params={"warehouse_id": wh, "product_id": product})
    it = r.json()["items"][0]
    return {"on_hand": float(it["qty_on_hand"]), "available": float(it["qty_available"])}


async def _unit(client, h, wh, branch) -> dict:
    model = (await client.post("/api/v1/motorcycles/models", headers=h, json={"brand": _rand("Br"), "name": _rand("Md")})).json()["id"]
    return (await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "model_id": model, "warehouse_id": wh, "branch_id": branch})).json()


async def _enable_sales(client, h) -> None:
    r = await client.get("/api/v1/tenant/settings", headers=h)
    flags = dict(r.json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags})


async def _customer(client, h) -> str:
    await _enable_sales(client, h)  # the customers endpoint is gated on the sales feature
    return (await client.post("/api/v1/customers", headers=h, json={"name": "Buyer"})).json()["id"]


async def _get_unit(client, h, uid) -> dict:
    return (await client.get(f"/api/v1/motorcycles/units/{uid}", headers=h)).json()


# ------------------------------------------------------------------------- #
async def test_bike_out_on_loan_not_sellable_then_returns_available(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, br = await _warehouse(client, h)
    unit = await _unit(client, h, wh, br)
    customer = await _customer(client, h)

    iss = (await client.post("/api/v1/issuances", headers=h, json={
        "warehouse_id": wh, "requestor": "Marketing", "purpose": "Expo",
        "bike_lines": [{"unit_id": unit["id"], "odometer_out": 1200, "fuel_out": "Half"}]})).json()
    line_id = iss["lines"][0]["id"]
    await client.post(f"/api/v1/issuances/{iss['id']}/issue", headers=h)

    # Out on loan: NOT deducted (still assembled), and NOT sellable / reservable.
    u = await _get_unit(client, h, unit["id"])
    assert u["status"] == "assembled"  # unchanged, not on_hold, not a 6th status
    r = await client.post(f"/api/v1/motorcycles/units/{unit['id']}/reserve", headers=h, json={"customer_id": customer})
    assert r.status_code == 400 and "loan" in r.text.lower()

    # Clean return (Good) -> the unit is available for sale again.
    r = await client.post(f"/api/v1/issuances/{iss['id']}/return", headers=h, json={
        "bike_lines": [{"line_id": line_id, "condition": "good", "odometer_in": 1300}]})
    assert r.status_code == 200 and r.json()["status"] == "returned"
    r = await client.post(f"/api/v1/motorcycles/units/{unit['id']}/reserve", headers=h, json={"customer_id": customer})
    assert r.status_code == 200, r.text  # sellable again


async def test_damaged_return_routes_bike_to_on_hold(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, br = await _warehouse(client, h)
    unit = await _unit(client, h, wh, br)

    iss = (await client.post("/api/v1/issuances", headers=h, json={
        "warehouse_id": wh, "purpose": "Test ride", "bike_lines": [{"unit_id": unit["id"]}]})).json()
    line_id = iss["lines"][0]["id"]
    await client.post(f"/api/v1/issuances/{iss['id']}/issue", headers=h)

    r = await client.post(f"/api/v1/issuances/{iss['id']}/return", headers=h, json={
        "bike_lines": [{"line_id": line_id, "condition": "needs_attention", "return_note": "Scratched tank"}]})
    assert r.status_code == 200
    u = await _get_unit(client, h, unit["id"])
    assert u["status"] == "on_hold" and u["hold_reason"] == "Scratched tank"


async def test_fungible_loan_holds_available_and_releases_on_return(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, _br = await _warehouse(client, h)
    product = await _product(client, h)
    await _receive(client, h, wh, product, 10)
    inv0 = await _inv(client, h, wh, product)

    iss = (await client.post("/api/v1/issuances", headers=h, json={
        "warehouse_id": wh, "purpose": "Demo kit",
        "part_lines": [{"product_id": product, "qty": 4, "returnable": True}]})).json()
    line_id = iss["lines"][0]["id"]
    await client.post(f"/api/v1/issuances/{iss['id']}/issue", headers=h)

    # Held: AVAILABLE down 4, on_hand UNCHANGED.
    held = await _inv(client, h, wh, product)
    assert held["available"] == inv0["available"] - 4 and held["on_hand"] == inv0["on_hand"]

    # Full return -> released back to available; on_hand still unchanged.
    r = await client.post(f"/api/v1/issuances/{iss['id']}/return", headers=h, json={
        "part_lines": [{"line_id": line_id, "returned_qty": 4}]})
    assert r.status_code == 200 and r.json()["status"] == "returned"
    back = await _inv(client, h, wh, product)
    assert back["available"] == inv0["available"] and back["on_hand"] == inv0["on_hand"]


async def test_consumable_deducts_at_handover_and_shortfall_is_a_loss(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, _br = await _warehouse(client, h)
    consumable = await _product(client, h)
    returnable = await _product(client, h)
    await _receive(client, h, wh, consumable, 10)
    await _receive(client, h, wh, returnable, 10)
    c0, r0 = await _inv(client, h, wh, consumable), await _inv(client, h, wh, returnable)

    iss = (await client.post("/api/v1/issuances", headers=h, json={
        "warehouse_id": wh, "purpose": "Giveaways + demo",
        "part_lines": [
            {"product_id": consumable, "qty": 2, "consumable": True},
            {"product_id": returnable, "qty": 5, "returnable": True},
        ]})).json()
    ret_line = next(x["id"] for x in iss["lines"] if x["product_id"] == returnable)
    await client.post(f"/api/v1/issuances/{iss['id']}/issue", headers=h)

    # Consumable: a real deduction at handover (on_hand down 2). Not expected back.
    c1 = await _inv(client, h, wh, consumable)
    assert c1["on_hand"] == c0["on_hand"] - 2

    # Returnable, only 3 of 5 come back -> 2 unreturned become a documented loss:
    # on_hand down 2, available restored for the 3 that returned.
    r = await client.post(f"/api/v1/issuances/{iss['id']}/return", headers=h, json={
        "part_lines": [{"line_id": ret_line, "returned_qty": 3}]})
    assert r.status_code == 200
    ln = next(x for x in r.json()["lines"] if x["id"] == ret_line)
    assert ln["returned_qty"] == 3.0 and ln["missing_qty"] == 2.0
    r1 = await _inv(client, h, wh, returnable)
    assert r1["on_hand"] == r0["on_hand"] - 2       # the 2 lost are deducted
    assert r1["available"] == r0["available"] - 2   # hold fully released; net loss of 2
