"""Integration tests for the Motorcycle (serialized-unit) lifecycle module over HTTP:

create -> legal transitions (illegal rejected) -> reserve (links a sales order) ->
sell (links an invoice) -> deliver, plus a serialized branch transfer, the per-unit
event ledger, global-search by chassis/engine/registration, and a permission boundary.

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


async def _enable_sales(client, h) -> None:
    r = await client.get("/api/v1/tenant/settings", headers=h)
    flags = dict(r.json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags})


async def _branches(client, h) -> list[dict]:
    r = await client.get("/api/v1/branches", headers=h, params={"page_size": 50})
    assert r.status_code == 200, r.text
    return r.json()["items"]


async def _customer(client, h, name="Moto Buyer") -> str:
    return (await client.post("/api/v1/customers", headers=h, json={"name": name})).json()["id"]


async def _find_stocked(client, h, min_qty=2):
    r = await client.get("/api/v1/inventory", headers=h, params={"page_size": 200})
    for row in r.json()["items"]:
        if float(row["qty_available"]) >= min_qty:
            return row["product_id"], row["warehouse_id"]
    pytest.skip("no inventory with enough available stock")


async def _invoice_for(client, h, customer_id, product_id, location_id):
    so = (await client.post("/api/v1/sales/orders", headers=h, json={
        "customer_id": customer_id, "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": 1, "unit_price": 100}]})).json()
    await client.post(f"/api/v1/sales/orders/{so['id']}/confirm", headers=h)
    d = (await client.post(f"/api/v1/sales/orders/{so['id']}/deliver", headers=h, json={})).json()
    inv = (await client.post("/api/v1/sales/invoices", headers=h,
                             json={"delivery_note_id": d["id"]})).json()
    return so["id"], inv["id"]


def _chassis() -> str:
    return "CHS-" + uuid.uuid4().hex[:10].upper()


async def test_full_unit_lifecycle_with_sales_linkage(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, h)
    branches = await _branches(client, h)
    b0 = branches[0]["id"]
    customer_id = await _customer(client, h)
    product_id, location_id = await _find_stocked(client, h, min_qty=1)
    chassis = _chassis()

    # Create the unit
    r = await client.post("/api/v1/motorcycles", headers=h, json={
        "chassis_number": chassis, "engine_number": "ENG-123", "model": "Apache 160",
        "colour": "Red", "year": 2026, "branch_id": b0, "selling_price": 2500})
    assert r.status_code == 201, r.text
    unit = r.json()
    uid = unit["id"]
    assert unit["status"] == "received" and unit["chassis_number"] == chassis and unit["version"] == 0

    # Legal transition received -> inspected
    r = await client.post(f"/api/v1/motorcycles/{uid}/transition", headers=h,
                          json={"to_status": "inspected"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "inspected"

    # Illegal transition inspected -> delivered is rejected
    r = await client.post(f"/api/v1/motorcycles/{uid}/transition", headers=h,
                          json={"to_status": "delivered"})
    assert r.status_code == 400, r.text

    # transition endpoint refuses to set reserved/sold (must use the dedicated actions)
    r = await client.post(f"/api/v1/motorcycles/{uid}/transition", headers=h,
                          json={"to_status": "sold"})
    assert r.status_code == 400 and "reserve" in r.text.lower()

    # Reserve — links to a real sales order
    so_id, invoice_id = await _invoice_for(client, h, customer_id, product_id, location_id)
    r = await client.post(f"/api/v1/motorcycles/{uid}/reserve", headers=h,
                          json={"customer_id": customer_id, "sales_order_id": so_id})
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["status"] == "reserved" and u["reserved"] is True
    assert u["reserved_sales_order_id"] == so_id and u["so_number"]
    assert u["customer_id"] == customer_id and u["customer_name"]

    # Sell — links to the existing invoice (no parallel sales path)
    r = await client.post(f"/api/v1/motorcycles/{uid}/sell", headers=h,
                          json={"invoice_id": invoice_id, "price_charged": 2450})
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["status"] == "sold" and u["sold"] is True
    assert u["invoice_id"] == invoice_id and u["invoice_number"]
    assert u["price_charged"] == 2450.0

    # sold -> delivered is legal
    r = await client.post(f"/api/v1/motorcycles/{uid}/transition", headers=h,
                          json={"to_status": "delivered"})
    assert r.status_code == 200 and r.json()["status"] == "delivered"

    # The per-unit event ledger captured every step in order
    events = (await client.get(f"/api/v1/motorcycles/{uid}", headers=h)).json()["events"]
    kinds = [e["event_type"] for e in events]
    assert kinds[0] == "created"
    assert "reserved" in kinds and "sold" in kinds and "status_change" in kinds


async def test_serialized_branch_transfer(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    branches = await _branches(client, h)
    if len(branches) < 2:
        pytest.skip("need two branches for a transfer")
    b0, b1 = branches[0]["id"], branches[1]["id"]
    uid = (await client.post("/api/v1/motorcycles", headers=h, json={
        "chassis_number": _chassis(), "model": "NTorq", "branch_id": b0})).json()["id"]

    r = await client.post(f"/api/v1/motorcycles/{uid}/transfer", headers=h,
                          json={"to_branch_id": b1, "note": "rebalance"})
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["branch_id"] == b1
    ev = next(e for e in u["events"] if e["event_type"] == "transfer")
    assert ev["from_branch_id"] == b0 and ev["to_branch_id"] == b1  # both sides visible


async def test_search_finds_unit_by_chassis_and_registration(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    chassis = _chassis()
    uid = (await client.post("/api/v1/motorcycles", headers=h, json={
        "chassis_number": chassis, "model": "Raider"})).json()["id"]

    r = await client.get("/api/v1/search", headers=h, params={"q": chassis})
    groups = {g["entity"]: g for g in r.json()["groups"]}
    assert "motorcycle" in groups, r.text
    assert any(hit["id"] == uid for hit in groups["motorcycle"]["hits"])

    # Set a registration number, then find by it
    rego = "REG" + uuid.uuid4().hex[:6].upper()
    await client.patch(f"/api/v1/motorcycles/{uid}", headers=h, json={"registration_number": rego})
    r = await client.get("/api/v1/search", headers=h, params={"q": rego})
    groups = {g["entity"]: g for g in r.json()["groups"]}
    assert "motorcycle" in groups and any(hit["id"] == uid for hit in groups["motorcycle"]["hits"])


async def test_permission_boundary(client):
    """A Viewer has motorcycle.read but not motorcycle.manage: can list, cannot create."""
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.get("/api/v1/users/roles", headers=h)
    role_id = next((x["id"] for x in r.json() if x["name"] == "Viewer"), None)
    if not role_id:
        pytest.skip("Viewer role not seeded")
    email = f"viewer-{uuid.uuid4().hex[:8]}@demo.com"
    pw = "ViewerPass123"
    r = await client.post("/api/v1/users", headers=h, json={
        "email": email, "full_name": "Read Only", "password": pw, "role_ids": [role_id]})
    assert r.status_code == 201, r.text
    vh = await _headers(client, email, pw)

    assert (await client.get("/api/v1/motorcycles", headers=vh)).status_code == 200
    r = await client.post("/api/v1/motorcycles", headers=vh, json={"chassis_number": _chassis()})
    assert r.status_code == 403, r.text
