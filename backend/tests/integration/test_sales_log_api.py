"""Integration tests for the unified sales log (GET /api/v1/reports/sales-log).

Confirms the endpoint wires the shared aggregation against real Postgres: a POS
parts sale shows up in the parts stream for the day, the `type` filter isolates
streams (no double count), and the motorcycle branch of the query executes (the
coalesce/cast over sold units). Requires a live DB with the RBAC + demo seed.
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


async def _headers(client, email, password) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _enable_sales(client, admin_h) -> None:
    r = await client.get("/api/v1/tenant/settings", headers=admin_h)
    flags = dict(r.json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    r = await client.put("/api/v1/tenant/settings", headers=admin_h, json={"feature_flags": flags})
    assert r.status_code == 200, r.text


async def _find_stocked(client, admin_h, min_qty=3.0) -> tuple[str, str]:
    r = await client.get("/api/v1/inventory", headers=admin_h, params={"page_size": 200})
    assert r.status_code == 200, r.text
    for row in r.json()["items"]:
        if float(row["qty_available"]) >= min_qty:
            return row["product_id"], row["warehouse_id"]
    pytest.skip("no inventory with enough available stock in the demo data")


async def _sales_log(client, h, **params):
    r = await client.get("/api/v1/reports/sales-log", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_parts_sale_shows_in_sales_log_and_type_filter_isolates(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    await _enable_sales(client, admin_h)
    product_id, location_id = await _find_stocked(client, admin_h, min_qty=3)
    today = dt.date.today().isoformat()

    base = await _sales_log(client, admin_h, granularity="daily", type="parts",
                            date_from=today, date_to=today)
    base_parts = base["totals"]["parts_revenue"]

    # A parts POS sale of 3 x 60 = 180.
    r = await client.post("/api/v1/sales/pos/checkout", headers=admin_h, json={
        "location_id": location_id,
        "lines": [{"product_id": product_id, "qty": 3, "unit_price": 60}],
        "payments": [{"method": "cash", "amount": 180}],
    })
    assert r.status_code == 201, r.text

    after = await _sales_log(client, admin_h, granularity="daily", type="parts",
                             date_from=today, date_to=today)
    # Parts revenue for today grew by exactly the sale (counted once).
    assert after["totals"]["parts_revenue"] == pytest.approx(base_parts + 180.0)
    # There is a 'parts' component in today's row and no motorcycle contribution.
    todays = [row for row in after["rows"] if row["period_start"] == today]
    assert todays, "expected a row for today"
    kinds = {c["type"] for c in todays[0]["components"]}
    assert "parts" in kinds
    assert after["totals"]["motorcycle_revenue"] == 0.0
    assert after["totals"]["historical_revenue"] == 0.0

    # type=motorcycles executes the sold-unit branch of the query and excludes parts.
    bikes = await _sales_log(client, admin_h, granularity="daily", type="motorcycles",
                             date_from=today, date_to=today)
    assert bikes["totals"]["parts_revenue"] == 0.0

    # type=all revenue == parts + motorcycles for the range (nothing double counted).
    allt = await _sales_log(client, admin_h, granularity="monthly", type="all",
                            date_from=today, date_to=today)
    t = allt["totals"]
    assert t["revenue"] == pytest.approx(
        t["parts_revenue"] + t["motorcycle_revenue"] + t["historical_revenue"]
    )


async def test_sales_log_validates_params(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.get("/api/v1/reports/sales-log", headers=admin_h,
                         params={"granularity": "hourly"})
    assert r.status_code == 400, r.text
    r = await client.get("/api/v1/reports/sales-log", headers=admin_h,
                         params={"type": "bikes"})
    assert r.status_code == 400, r.text
