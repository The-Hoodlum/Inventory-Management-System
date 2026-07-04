"""Integration tests for typed delivery / dispatch notes — Type 1 warehouse->branch.

A delivery note DOCUMENTS a movement; the stock moves through the existing paths
(InventoryService for parts, the serialized registry for bikes). Verifies: source
decrements on dispatch and destination increments on receipt with the ledger
reconciling at both ends; in-transit is neither double-counted nor lost; a bike moves
by chassis and lands at the branch on receipt; a mixed note transfers; a short receipt
is recorded as a discrepancy. Requires a live DB + seed.
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


async def _branch(client, h) -> str:
    r = await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _warehouse(client, h, branch_id) -> str:
    r = await client.post("/api/v1/warehouses", headers=h, json={
        "code": _rand("WH"), "name": _rand("Warehouse"), "branch_id": branch_id, "is_active": True})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _locations(client, h):
    """A source warehouse in branch A and a destination warehouse in branch B."""
    a, b = await _branch(client, h), await _branch(client, h)
    return (await _warehouse(client, h, a), a, await _warehouse(client, h, b), b)


async def _product(client, h) -> str:
    r = await client.post("/api/v1/products", headers=h, json={"sku": _rand("SKU"), "name": "Transfer part"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _receive(client, h, wh_id, product_id, qty) -> None:
    r = await client.post("/api/v1/inventory/receive", headers=h, json={
        "warehouse_id": wh_id, "lines": [{"product_id": product_id, "quantity": qty}],
        "reference_type": "manual"})
    assert r.status_code == 201, r.text


async def _onhand(client, h, wh_id, product_id) -> float:
    r = await client.get("/api/v1/inventory", headers=h,
                         params={"warehouse_id": wh_id, "product_id": product_id})
    items = r.json()["items"]
    return float(items[0]["qty_on_hand"]) if items else 0.0


async def _ledger_sum(client, h, wh_id, product_id) -> float:
    r = await client.get("/api/v1/inventory/movements", headers=h,
                         params={"warehouse_id": wh_id, "product_id": product_id, "page_size": 200})
    return sum(float(m["quantity"]) for m in r.json()["items"])


async def _model(client, h) -> str:
    r = await client.post("/api/v1/motorcycles/models", headers=h,
                          json={"brand": _rand("Brand"), "name": _rand("Model")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _unit(client, h, model_id, wh_id, branch_id) -> dict:
    r = await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "engine_number": _rand("EN"),
        "model_id": model_id, "warehouse_id": wh_id, "branch_id": branch_id})
    assert r.status_code == 201, r.text
    return r.json()


async def _get_unit(client, h, unit_id) -> dict:
    return (await client.get(f"/api/v1/motorcycles/units/{unit_id}", headers=h)).json()


# ------------------------------------------------------------------------- #
async def test_parts_transfer_reconciles_ledger_at_both_ends(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    src, _sa, dst, _db = await _locations(client, h)
    product = await _product(client, h)
    await _receive(client, h, src, product, 10)

    src_oh0, src_led0 = await _onhand(client, h, src, product), await _ledger_sum(client, h, src, product)
    dst_oh0, dst_led0 = await _onhand(client, h, dst, product), await _ledger_sum(client, h, dst, product)

    note = (await client.post("/api/v1/delivery-notes", headers=h, json={
        "from_warehouse_id": src, "to_warehouse_id": dst,
        "part_lines": [{"product_id": product, "qty": 6}]})).json()
    assert note["status"] == "draft"

    # Dispatch: source down; destination not yet counted (in transit).
    r = await client.post(f"/api/v1/delivery-notes/{note['id']}/dispatch", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "in_transit"
    assert await _onhand(client, h, src, product) == src_oh0 - 6
    assert await _onhand(client, h, dst, product) == dst_oh0  # not double-counted at dest yet

    # Receive full: destination up.
    r = await client.post(f"/api/v1/delivery-notes/{note['id']}/receive", headers=h,
                          json={"received_by": "Branch Clerk"})
    assert r.status_code == 200 and r.json()["status"] == "received"
    src_oh1, dst_oh1 = await _onhand(client, h, src, product), await _onhand(client, h, dst, product)
    assert src_oh1 == src_oh0 - 6 and dst_oh1 == dst_oh0 + 6

    # Ledger reconciles at BOTH ends (delta on_hand == delta ledger sum).
    assert (await _ledger_sum(client, h, src, product)) - src_led0 == src_oh1 - src_oh0 == -6
    assert (await _ledger_sum(client, h, dst, product)) - dst_led0 == dst_oh1 - dst_oh0 == 6


async def test_bike_moves_by_chassis_and_lands_at_branch_on_receipt(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    src, sa, dst, db = await _locations(client, h)
    model = await _model(client, h)
    unit = await _unit(client, h, model, src, sa)
    assert unit["branch_id"] == sa

    note = (await client.post("/api/v1/delivery-notes", headers=h, json={
        "from_warehouse_id": src, "to_warehouse_id": dst,
        "bike_lines": [{"unit_id": unit["id"]}]})).json()
    assert note["lines"][0]["chassis_number"] == unit["chassis_number"]
    assert note["lines"][0]["engine_number"] == unit["engine_number"]  # engine pulled from the unit

    # Dispatch: the unit leaves the source (in transit — at no branch).
    await client.post(f"/api/v1/delivery-notes/{note['id']}/dispatch", headers=h)
    assert (await _get_unit(client, h, unit["id"]))["branch_id"] is None

    # Receive: the unit lands at the destination branch.
    r = await client.post(f"/api/v1/delivery-notes/{note['id']}/receive", headers=h, json={})
    assert r.status_code == 200 and r.json()["status"] == "received"
    moved = await _get_unit(client, h, unit["id"])
    assert moved["branch_id"] == db
    # It shows at the destination branch's unit list now.
    r = await client.get("/api/v1/motorcycles/units", headers=h,
                         params={"branch_id": db, "search": unit["chassis_number"]})
    assert any(u["id"] == unit["id"] for u in r.json()["items"])


async def test_mixed_note_transfers_bikes_and_parts(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    src, sa, dst, db = await _locations(client, h)
    product = await _product(client, h)
    await _receive(client, h, src, product, 5)
    model = await _model(client, h)
    unit = await _unit(client, h, model, src, sa)

    note = (await client.post("/api/v1/delivery-notes", headers=h, json={
        "from_warehouse_id": src, "to_warehouse_id": dst,
        "part_lines": [{"product_id": product, "qty": 3}],
        "bike_lines": [{"unit_id": unit["id"]}]})).json()
    await client.post(f"/api/v1/delivery-notes/{note['id']}/dispatch", headers=h)
    r = await client.post(f"/api/v1/delivery-notes/{note['id']}/receive", headers=h, json={})
    assert r.status_code == 200 and r.json()["status"] == "received"
    assert await _onhand(client, h, dst, product) == 3
    assert (await _get_unit(client, h, unit["id"]))["branch_id"] == db


async def test_short_receipt_records_a_discrepancy(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    src, _sa, dst, _db = await _locations(client, h)
    product = await _product(client, h)
    await _receive(client, h, src, product, 8)

    note = (await client.post("/api/v1/delivery-notes", headers=h, json={
        "from_warehouse_id": src, "to_warehouse_id": dst,
        "part_lines": [{"product_id": product, "qty": 5}]})).json()
    line_id = note["lines"][0]["id"]
    await client.post(f"/api/v1/delivery-notes/{note['id']}/dispatch", headers=h)

    # 5 dispatched, only 4 arrive -> partially_received, 1 recorded missing.
    r = await client.post(f"/api/v1/delivery-notes/{note['id']}/receive", headers=h, json={
        "part_lines": [{"line_id": line_id, "received_qty": 4}]})
    assert r.status_code == 200
    got = r.json()
    assert got["status"] == "partially_received"
    ln = got["lines"][0]
    assert ln["received_qty"] == 4.0 and ln["missing_qty"] == 1.0
    # Destination gained only what arrived; the shortfall is documented, not absorbed.
    assert await _onhand(client, h, dst, product) == 4
