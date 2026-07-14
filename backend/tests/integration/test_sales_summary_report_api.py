"""Integration test for the daily/monthly sales-summary report:

a POS spare-part sale shows up in today's report as a line with the right VAT (parts are
VAT-exclusive), the payment appears in the by-method breakdown, and the totals include it.
Assertions are containment-based (other tests may sell on the same day too).

Requires a live database (DATABASE_URL) with the RBAC + demo seed; skipped otherwise.
"""
from __future__ import annotations

import datetime as dt
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


async def _headers(client) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _enable_sales_vat(client, h) -> None:
    flags = dict((await client.get("/api/v1/tenant/settings", headers=h)).json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    r = await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags, "vat_rate": "0.16"})
    assert r.status_code == 200, r.text


async def _find_stocked(client, h, min_qty=3.0):
    r = await client.get("/api/v1/inventory", headers=h, params={"page_size": 200})
    for row in r.json()["items"]:
        if float(row["qty_available"]) >= min_qty:
            return row["product_id"], row["warehouse_id"]
    pytest.skip("no inventory with enough available stock in the demo data")


async def test_sales_summary_includes_pos_sale_with_vat_and_payment(client):
    h = await _headers(client)
    await _enable_sales_vat(client, h)
    product_id, location_id = await _find_stocked(client, h, min_qty=3)

    # A POS spare-part sale: 2 x 100 -> net 200, +16% VAT 32, gross 232, paid cash.
    r = await client.post("/api/v1/sales/pos/checkout", headers=h, json={
        "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": 2, "unit_price": 100}],
        "payments": [{"method": "cash", "amount": 232}]})
    assert r.status_code == 201, r.text
    inv_no = r.json()["invoice"]["invoice_number"]

    # Today's report contains it, with the VAT broken out.
    today = dt.date.today().isoformat()
    r = await client.get("/api/v1/reports/sales-summary", headers=h, params={"period": "daily", "date": today})
    assert r.status_code == 200, r.text
    rep = r.json()

    line = next((ln for ln in rep["lines"] if ln["invoice_number"] == inv_no and ln["kind"] == "part"), None)
    assert line is not None, "the POS sale is missing from the report"
    assert line["gross"] == 232.0 and line["net"] == 200.0 and line["vat"] == 32.0

    # The payment shows up in the by-method breakdown, and the totals include the sale.
    methods = {p["method"]: p["amount"] for p in rep["payments"]}
    assert methods.get("cash", 0) >= 232.0
    assert rep["gross_total"] >= 232.0 and rep["collected_total"] >= 232.0

    # Reset VAT for other tests.
    await client.put("/api/v1/tenant/settings", headers=h, json={"vat_rate": 0})
