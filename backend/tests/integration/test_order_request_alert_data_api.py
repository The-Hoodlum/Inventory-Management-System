"""The pending-order-request alert carries WHAT was requested.

Previously it exposed only a request number and an item count, so an approver had to open
the app to find out what was being asked for. This pins the enriched query: requester,
location, purpose and the actual lines.

Requires a live database (DATABASE_URL); skipped otherwise.
"""
from __future__ import annotations

import base64
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


async def _headers(client):
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}, _claims(tok)


async def _alert_data(tenant_id, warehouse_id):
    """Run the alert's own query, RLS-scoped, exactly as the scheduler would.

    The tenant MUST come from the caller (the login claims). Picking "the first tenant"
    silently returns nothing when the database holds more than one, which reads as a
    feature bug rather than a test bug.
    """
    from sqlalchemy import text

    from app.assistant.repository import AssistantRepository
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        await s.execute(text("SELECT set_config('app.current_tenant', :t, true)"),
                        {"t": str(tenant_id)})
        return await AssistantRepository(s).pending_order_requests([uuid.UUID(str(warehouse_id))])


async def test_pending_request_carries_requester_purpose_and_items(client):
    h, claims = await _headers(client)
    tenant_id = claims["tenant_id"]
    branch = (await client.post("/api/v1/branches", headers=h,
              json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    wh = (await client.post("/api/v1/warehouses", headers=h, json={
        "code": _rand("WH"), "name": _rand("Shop"), "branch_id": branch, "is_active": True})).json()["id"]
    p1 = (await client.post("/api/v1/products", headers=h,
          json={"sku": _rand("SKU"), "name": "Brake pads CG125"})).json()["id"]
    p2 = (await client.post("/api/v1/products", headers=h,
          json={"sku": _rand("SKU"), "name": "Chain lube 400ml"})).json()["id"]

    r = await client.post("/api/v1/order-requests", headers=h, json={
        "branch_id": wh, "purpose": "shelf_replenishment",
        "lines": [{"product_id": p1, "requested_qty": 10}, {"product_id": p2, "requested_qty": 6}]})
    assert r.status_code == 201, r.text
    number = r.json()["request_number"]

    data = await _alert_data(tenant_id, wh)
    matches = [x for x in data["requests"] if x["request_number"] == number]
    assert matches, f"{number} missing from the alert data: {[r['request_number'] for r in data['requests']]}"
    req = matches[0]
    assert req["item_count"] == 2
    assert req["purpose"] == "shelf_replenishment"
    assert req["requested_by"]                      # the creator's name is carried
    names = {i["name"] for i in req["items"]}
    assert "Brake pads CG125" in names and "Chain lube 400ml" in names
    qty = {i["name"]: i["qty"] for i in req["items"]}
    assert qty["Brake pads CG125"] == 10.0 and qty["Chain lube 400ml"] == 6.0

    # And it renders into the alert text an approver actually receives.
    from app.assistant.alerts import build_order_requests_message

    msg = build_order_requests_message(data)
    assert number in msg and "Brake pads CG125 x 10" in msg and "shelf replenishment" in msg
