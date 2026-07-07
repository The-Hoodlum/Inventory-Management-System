"""Integration tests for the order-request from->to model + per-type role gating (FIX 3 & 4).

- A request stores an explicit SOURCE and DESTINATION location.
- A cashier can raise a restock to their own branch, but NOT a managed transfer, and NOT a
  restock that sends stock to another branch (role gating enforced server-side).
- An authorized manager's transfer approves + issues source->dest via the existing transfer
  path, with ledger entries on both ends.

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


def _rand(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


async def _headers(client, email, password) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _branch_wh(client, h) -> tuple[str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()
    wh = (await client.post("/api/v1/warehouses", headers=h, json={
        "code": _rand("WH"), "name": _rand("WH"), "branch_id": br["id"], "is_active": True})).json()
    return br["id"], wh["id"]


async def _role_id(client, h, name) -> str:
    roles = (await client.get("/api/v1/users/roles", headers=h)).json()
    return next(r["id"] for r in roles if r["name"] == name)


async def _product_with_stock(client, h, wh, qty) -> str:
    pid = (await client.post("/api/v1/products", headers=h, json={"sku": _rand("SKU"), "name": "Part"})).json()["id"]
    await client.post("/api/v1/inventory/receive", headers=h, json={
        "warehouse_id": wh, "reference_type": "manual", "lines": [{"product_id": pid, "quantity": qty}]})
    return pid


async def _onhand(client, h, pid, wh) -> float:
    r = await client.get("/api/v1/inventory", headers=h, params={"warehouse_id": wh, "product_id": pid})
    items = r.json()["items"]
    return float(items[0]["qty_on_hand"]) if items else 0.0


# ------------------------------------------------------------------------- #
async def test_cashier_restock_vs_manager_transfer_and_from_to(client):
    admin = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    a_branch, a_loc = await _branch_wh(client, admin)      # cashier's branch + own location
    _depot_branch, depot = await _branch_wh(client, admin)  # source depot
    _b_branch, b_loc = await _branch_wh(client, admin)      # a different branch's location
    product = await _product_with_stock(client, admin, depot, 20)

    # A cashier scoped to branch A (Cashier role has create, NOT transfer).
    email, pw = _rand("cashier") + "@demo.com", "ScopeTest123!"
    await client.post("/api/v1/users", headers=admin, json={
        "email": email, "full_name": "Cashier", "password": pw,
        "role_ids": [await _role_id(client, admin, "Cashier")], "branch_ids": [a_branch]})
    cashier = await _headers(client, email, pw)

    # (1) restock to their OWN location: source depot -> destination A. Stores explicit ends.
    restock = await client.post("/api/v1/order-requests", headers=cashier, json={
        "source_location_id": depot, "destination_location_id": a_loc,
        "purpose": "shelf_replenishment", "lines": [{"product_id": product, "requested_qty": 4}]})
    assert restock.status_code == 201, restock.text
    body = restock.json()
    assert body["source_location_id"] == depot and body["dest_location_id"] == a_loc

    # (2) a cashier may NOT raise a managed transfer (needs order_request.transfer).
    transfer = await client.post("/api/v1/order-requests", headers=cashier, json={
        "source_location_id": depot, "destination_location_id": a_loc, "purpose": "branch_transfer",
        "comments": "x", "lines": [{"product_id": product, "requested_qty": 1}]})
    assert transfer.status_code == 403, transfer.text

    # (3) a cashier may NOT send a restock to ANOTHER branch (outside their scope).
    outside = await client.post("/api/v1/order-requests", headers=cashier, json={
        "source_location_id": depot, "destination_location_id": b_loc,
        "purpose": "shelf_replenishment", "lines": [{"product_id": product, "requested_qty": 1}]})
    assert outside.status_code == 403, outside.text


async def test_manager_transfer_moves_stock_source_to_dest_with_ledger_both_ends(client):
    admin = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    _sb, source = await _branch_wh(client, admin)
    _db, dest = await _branch_wh(client, admin)
    product = await _product_with_stock(client, admin, source, 10)

    req = (await client.post("/api/v1/order-requests", headers=admin, json={
        "source_location_id": source, "destination_location_id": dest, "purpose": "branch_transfer",
        "comments": "rebalance", "lines": [{"product_id": product, "requested_qty": 6}]})).json()
    rid, line_id = req["id"], req["lines"][0]["id"]
    assert req["source_location_id"] == source and req["dest_location_id"] == dest

    await client.post(f"/api/v1/order-requests/{rid}/approve", headers=admin,
                      json={"lines": [{"line_id": line_id, "approved_qty": 6}]})
    iss = await client.post(f"/api/v1/order-requests/{rid}/issue", headers=admin)
    assert iss.status_code == 200, iss.text

    # Source on-hand deducted by 6 (moved out / in-transit). Existing transfer path — no new
    # stock-writing code.
    assert await _onhand(client, admin, product, source) == 4.0

    # The immutable transfer ledger records both ends (source_location + dest_location).
    ledger = (await client.get(f"/api/v1/order-requests/{rid}/ledger", headers=admin)).json()
    assert ledger, "expected transfer-ledger rows"
    assert any(e["source_location_name"] and e["dest_location_name"] for e in ledger)
