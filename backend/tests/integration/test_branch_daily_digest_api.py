"""Per-branch daily digest: what sold, how it was paid for, and what else happened.

The figures come from the authoritative invoice-based sales aggregation (the same one the
Daily/Monthly Sales Report page uses), so the digest can never disagree with the report.
Crucially it is PER BRANCH — one branch's takings must not appear in another's digest.

Requires a live database (DATABASE_URL); skipped otherwise.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
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
TODAY = dt.date.today()


@pytest_asyncio.fixture
async def client():
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _rand(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _claims(token: str) -> dict:
    p = token.split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))


async def _login(client):
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}, _claims(tok)


async def _digests(tenant_id, day):
    """Build the digests exactly as the scheduler does, RLS-scoped to the real tenant."""
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal
    from app.reports.digest import DailyDigestService
    from app.reports.repository import ReportsRepository
    from app.reports.service import ReportsService

    async with AsyncSessionLocal() as s:
        await s.execute(text("SELECT set_config('app.current_tenant', :t, true)"),
                        {"t": str(tenant_id)})
        svc = DailyDigestService(ReportsService(ReportsRepository(s)), s)
        return await svc.branch_digests(day)


async def _setup_branch_with_stock(client, h):
    br = (await client.post("/api/v1/branches", headers=h,
          json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    wh = (await client.post("/api/v1/warehouses", headers=h, json={
        "code": _rand("WH"), "name": _rand("WH"), "branch_id": br, "is_active": True})).json()["id"]
    prod = (await client.post("/api/v1/products", headers=h,
            json={"sku": _rand("SKU"), "name": "Brake pads CG125"})).json()["id"]
    await client.post("/api/v1/inventory/receive", headers=h, json={
        "warehouse_id": wh, "reference_type": "manual", "lines": [{"product_id": prod, "quantity": 20}]})
    return br, wh, prod


async def _enable_pos(client, h):
    flags = dict((await client.get("/api/v1/tenant/settings", headers=h)).json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags, "vat_rate": "0"})


# ------------------------------------------------------------------------- #
async def test_digest_reports_what_sold_and_how_it_was_paid(client):
    h, claims = await _login(client)
    tenant_id = claims["tenant_id"]
    await _enable_pos(client, h)
    br, wh, prod = await _setup_branch_with_stock(client, h)

    # Split payment so the by-method breakdown is exercised.
    r = await client.post("/api/v1/sales/pos/checkout", headers=h, json={
        "branch_id": br, "location_id": wh,
        "lines": [{"product_id": prod, "qty": 2, "unit_price": 150}],
        "payments": [{"method": "cash", "amount": 200}, {"method": "mobile_money", "amount": 100}]})
    assert r.status_code == 201, r.text

    mine = next(d for d in await _digests(tenant_id, TODAY) if d["branch_id"] == uuid.UUID(br))
    assert float(mine["gross_total"]) == 300.0
    assert any("Brake pads" in (s["description"] or "") for s in mine["sold"])
    methods = {p["method"]: float(p["amount"]) for p in mine["payments"]}
    assert methods["cash"] == 200.0 and methods["mobile_money"] == 100.0

    # It renders into the message a manager receives.
    from app.assistant.alerts import build_branch_daily_report

    msg = build_branch_daily_report(mine, currency="ZMW")
    assert "Cash: ZMW 200.00" in msg and "Mobile Money: ZMW 100.00" in msg


async def test_one_branch_takings_do_not_leak_into_another(client):
    """The whole point of a per-branch digest — Lusaka's numbers stay out of Solwezi's."""
    h, claims = await _login(client)
    tenant_id = claims["tenant_id"]
    await _enable_pos(client, h)
    selling, wh, prod = await _setup_branch_with_stock(client, h)
    quiet = (await client.post("/api/v1/branches", headers=h,
             json={"code": _rand("BR"), "name": _rand("Quiet")})).json()["id"]

    await client.post("/api/v1/sales/pos/checkout", headers=h, json={
        "branch_id": selling, "location_id": wh,
        "lines": [{"product_id": prod, "qty": 1, "unit_price": 500}],
        "payments": [{"method": "cash", "amount": 500}]})

    digests = await _digests(tenant_id, TODAY)
    seller = next(d for d in digests if d["branch_id"] == uuid.UUID(selling))
    assert float(seller["gross_total"]) == 500.0
    # The quiet branch had no sales and no activity, so it gets no digest at all.
    assert not [d for d in digests if d["branch_id"] == uuid.UUID(quiet)]


async def test_digest_counts_the_days_operational_activity(client):
    h, claims = await _login(client)
    tenant_id = claims["tenant_id"]
    br, wh, prod = await _setup_branch_with_stock(client, h)

    r = await client.post("/api/v1/order-requests", headers=h, json={
        "branch_id": wh, "purpose": "shelf_replenishment",
        "lines": [{"product_id": prod, "requested_qty": 5}]})
    assert r.status_code == 201, r.text

    mine = next(d for d in await _digests(tenant_id, TODAY) if d["branch_id"] == uuid.UUID(br))
    assert mine["order_requests"] >= 1
    from app.assistant.alerts import build_branch_daily_report

    assert "order request(s)" in build_branch_daily_report(mine, currency="ZMW")
