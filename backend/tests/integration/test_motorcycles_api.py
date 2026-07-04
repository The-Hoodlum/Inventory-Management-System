"""Integration tests for the Motorcycle module over HTTP:

reference catalog CRUD (models/variants/colours), the per-unit lifecycle with a
real sales-document linkage, a serialized branch transfer, global search by
chassis/engine/registration, and a permission boundary.

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


def _rand(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _enable_sales(client, admin_h) -> None:
    r = await client.get("/api/v1/tenant/settings", headers=admin_h)
    flags = dict(r.json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    r = await client.put("/api/v1/tenant/settings", headers=admin_h, json={"feature_flags": flags})
    assert r.status_code == 200, r.text


async def _brand_id(client, admin_h) -> str:
    """Brands are get-or-created by name when creating a product; reuse that."""
    r = await client.post("/api/v1/products", headers=admin_h, json={
        "sku": _rand("SKU"), "name": "Chassis carrier product", "brand": _rand("MotoBrand")})
    assert r.status_code == 201, r.text
    return r.json()["brand_id"]


async def _model(client, admin_h, brand_id=None) -> dict:
    brand_id = brand_id or await _brand_id(client, admin_h)
    r = await client.post("/api/v1/motorcycles/models", headers=admin_h, json={
        "brand_id": brand_id, "name": _rand("Model"), "engine_cc": 150, "default_selling_price": 2000})
    assert r.status_code == 201, r.text
    return r.json()


async def _colour(client, admin_h) -> dict:
    r = await client.post("/api/v1/motorcycles/colours", headers=admin_h, json={
        "name": _rand("Colour"), "hex_code": "#FF0000"})
    assert r.status_code == 201, r.text
    return r.json()


async def _unit(client, admin_h, *, model_id, chassis=None, **extra) -> dict:
    body = {"chassis_number": chassis or _rand("CH"), "engine_number": _rand("EN"),
            "model_id": model_id, **extra}
    r = await client.post("/api/v1/motorcycles/units", headers=admin_h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------------- #
# Dashboard metrics
# ------------------------------------------------------------------------- #
async def test_metrics_rolls_up_by_lifecycle_bucket(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    before = (await client.get("/api/v1/motorcycles/metrics", headers=admin_h)).json()

    model = await _model(client, admin_h)
    u1 = await _unit(client, admin_h, model_id=model["id"])   # assembled -> in_stock
    await _unit(client, admin_h, model_id=model["id"], assembly_required=True)  # unassembled -> in_stock
    # Put one on hold — still physically in stock (not sold / reserved).
    await client.post(f"/api/v1/motorcycles/units/{u1['id']}/transition", headers=admin_h,
                      json={"to_status": "on_hold", "hold_reason": "Awaiting parts"})

    after = (await client.get("/api/v1/motorcycles/metrics", headers=admin_h)).json()
    assert after["total"] == before["total"] + 2
    assert after["in_stock"] == before["in_stock"] + 2  # assembled + unassembled + on_hold all count
    assert set(after["by_status"]).issubset({"unassembled", "assembled", "reserved", "on_hold", "sold"})


# ------------------------------------------------------------------------- #
# Layer 1: reference catalog CRUD
# ------------------------------------------------------------------------- #
async def test_reference_catalog_crud(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    brand_id = await _brand_id(client, admin_h)

    model = await _model(client, admin_h, brand_id)
    assert model["brand_name"] and model["is_active"] is True

    # Duplicate model name for the same brand is rejected.
    r = await client.post("/api/v1/motorcycles/models", headers=admin_h, json={
        "brand_id": brand_id, "name": model["name"]})
    assert r.status_code == 409, r.text

    # Update the model.
    r = await client.patch(f"/api/v1/motorcycles/models/{model['id']}", headers=admin_h,
                           json={"engine_cc": 200, "is_active": False})
    assert r.status_code == 200 and r.json()["engine_cc"] == 200 and r.json()["is_active"] is False

    # Variant belongs to the model; duplicate name rejected; filter by model.
    r = await client.post("/api/v1/motorcycles/variants", headers=admin_h, json={
        "model_id": model["id"], "name": "Deluxe"})
    assert r.status_code == 201, r.text
    variant = r.json()
    assert variant["model_name"] == model["name"]
    r = await client.post("/api/v1/motorcycles/variants", headers=admin_h, json={
        "model_id": model["id"], "name": "Deluxe"})
    assert r.status_code == 409, r.text
    r = await client.get("/api/v1/motorcycles/variants", headers=admin_h,
                         params={"model_id": model["id"]})
    assert r.status_code == 200 and any(v["id"] == variant["id"] for v in r.json()["items"])

    # Colour is a flat tenant list; duplicate name rejected.
    colour = await _colour(client, admin_h)
    r = await client.post("/api/v1/motorcycles/colours", headers=admin_h, json={"name": colour["name"]})
    assert r.status_code == 409, r.text

    # A model can also be created by brand NAME (get-or-create; reuses the brands table).
    r = await client.post("/api/v1/motorcycles/models", headers=admin_h, json={
        "brand": _rand("NamedBrand"), "name": _rand("Model")})
    assert r.status_code == 201, r.text
    assert r.json()["brand_name"]


# ------------------------------------------------------------------------- #
# Layer 2: full lifecycle + sales linkage
# ------------------------------------------------------------------------- #
async def _invoice_for_sale(client, admin_h) -> dict:
    """Run the real sales flow to produce a genuine invoice to link a unit to."""
    await _enable_sales(client, admin_h)
    r = await client.post("/api/v1/customers", headers=admin_h, json={"name": "Moto Buyer"})
    assert r.status_code == 201, r.text
    customer_id = r.json()["id"]
    # find a stocked product + location
    r = await client.get("/api/v1/inventory", headers=admin_h, params={"page_size": 200})
    product_id = location_id = None
    for row in r.json()["items"]:
        if float(row["qty_available"]) >= 1:
            product_id, location_id = row["product_id"], row["warehouse_id"]
            break
    if product_id is None:
        pytest.skip("no stocked product to build an invoice")
    r = await client.post("/api/v1/sales/orders", headers=admin_h, json={
        "customer_id": customer_id, "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": 1, "unit_price": 100}]})
    so_id = r.json()["id"]
    await client.post(f"/api/v1/sales/orders/{so_id}/confirm", headers=admin_h)
    d = await client.post(f"/api/v1/sales/orders/{so_id}/deliver", headers=admin_h, json={})
    inv = await client.post("/api/v1/sales/invoices", headers=admin_h,
                            json={"delivery_note_id": d.json()["id"]})
    assert inv.status_code == 201, inv.text
    return {"invoice": inv.json(), "customer_id": customer_id, "so_id": so_id}


async def test_full_unit_lifecycle_with_sales_linkage(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    model = await _model(client, admin_h)
    colour = await _colour(client, admin_h)
    unit = await _unit(client, admin_h, model_id=model["id"], colour_id=colour["id"],
                       selling_price=2500, assembly_required=True)
    # Assembly-required units start 'unassembled'; inspection/registration default off.
    assert unit["status"] == "unassembled" and unit["inspected"] is False and unit["registered"] is False
    uid = unit["id"]

    # Assemble it. Now sellable.
    r = await client.post(f"/api/v1/motorcycles/units/{uid}/transition", headers=admin_h,
                          json={"to_status": "assembled"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "assembled"
    assert set(body["allowed_next"]) == {"reserved", "on_hold", "sold"}

    # Illegal transition is rejected (assembled cannot go back to unassembled).
    r = await client.post(f"/api/v1/motorcycles/units/{uid}/transition", headers=admin_h,
                          json={"to_status": "unassembled"})
    assert r.status_code == 400, r.text
    # Cannot jump to reserved/sold via the generic transition (must use the actions).
    r = await client.post(f"/api/v1/motorcycles/units/{uid}/transition", headers=admin_h,
                          json={"to_status": "sold"})
    assert r.status_code == 400, r.text

    # Inspection is an INDEPENDENT fact — set it without touching the sale status.
    r = await client.patch(f"/api/v1/motorcycles/units/{uid}", headers=admin_h,
                           json={"inspected": True})
    assert r.status_code == 200 and r.json()["inspected"] is True and r.json()["status"] == "assembled"

    sale = await _invoice_for_sale(client, admin_h)
    customer_id, invoice = sale["customer_id"], sale["invoice"]

    # Reserve this specific chassis for the customer (serialized hold), then let it fall
    # through (reserved -> assembled releases the hold + clears the customer).
    r = await client.post(f"/api/v1/motorcycles/units/{uid}/reserve", headers=admin_h,
                          json={"customer_id": customer_id, "sales_order_id": sale["so_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "reserved" and r.json()["customer_id"] == customer_id
    assert r.json()["reserved_so_number"]  # linked to the sales order
    r = await client.post(f"/api/v1/motorcycles/units/{uid}/transition", headers=admin_h,
                          json={"to_status": "assembled"})
    assert r.status_code == 200
    assert r.json()["reserved_ref"] is None and r.json()["customer_id"] is None  # released

    # Sell against the real invoice: unit links to the sales document.
    r = await client.post(f"/api/v1/motorcycles/units/{uid}/sell", headers=admin_h,
                          json={"invoice_id": invoice["id"], "price_charged": 2450})
    assert r.status_code == 200, r.text
    sold = r.json()
    assert sold["status"] == "sold"
    assert sold["sold_ref"] == invoice["id"]
    assert sold["sold_invoice_number"] == invoice["invoice_number"]
    assert sold["price_charged"] == 2450 and sold["customer_id"] == invoice["customer_id"]

    # 'sold' is terminal — no further sale-status transitions.
    assert sold["allowed_next"] == []

    # Registration is INDEPENDENT — a sold unit can still be registered afterwards.
    r = await client.patch(f"/api/v1/motorcycles/units/{uid}", headers=admin_h,
                           json={"registered": True, "registration_number": "ABZ 1234"})
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["registered"] is True and reg["registration_number"] == "ABZ 1234"
    assert reg["status"] == "sold"  # unchanged by registration

    # The immutable event ledger recorded every step (created + each transition/action).
    types = [e["event_type"] for e in reg["events"]]
    assert types[0] == "created"
    assert "reserved" in types and "sold" in types


async def test_reserved_requires_a_customer(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    model = await _model(client, admin_h)
    unit = await _unit(client, admin_h, model_id=model["id"])  # assembled
    # No customer_id at all -> schema rejects it (422).
    r = await client.post(f"/api/v1/motorcycles/units/{unit['id']}/reserve", headers=admin_h, json={})
    assert r.status_code == 422, r.text
    # A non-existent customer -> 404.
    r = await client.post(f"/api/v1/motorcycles/units/{unit['id']}/reserve", headers=admin_h,
                          json={"customer_id": str(uuid.uuid4())})
    assert r.status_code == 404, r.text


async def test_on_hold_requires_reason_no_customer_and_cannot_sell(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    model = await _model(client, admin_h)
    unit = await _unit(client, admin_h, model_id=model["id"])  # assembled
    uid = unit["id"]

    # on_hold without a reason is rejected.
    r = await client.post(f"/api/v1/motorcycles/units/{uid}/transition", headers=admin_h,
                          json={"to_status": "on_hold"})
    assert r.status_code == 400, r.text

    # With a reason it holds — carries the reason, no customer, and no reservation.
    r = await client.post(f"/api/v1/motorcycles/units/{uid}/transition", headers=admin_h,
                          json={"to_status": "on_hold", "hold_reason": "Cracked mudguard"})
    assert r.status_code == 200, r.text
    held = r.json()
    assert held["status"] == "on_hold" and held["hold_reason"] == "Cracked mudguard"
    assert held["customer_id"] is None
    # A held unit cannot be sold (must clear the hold first).
    sale = await _invoice_for_sale(client, admin_h)
    r = await client.post(f"/api/v1/motorcycles/units/{uid}/sell", headers=admin_h,
                          json={"invoice_id": sale["invoice"]["id"]})
    assert r.status_code == 400, r.text
    # Clear the hold back to assembled; the reason is kept for history.
    r = await client.post(f"/api/v1/motorcycles/units/{uid}/transition", headers=admin_h,
                          json={"to_status": "assembled"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "assembled" and r.json()["hold_reason"] == "Cracked mudguard"


# ------------------------------------------------------------------------- #
# Serialized branch transfer
# ------------------------------------------------------------------------- #
async def _two_branches(client, admin_h) -> tuple[str, str]:
    r = await client.get("/api/v1/branches", headers=admin_h, params={"page_size": 50})
    branches = [b["id"] for b in r.json()["items"]]
    while len(branches) < 2:
        r = await client.post("/api/v1/branches", headers=admin_h,
                              json={"code": _rand("BR"), "name": _rand("Branch")})
        assert r.status_code == 201, r.text
        branches.append(r.json()["id"])
    return branches[0], branches[1]


async def test_serialized_branch_transfer(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    a, b = await _two_branches(client, admin_h)
    model = await _model(client, admin_h)
    unit = await _unit(client, admin_h, model_id=model["id"], branch_id=a)
    assert unit["branch_id"] == a

    r = await client.post(f"/api/v1/motorcycles/units/{unit['id']}/transfer", headers=admin_h,
                          json={"to_branch_id": b, "note": "rebalancing"})
    assert r.status_code == 200, r.text
    moved = r.json()
    assert moved["branch_id"] == b
    transfer_events = [e for e in moved["events"] if e["event_type"] == "transfer"]
    assert len(transfer_events) == 1
    ev = transfer_events[0]
    assert ev["from_branch_id"] == a and ev["to_branch_id"] == b  # both sides visible
    assert ev["from_branch_name"] and ev["to_branch_name"]


# ------------------------------------------------------------------------- #
# Global search
# ------------------------------------------------------------------------- #
async def test_search_finds_unit_by_chassis_engine_and_registration(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    model = await _model(client, admin_h)
    chassis = _rand("CHZ")
    engine = _rand("ENZ")
    unit = await _unit(client, admin_h, model_id=model["id"], chassis=chassis, engine_number=engine)
    reg = _rand("REG")
    r = await client.patch(f"/api/v1/motorcycles/units/{unit['id']}", headers=admin_h,
                           json={"registration_number": reg})
    assert r.status_code == 200, r.text

    for term in (chassis, engine, reg):
        r = await client.get("/api/v1/search", headers=admin_h, params={"q": term})
        assert r.status_code == 200, r.text
        groups = {g["entity"]: g for g in r.json()["groups"]}
        assert "motorcycle_unit" in groups, f"no motorcycle group for '{term}'"
        hits = groups["motorcycle_unit"]["hits"]
        assert any(h["id"] == unit["id"] for h in hits), f"unit not found by '{term}'"


# ------------------------------------------------------------------------- #
# Permission boundary
# ------------------------------------------------------------------------- #
async def test_permission_boundary(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    model = await _model(client, admin_h)

    # A Viewer has motorcycle.read but neither manage nor config.
    r = await client.get("/api/v1/users/roles", headers=admin_h)
    role_id = next(x["id"] for x in r.json() if x["name"] == "Viewer")
    email, pw = f"viewer-{uuid.uuid4().hex[:8]}@demo.com", "ViewerPass123"
    r = await client.post("/api/v1/users", headers=admin_h, json={
        "email": email, "full_name": "Read Only", "password": pw, "role_ids": [role_id]})
    assert r.status_code == 201, r.text
    viewer_h = await _headers(client, email, pw)

    # Read is allowed.
    r = await client.get("/api/v1/motorcycles/units", headers=viewer_h)
    assert r.status_code == 200, r.text
    # Creating a unit (manage) is forbidden.
    r = await client.post("/api/v1/motorcycles/units", headers=viewer_h, json={
        "chassis_number": _rand("CH"), "model_id": model["id"]})
    assert r.status_code == 403, r.text
    # Managing the catalog (config) is forbidden.
    r = await client.post("/api/v1/motorcycles/colours", headers=viewer_h, json={"name": _rand("C")})
    assert r.status_code == 403, r.text
