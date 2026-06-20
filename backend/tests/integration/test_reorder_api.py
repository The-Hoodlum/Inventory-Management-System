"""End-to-end integration test for the reorder & procurement API.

Exercises the real FastAPI app against a live PostgreSQL database (RLS, JWT, the
reorder engine, and PO generation) using httpx's ASGI transport.

Requires a provisioned database (schema + RBAC + demo seed) and these env vars:
    DATABASE_URL           async DSN, e.g. postgresql+asyncpg://app_user:app_pw@localhost:5432/inventory
    JWT_SECRET_KEY         any non-empty secret
    DEMO_ADMIN_EMAIL       (optional) default: admin@demo.com
    DEMO_ADMIN_PASSWORD    (optional) default: ChangeMe123!

The whole module is skipped when DATABASE_URL is absent, so the default unit-test
run stays hermetic. Heavy imports happen inside the fixture so collection never
requires the database or app settings.
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
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_run_recommendations_then_generate_purchase_orders(client):
    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    # 1) Run the reorder engine across all warehouses, persisting actionable recs.
    r = await client.post(
        "/api/v1/reorder/run",
        headers=headers,
        json={"window_days": 90, "persist": True, "only_below_rop": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"items", "evaluated", "to_order", "generated_at"} <= body.keys()

    # 2) List pending recommendations.
    r = await client.get(
        "/api/v1/reorder/recommendations", headers=headers, params={"status": "pending"}
    )
    assert r.status_code == 200, r.text
    recs = r.json()["items"]

    # 3) If any have a supplier, generate POs and read one back.
    sourced = [rec["id"] for rec in recs if rec.get("supplier_id")]
    if sourced:
        r = await client.post(
            "/api/v1/reorder/purchase-orders",
            headers=headers,
            json={"recommendation_ids": sourced},
        )
        assert r.status_code == 201, r.text
        po_body = r.json()
        assert po_body["created"] >= 1
        assert len(po_body["purchase_orders"]) == po_body["created"]

        po_id = po_body["purchase_orders"][0]["id"]
        r = await client.get(f"/api/v1/purchase-orders/{po_id}", headers=headers)
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["po_number"]
        assert detail["status"] == "draft"
        assert len(detail["lines"]) >= 1


async def test_reorder_run_requires_authentication(client):
    r = await client.post("/api/v1/reorder/run", json={"window_days": 90})
    assert r.status_code in (401, 403)


async def test_reorder_run_rejects_invalid_service_level(client):
    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    # service_level must be in (0.5, 1); 1.5 should fail validation.
    r = await client.post(
        "/api/v1/reorder/run", headers=headers, json={"service_level": 1.5}
    )
    assert r.status_code == 422
