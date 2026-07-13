"""Integration tests for the branch vs. location distinction in the admin API:

- a location (warehouse) cannot be created without a parent branch (422);
- deleting a branch is refused (409, naming what) while anything still references it, and
  succeeds (204) once it is empty — no data is wiped on the user's behalf.

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


def _rand(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


async def _headers(client) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _branch(client, h) -> str:
    r = await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_location_requires_a_parent_branch(client):
    h = await _headers(client)
    # No branch_id -> rejected (a location must live inside a branch).
    r = await client.post("/api/v1/warehouses", headers=h,
                          json={"code": _rand("WH"), "name": _rand("WH")})
    assert r.status_code == 422, r.text

    # With a parent branch -> created.
    branch_id = await _branch(client, h)
    r = await client.post("/api/v1/warehouses", headers=h,
                          json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": branch_id})
    assert r.status_code == 201, r.text
    assert r.json()["branch_id"] == branch_id


async def test_branch_delete_guarded_then_allowed_when_empty(client):
    h = await _headers(client)
    branch_id = await _branch(client, h)
    wh = await client.post("/api/v1/warehouses", headers=h,
                           json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": branch_id})
    assert wh.status_code == 201, wh.text
    wh_id = wh.json()["id"]

    # While a location references it, deletion is refused with a clear, itemised message.
    r = await client.delete(f"/api/v1/branches/{branch_id}", headers=h)
    assert r.status_code == 409, r.text
    body = r.text.lower()
    assert "location" in body and "cannot delete" in body

    # Remove the only reference, then the branch can be deleted (no data was wiped for us).
    assert (await client.delete(f"/api/v1/warehouses/{wh_id}", headers=h)).status_code == 204
    r = await client.delete(f"/api/v1/branches/{branch_id}", headers=h)
    assert r.status_code == 204, r.text
    # It's really gone.
    assert (await client.get(f"/api/v1/branches/{branch_id}", headers=h)).status_code == 404
