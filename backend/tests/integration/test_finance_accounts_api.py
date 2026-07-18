"""Integration tests for the finance accounts API (PR 1).

Guarantees:
- an account's balance is DERIVED (opening + movements) and returned on read;
- there is NO delete endpoint for a financial record (accounts are deactivated);
- no request can set/edit a balance — PATCH only touches name/active; unknown fields
  (e.g. opening_balance) are ignored and the derived balance is unchanged;
- branch scoping: a Lusaka-scoped user cannot see or read a Solwezi account.

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


async def _headers(client, email, password) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _branch(client, h) -> str:
    r = await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _role_id(client, h, name) -> str:
    roles = (await client.get("/api/v1/users/roles", headers=h)).json()
    return next(r["id"] for r in roles if r["name"] == name)


# ------------------------------------------------------------------------- #
async def test_create_lists_with_derived_balance_and_cannot_set_balance(client):
    admin = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    branch_id = await _branch(client, admin)

    r = await client.post("/api/v1/finance/accounts", headers=admin, json={
        "name": "Cash in hand", "type": "CASH", "branch_id": branch_id,
        "opening_balance": "100.00", "opening_as_of": "2026-01-01"})
    assert r.status_code == 201, r.text
    acct_id = r.json()["id"]

    # Listed with the DERIVED balance == opening (no movements yet).
    accounts = (await client.get("/api/v1/finance/accounts", headers=admin, params={"branch_id": branch_id})).json()
    mine = next(a for a in accounts if a["id"] == acct_id)
    assert float(mine["balance"]) == 100.0
    assert float(mine["total_in"]) == 0.0 and float(mine["total_out"]) == 0.0

    # PATCH cannot set/edit a balance: opening_balance is not an editable field, so passing
    # it is ignored and the derived balance is unchanged. Only name/active change.
    r = await client.patch(f"/api/v1/finance/accounts/{acct_id}", headers=admin,
                           json={"name": "Cash — main till", "opening_balance": "999999"})
    assert r.status_code == 200, r.text
    after = (await client.get(f"/api/v1/finance/accounts/{acct_id}", headers=admin)).json()
    assert after["name"] == "Cash — main till"
    assert float(after["balance"]) == 100.0  # NOT 999999 — a balance can never be set


async def test_no_delete_endpoint_for_accounts(client):
    admin = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    branch_id = await _branch(client, admin)
    acct_id = (await client.post("/api/v1/finance/accounts", headers=admin, json={
        "name": "Bank", "type": "BANK", "branch_id": branch_id})).json()["id"]
    # No hard-delete path exists for any financial record — the route is not allowed.
    r = await client.delete(f"/api/v1/finance/accounts/{acct_id}", headers=admin)
    assert r.status_code == 405, r.text


async def test_branch_scoping_hides_foreign_accounts(client):
    admin = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    a_br = await _branch(client, admin)
    b_br = await _branch(client, admin)
    a_acct = (await client.post("/api/v1/finance/accounts", headers=admin, json={
        "name": "Cash A", "type": "CASH", "branch_id": a_br})).json()["id"]
    b_acct = (await client.post("/api/v1/finance/accounts", headers=admin, json={
        "name": "Cash B", "type": "CASH", "branch_id": b_br})).json()["id"]

    # A user scoped to branch A only (Finance role: finance.read + finance.account.manage).
    email, pw = _rand("fin") + "@demo.com", "ScopeTest123!"
    await client.post("/api/v1/users", headers=admin, json={
        "email": email, "full_name": "Lusaka finance", "password": pw,
        "role_ids": [await _role_id(client, admin, "Finance")], "branch_ids": [a_br]})
    u = await _headers(client, email, pw)

    listed = {a["id"] for a in (await client.get("/api/v1/finance/accounts", headers=u)).json()}
    assert a_acct in listed and b_acct not in listed
    # Direct read of a foreign-branch account is a 403.
    assert (await client.get(f"/api/v1/finance/accounts/{b_acct}", headers=u)).status_code == 403
    # They CAN create in their own branch.
    r = await client.post("/api/v1/finance/accounts", headers=u, json={
        "name": "Mobile money A", "type": "MOBILE_MONEY", "branch_id": a_br})
    assert r.status_code == 201, r.text
    # But not in a foreign branch.
    r = await client.post("/api/v1/finance/accounts", headers=u, json={
        "name": "Sneaky B", "type": "CASH", "branch_id": b_br})
    assert r.status_code == 403, r.text
