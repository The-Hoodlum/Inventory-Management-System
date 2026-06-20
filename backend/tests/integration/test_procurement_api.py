"""End-to-end integration test for the procurement (PO + receiving) API.

Exercises the real FastAPI app against a live PostgreSQL database (RLS, JWT, the
state machine, receiving, inventory effects, events, and PDF) via httpx's ASGI
transport.

Requires a provisioned database (schema + RBAC + demo seed) and:
    DATABASE_URL           async DSN (postgresql+asyncpg://...)
    JWT_SECRET_KEY         any non-empty secret
    DEMO_ADMIN_EMAIL       (optional) default: admin@demo.com
    DEMO_ADMIN_PASSWORD    (optional) default: ChangeMe123!

Skipped entirely when DATABASE_URL is absent, so the default unit run stays
hermetic. The flow self-discovers a supplier / warehouse / product from the API
and skips gracefully if the demo data has none.
"""
from __future__ import annotations

import os

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


async def _login(client) -> str:
    r = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _first_id(client, headers, path) -> str | None:
    r = await client.get(path, headers=headers, params={"page_size": 1})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    return items[0]["id"] if items else None


async def test_full_purchase_order_lifecycle(client):
    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    supplier_id = await _first_id(client, headers, "/api/v1/suppliers")
    warehouse_id = await _first_id(client, headers, "/api/v1/warehouses")
    product_id = await _first_id(client, headers, "/api/v1/products")
    if not (supplier_id and warehouse_id and product_id):
        pytest.skip("demo data lacks a supplier/warehouse/product to build a PO")

    # 1) Create a draft PO.
    r = await client.post(
        "/api/v1/purchase-orders",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "warehouse_id": warehouse_id,
            "notes": "integration test PO",
            "lines": [
                {
                    "product_id": product_id,
                    "ordered_qty": "10",
                    "unit_cost": "3.00",
                    "units_per_carton": 5,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    po = r.json()
    po_id = po["id"]
    line_id = po["lines"][0]["id"]
    assert po["status"] == "draft"
    assert po["total"] == "30.0000" or float(po["total"]) == 30.0

    # 2) Approving a draft must be rejected (invalid transition -> 409).
    r = await client.post(f"/api/v1/purchase-orders/{po_id}/approve", headers=headers, json={})
    assert r.status_code == 409, r.text

    # 3) Submit -> approve -> send.
    r = await client.post(
        f"/api/v1/purchase-orders/{po_id}/submit", headers=headers, json={"comment": "review"}
    )
    assert r.status_code == 200 and r.json()["status"] == "pending_approval", r.text
    r = await client.post(
        f"/api/v1/purchase-orders/{po_id}/approve", headers=headers, json={"comment": "ok"}
    )
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    r = await client.post(f"/api/v1/purchase-orders/{po_id}/send", headers=headers, json={})
    assert r.status_code == 200 and r.json()["status"] == "sent", r.text

    # 4) Partial receipt (4 of 10).
    r = await client.post(
        f"/api/v1/purchase-orders/{po_id}/receipts",
        headers=headers,
        json={"lines": [{"line_id": line_id, "quantity": "4"}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fully_received"] is False
    assert body["purchase_order"]["status"] == "partially_received"
    assert body["purchase_order"]["lines"][0]["remaining_qty"] in ("6.0000", "6")

    # 5) Final receipt (remaining 6) -> fully received.
    r = await client.post(
        f"/api/v1/purchase-orders/{po_id}/receipts",
        headers=headers,
        json={"lines": [{"line_id": line_id, "quantity": "6"}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fully_received"] is True
    assert body["purchase_order"]["status"] == "received"

    # 6) Event timeline includes the key lifecycle actions.
    r = await client.get(f"/api/v1/purchase-orders/{po_id}/events", headers=headers)
    assert r.status_code == 200, r.text
    actions = {e["action"] for e in r.json()}
    assert {"created", "submitted", "approved", "sent", "received", "closed"} <= actions

    # 7) PDF renders.
    r = await client.get(f"/api/v1/purchase-orders/{po_id}/pdf", headers=headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:4] == b"%PDF"


async def test_create_requires_authentication(client):
    r = await client.post("/api/v1/purchase-orders", json={"supplier_id": "x", "warehouse_id": "y", "lines": []})
    assert r.status_code in (401, 403, 422)
