"""End-to-end integration test: the full warehouse-manager workflow.

Drives the real FastAPI app against a live PostgreSQL database via httpx's ASGI
transport, using freshly-created data (not seed discovery) to exercise the
operations a warehouse manager performs end to end:
  create supplier -> create warehouses -> create product -> receive stock ->
  transfer between warehouses -> create PO -> submit/approve/send -> receive PO
  -> verify on-hand + movement ledger -> run reorder.

Requires a provisioned database (schema + RBAC + demo seed) and:
    DATABASE_URL           async DSN, e.g.
                           postgresql+asyncpg://app_user:app_pw@localhost:5432/inventory
    JWT_SECRET_KEY         any non-empty secret
    DEMO_ADMIN_EMAIL       (optional) default: admin@demo.com
    DEMO_ADMIN_PASSWORD    (optional) default: ChangeMe123!

Skipped entirely when DATABASE_URL is absent, so the default unit run stays
hermetic. Uses unique SKUs/codes/names so it is safe to run repeatedly.
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


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def client():
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _admin_headers(client) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _onhand(client, headers, product_id, warehouse_id) -> float:
    r = await client.get(
        "/api/v1/inventory",
        headers=headers,
        params={"product_id": product_id, "warehouse_id": warehouse_id},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    return float(items[0]["qty_on_hand"]) if items else 0.0


async def test_warehouse_manager_workflow(client):
    h = await _admin_headers(client)

    # 1) Create a supplier.
    r = await client.post(
        "/api/v1/suppliers",
        headers=h,
        json={"name": _uniq("Supplier"), "currency": "USD", "default_lead_time_days": 7},
    )
    assert r.status_code == 201, r.text
    supplier_id = r.json()["id"]

    # 2) Create two warehouses (so we can transfer between them).
    r = await client.post("/api/v1/warehouses", headers=h, json={"code": _uniq("WH"), "name": "WF Main"})
    assert r.status_code == 201, r.text
    wh_a = r.json()["id"]
    r = await client.post("/api/v1/warehouses", headers=h, json={"code": _uniq("WH"), "name": "WF Second"})
    assert r.status_code == 201, r.text
    wh_b = r.json()["id"]

    # 3) Create a product.
    r = await client.post(
        "/api/v1/products",
        headers=h,
        json={
            "sku": _uniq("SKU"),
            "name": "WF Widget",
            "cost_price": "10.00",
            "selling_price": "18.00",
            "units_per_carton": 12,
            "moq": 24,
            "primary_supplier_id": supplier_id,
        },
    )
    assert r.status_code == 201, r.text
    product_id = r.json()["id"]

    # 4) Receive 50 units ad-hoc into warehouse A.
    r = await client.post(
        "/api/v1/inventory/receive",
        headers=h,
        json={
            "warehouse_id": wh_a,
            "reference_type": "manual",
            "lines": [{"product_id": product_id, "quantity": "50", "unit_cost": "10.00"}],
        },
    )
    assert r.status_code == 201, r.text
    assert await _onhand(client, h, product_id, wh_a) == 50.0

    # 5) Transfer 20 units A -> B.
    r = await client.post(
        "/api/v1/inventory/transfer",
        headers=h,
        json={
            "product_id": product_id,
            "from_warehouse_id": wh_a,
            "to_warehouse_id": wh_b,
            "quantity": "20",
        },
    )
    assert r.status_code == 200, r.text
    assert await _onhand(client, h, product_id, wh_a) == 30.0
    assert await _onhand(client, h, product_id, wh_b) == 20.0

    # 6) Transferring more than available is rejected by the business rule.
    r = await client.post(
        "/api/v1/inventory/transfer",
        headers=h,
        json={
            "product_id": product_id,
            "from_warehouse_id": wh_a,
            "to_warehouse_id": wh_b,
            "quantity": "999",
        },
    )
    assert r.status_code in (400, 409, 422), r.text

    # 7) Create a PO for the product and run it through to fully received.
    r = await client.post(
        "/api/v1/purchase-orders",
        headers=h,
        json={
            "supplier_id": supplier_id,
            "warehouse_id": wh_a,
            "lines": [{"product_id": product_id, "ordered_qty": "30", "unit_cost": "10.00"}],
        },
    )
    assert r.status_code == 201, r.text
    po = r.json()
    po_id = po["id"]
    line_id = po["lines"][0]["id"]
    for action in ("submit", "approve", "send"):
        r = await client.post(f"/api/v1/purchase-orders/{po_id}/{action}", headers=h, json={})
        assert r.status_code == 200, (action, r.text)
    r = await client.post(
        f"/api/v1/purchase-orders/{po_id}/receipts",
        headers=h,
        json={"lines": [{"line_id": line_id, "quantity": "30"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["purchase_order"]["status"] == "received"

    # On-hand in A: 50 received - 20 transferred out + 30 PO receipt = 60.
    assert await _onhand(client, h, product_id, wh_a) == 60.0

    # 8) The movement ledger reflects receipt + both transfer legs.
    r = await client.get(
        "/api/v1/inventory/movements",
        headers=h,
        params={"product_id": product_id, "page_size": 50},
    )
    assert r.status_code == 200, r.text
    movement_types = {m["movement_type"] for m in r.json()["items"]}
    assert {"receipt", "transfer_out", "transfer_in"} <= movement_types, movement_types

    # 9) A reorder run executes successfully.
    r = await client.post("/api/v1/reorder/run", headers=h, json={})
    assert r.status_code == 200, r.text
