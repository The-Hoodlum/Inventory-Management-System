"""Integration: low-stock + pending-approval notification producers.

- issuing stock that takes an item across its reorder point fires ONE low-stock alert to
  the reorder managers (not the person issuing), and does not re-fire on the next issue;
- raising a requisition for approval notifies the approvers;
- submitting a purchase order for approval notifies the approvers.

A second Admin user receives the branch/permission-targeted events (the actor is excluded).
Requires a live DB; skipped otherwise.
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


async def _second_admin(client, admin_h) -> dict[str, str]:
    roles = (await client.get("/api/v1/users/roles", headers=admin_h)).json()
    role_id = next(r["id"] for r in roles if r["name"] == "Admin")
    email, pw = _rand("mgr") + "@demo.com", "MgrPass123"
    r = await client.post("/api/v1/users", headers=admin_h, json={
        "email": email, "full_name": "Approver", "password": pw, "role_ids": [role_id]})
    assert r.status_code == 201, r.text
    return await _headers(client, email, pw)


async def _warehouse(client, h) -> tuple[str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    wh = (await client.post("/api/v1/warehouses", headers=h, json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": br, "is_active": True})).json()["id"]
    return wh, br


async def _product(client, h, *, reorder_point=None) -> str:
    body = {"sku": _rand("SKU"), "name": _rand("Part")}
    if reorder_point is not None:
        body["reorder_point"] = reorder_point
    return (await client.post("/api/v1/products", headers=h, json=body)).json()["id"]


async def _notifs(client, h, event_type: str) -> list[dict]:
    items = (await client.get("/api/v1/notifications", headers=h, params={"limit": 100})).json()["items"]
    return [i for i in items if i["event_type"] == event_type]


# ------------------------------------------------------------------------- #
async def test_low_stock_crossing_notifies_reorder_managers_once(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    b_h = await _second_admin(client, admin_h)
    wh, _br = await _warehouse(client, admin_h)
    product = await _product(client, admin_h, reorder_point=5)
    await client.post("/api/v1/inventory/receive", headers=admin_h, json={
        "warehouse_id": wh, "lines": [{"product_id": product, "quantity": 10}], "reference_type": "manual"})

    # Issue 6 -> available 4, crossing below the reorder point (5).
    r = await client.post("/api/v1/inventory/issue", headers=admin_h, json={
        "warehouse_id": wh, "lines": [{"product_id": product, "quantity": 6}], "reason": "test"})
    assert r.status_code == 200, r.text

    mine = [n for n in await _notifs(client, b_h, "inventory.low_stock") if str(product) in (n.get("entity_id") or "")]
    assert len(mine) == 1                                    # reorder managers told, once
    assert await _notifs(client, admin_h, "inventory.low_stock") == []   # actor excluded

    # Already below -> a further issue does NOT re-fire.
    before = len(await _notifs(client, b_h, "inventory.low_stock"))
    await client.post("/api/v1/inventory/issue", headers=admin_h, json={
        "warehouse_id": wh, "lines": [{"product_id": product, "quantity": 1}], "reason": "test"})
    assert len(await _notifs(client, b_h, "inventory.low_stock")) == before


async def test_order_request_pending_notifies_approvers(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    b_h = await _second_admin(client, admin_h)
    wh, _br = await _warehouse(client, admin_h)     # a "location" for the requisition is a warehouse
    product = await _product(client, admin_h)

    r = await client.post("/api/v1/order-requests", headers=admin_h, json={
        "source_location_id": wh, "purpose": "shelf_replenishment", "submit": True,
        "lines": [{"product_id": product, "requested_qty": 5}]})
    assert r.status_code == 201, r.text
    assert len(await _notifs(client, b_h, "order_request.pending")) >= 1


async def test_po_submit_notifies_approvers(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    b_h = await _second_admin(client, admin_h)
    wh, _br = await _warehouse(client, admin_h)
    product = await _product(client, admin_h)
    supplier = (await client.post("/api/v1/suppliers", headers=admin_h, json={"name": _rand("Sup")})).json()["id"]

    po = (await client.post("/api/v1/purchase-orders", headers=admin_h, json={
        "supplier_id": supplier, "warehouse_id": wh,
        "lines": [{"product_id": product, "ordered_qty": 5, "unit_cost": 100}]})).json()
    r = await client.post(f"/api/v1/purchase-orders/{po['id']}/submit", headers=admin_h, json={})
    assert r.status_code == 200, r.text
    assert len(await _notifs(client, b_h, "po.pending_approval")) >= 1
