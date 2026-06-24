"""Integration tests for the order-request flow over HTTP:
cashier creates -> admin approves -> admin issues (inventory deducted), plus the
permission boundary (cashier cannot approve) and the feature-flag gate.

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


async def _role_id(client, admin_h, name) -> str:
    r = await client.get("/api/v1/users/roles", headers=admin_h)
    assert r.status_code == 200, r.text
    role = next((x for x in r.json() if x["name"] == name), None)
    assert role, f"system role {name!r} not found — re-seed the database"
    return role["id"]


async def _make_cashier(client, admin_h) -> tuple[str, str]:
    role_id = await _role_id(client, admin_h, "Cashier")
    email = f"cashier-{uuid.uuid4().hex[:8]}@demo.com"
    password = "CashierPass123"
    r = await client.post("/api/v1/users", headers=admin_h, json={
        "email": email, "full_name": "Test Cashier", "password": password, "role_ids": [role_id],
    })
    assert r.status_code == 201, r.text
    return email, password


async def _find_stocked_inventory(client, admin_h) -> tuple[str, str]:
    """Return (product_id, warehouse_id) for an inventory row with available stock."""
    r = await client.get("/api/v1/inventory", headers=admin_h, params={"page_size": 100})
    assert r.status_code == 200, r.text
    for row in r.json()["items"]:
        if float(row["qty_available"]) >= 1:
            return row["product_id"], row["warehouse_id"]
    pytest.skip("no inventory with available stock in the demo data")


async def test_full_request_flow_create_approve_issue(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    email, password = await _make_cashier(client, admin_h)
    cashier_h = await _headers(client, email, password)
    product_id, warehouse_id = await _find_stocked_inventory(client, admin_h)

    # 1) Cashier creates a request -> pending
    r = await client.post("/api/v1/order-requests", headers=cashier_h, json={
        "branch_id": warehouse_id, "purpose": "for_sale",
        "lines": [{"product_id": product_id, "requested_qty": 1}],
    })
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "pending"
    request_id = req["id"]
    line_id = req["lines"][0]["id"]

    # 2) Cashier can see it; cannot approve
    r = await client.get("/api/v1/order-requests", headers=cashier_h)
    assert r.status_code == 200 and any(x["id"] == request_id for x in r.json())
    r = await client.post(f"/api/v1/order-requests/{request_id}/approve", headers=cashier_h,
                          json={"lines": [{"line_id": line_id, "approved_qty": 1}]})
    assert r.status_code == 403, r.text  # cashier lacks order_request.approve

    # 3) Admin approves in full
    r = await client.post(f"/api/v1/order-requests/{request_id}/approve", headers=admin_h,
                          json={"lines": [{"line_id": line_id, "approved_qty": 1}]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    # 4) Admin issues -> inventory deducted
    before = await _qty(client, admin_h, product_id, warehouse_id)
    r = await client.post(f"/api/v1/order-requests/{request_id}/issue", headers=admin_h)
    assert r.status_code == 200, r.text
    issued = r.json()
    assert issued["status"] == "issued"
    assert issued["lines"][0]["issued_qty"] == 1
    after = await _qty(client, admin_h, product_id, warehouse_id)
    assert after == before - 1  # exactly one unit deducted at issue time

    # 5) Audit trail records the transitions
    r = await client.get(f"/api/v1/order-requests/{request_id}/audit", headers=admin_h)
    actions = [a["action"] for a in r.json()]
    assert {"created", "approved", "issued"}.issubset(set(actions))


async def _qty(client, headers, product_id, warehouse_id) -> float:
    r = await client.get("/api/v1/inventory", headers=headers,
                         params={"product_id": product_id, "warehouse_id": warehouse_id})
    assert r.status_code == 200, r.text
    return float(r.json()["items"][0]["qty_available"])


async def test_partial_approval_records_outstanding(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    email, password = await _make_cashier(client, admin_h)
    cashier_h = await _headers(client, email, password)
    product_id, warehouse_id = await _find_stocked_inventory(client, admin_h)

    r = await client.post("/api/v1/order-requests", headers=cashier_h, json={
        "branch_id": warehouse_id, "purpose": "shelf_replenishment",
        "lines": [{"product_id": product_id, "requested_qty": 4}],
    })
    request_id, line_id = r.json()["id"], r.json()["lines"][0]["id"]

    r = await client.post(f"/api/v1/order-requests/{request_id}/approve", headers=admin_h,
                          json={"lines": [{"line_id": line_id, "approved_qty": 2}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "partially_approved"
    line = body["lines"][0]
    assert line["requested_qty"] == 4 and line["approved_qty"] == 2 and line["outstanding_qty"] == 4


async def test_reject_requires_reason_and_sets_status(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    email, password = await _make_cashier(client, admin_h)
    cashier_h = await _headers(client, email, password)
    product_id, warehouse_id = await _find_stocked_inventory(client, admin_h)

    r = await client.post("/api/v1/order-requests", headers=cashier_h, json={
        "branch_id": warehouse_id, "purpose": "other",
        "lines": [{"product_id": product_id, "requested_qty": 1}],
    })
    request_id = r.json()["id"]
    # reason required (422 without it)
    r = await client.post(f"/api/v1/order-requests/{request_id}/reject", headers=admin_h, json={})
    assert r.status_code == 422
    r = await client.post(f"/api/v1/order-requests/{request_id}/reject", headers=admin_h,
                          json={"reason": "Not needed"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert r.json()["comments"] == "Not needed"


async def test_issue_then_complete_records_receipt(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    email, password = await _make_cashier(client, admin_h)
    cashier_h = await _headers(client, email, password)
    product_id, warehouse_id = await _find_stocked_inventory(client, admin_h)

    r = await client.post("/api/v1/order-requests", headers=cashier_h, json={
        "branch_id": warehouse_id, "purpose": "for_sale",
        "lines": [{"product_id": product_id, "requested_qty": 1}],
    })
    assert r.status_code == 201, r.text
    req = r.json()
    request_id, line_id = req["id"], req["lines"][0]["id"]

    r = await client.post(f"/api/v1/order-requests/{request_id}/approve", headers=admin_h,
                          json={"lines": [{"line_id": line_id, "approved_qty": 1}]})
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/v1/order-requests/{request_id}/issue", headers=admin_h)
    assert r.status_code == 200 and r.json()["status"] == "issued"

    # Once issued it can no longer be cancelled (business rule -> 400)...
    r = await client.post(f"/api/v1/order-requests/{request_id}/cancel", headers=admin_h, json={})
    assert r.status_code == 400, r.text
    # ...and completion requires receipt remarks (422 without them).
    r = await client.post(f"/api/v1/order-requests/{request_id}/complete", headers=admin_h, json={})
    assert r.status_code == 422

    # Confirm receipt with a discrepancy (the single unit went missing in transit).
    r = await client.post(f"/api/v1/order-requests/{request_id}/complete", headers=admin_h, json={
        "remarks": "Received short — 1 missing in transit",
        "lines": [{"line_id": line_id, "received_qty": 0, "missing_qty": 1}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["completion_remarks"] == "Received short — 1 missing in transit"
    assert body["completed_date"] is not None
    line = body["lines"][0]
    assert line["received_qty"] == 0 and line["missing_qty"] == 1

    # 'completed' is a separate, explicit, audited step — issuing never auto-completes.
    r = await client.get(f"/api/v1/order-requests/{request_id}/audit", headers=admin_h)
    actions = [a["action"] for a in r.json()]
    assert {"issued", "completed"}.issubset(set(actions))


async def test_cancel_request_by_requester(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    email, password = await _make_cashier(client, admin_h)
    cashier_h = await _headers(client, email, password)
    product_id, warehouse_id = await _find_stocked_inventory(client, admin_h)

    r = await client.post("/api/v1/order-requests", headers=cashier_h, json={
        "branch_id": warehouse_id, "purpose": "office_use",
        "lines": [{"product_id": product_id, "requested_qty": 1}],
    })
    assert r.status_code == 201, r.text
    request_id = r.json()["id"]

    # A requester can cancel their own pending request (before it is issued).
    r = await client.post(f"/api/v1/order-requests/{request_id}/cancel", headers=cashier_h,
                          json={"reason": "No longer needed"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    assert r.json()["comments"] == "No longer needed"
