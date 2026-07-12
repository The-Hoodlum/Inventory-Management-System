"""Integration tests for the Spare Parts sales log (GET /api/v1/sales/parts-sales).

A POS parts sale must (a) deduct on-hand exactly once through the InventoryService
ledger and (b) surface in the parts-sales log with the right product / qty / price /
branch / customer. Motorcycle unit sales must NOT appear here (they carry no invoice
line). Requires a live database with the RBAC + demo seed; skipped otherwise.
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


async def _headers(client, email, password) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _enable_sales(client, admin_h) -> None:
    r = await client.get("/api/v1/tenant/settings", headers=admin_h)
    flags = dict(r.json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    # This flow test asserts pre-VAT totals; neutralise VAT (VAT covered elsewhere).
    r = await client.put("/api/v1/tenant/settings", headers=admin_h,
                         json={"feature_flags": flags, "vat_rate": 0})
    assert r.status_code == 200, r.text


async def _find_stocked(client, admin_h, min_qty=3.0) -> tuple[str, str]:
    r = await client.get("/api/v1/inventory", headers=admin_h, params={"page_size": 200})
    assert r.status_code == 200, r.text
    for row in r.json()["items"]:
        if float(row["qty_available"]) >= min_qty:
            return row["product_id"], row["warehouse_id"]
    pytest.skip("no inventory with enough available stock in the demo data")


async def _onhand(client, h, product_id, wh_id) -> float:
    r = await client.get("/api/v1/inventory", headers=h,
                         params={"product_id": product_id, "warehouse_id": wh_id})
    assert r.status_code == 200, r.text
    return float(r.json()["items"][0]["qty_on_hand"])


async def test_parts_sale_appears_in_log_and_deducts_once(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=3)
    onhand0 = await _onhand(client, admin_h, product_id, location_id)

    # Sell 2 units through the existing POS path (single InventoryService write path).
    r = await client.post("/api/v1/sales/pos/checkout", headers=admin_h, json={
        "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": 2, "unit_price": 75}],
        "payments": [{"method": "cash", "amount": 150}],
    })
    assert r.status_code == 201, r.text
    invoice_number = r.json()["invoice"]["invoice_number"]

    # Stock deducted exactly once.
    assert await _onhand(client, admin_h, product_id, location_id) == onhand0 - 2

    # The sale shows in the parts-sales log with the right line detail.
    r = await client.get("/api/v1/sales/parts-sales", headers=admin_h,
                         params={"product_id": product_id, "limit": 50})
    assert r.status_code == 200, r.text
    rows = r.json()
    mine = [s for s in rows if s["invoice_number"] == invoice_number]
    assert len(mine) == 1, f"expected exactly one parts-sales line for {invoice_number}"
    line = mine[0]
    assert line["product_id"] == product_id
    assert line["qty"] == 2.0
    assert line["unit_price"] == 75.0
    assert line["line_total"] == 150.0
    assert line["customer_name"]  # walk-in customer resolved
    # Every row in the parts log is a fungible product line (never a serialized unit).
    assert all(s["product_id"] for s in rows)


async def test_parts_sales_requires_sales_read(client):
    """The parts-sales log is gated on sales.read (403 without a token)."""
    r = await client.get("/api/v1/sales/parts-sales")
    assert r.status_code in (401, 403), r.text
