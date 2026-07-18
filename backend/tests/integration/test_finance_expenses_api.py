"""Integration tests for finance expenses (PR 3).

- recording an expense reduces its account's balance by exactly the amount;
- only managers (finance.expense.manage) can record; a non-manager with finance.read may
  VIEW within their branch scope but not create (403);
- voiding an expense restores the balance (reversal, not delete) and no delete route exists;
- a receipt attachment round-trips.

Requires a live database (DATABASE_URL) with the RBAC + demo seed; skipped otherwise.
"""
from __future__ import annotations

import datetime as dt
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
    return (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]


async def _account(client, h, name, branch_id, opening="0") -> str:
    r = await client.post("/api/v1/finance/accounts", headers=h, json={
        "name": name, "type": "CASH", "branch_id": branch_id, "opening_balance": opening})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _balance(client, h, account_id) -> float:
    return float((await client.get(f"/api/v1/finance/accounts/{account_id}", headers=h)).json()["balance"])


async def _role_id(client, h, name) -> str:
    roles = (await client.get("/api/v1/users/roles", headers=h)).json()
    return next(r["id"] for r in roles if r["name"] == name)


TODAY = dt.date.today().isoformat()


# ------------------------------------------------------------------------- #
async def test_expense_reduces_balance_and_void_restores_it(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    br = await _branch(client, h)
    acct = await _account(client, h, "Cash", br, opening="1000")
    cat = (await client.post("/api/v1/finance/expense-categories", headers=h, json={"name": _rand("Fuel")})).json()

    r = await client.post("/api/v1/finance/expenses", headers=h, json={
        "account_id": acct, "amount": "300", "expense_date": TODAY,
        "category_id": cat["id"], "payee": "Total", "description": "Diesel"})
    assert r.status_code == 201, r.text
    expense_id = r.json()["id"]
    assert await _balance(client, h, acct) == 700.0  # dropped by exactly 300

    # No hard-delete for a financial record.
    assert (await client.delete(f"/api/v1/finance/expenses/{expense_id}", headers=h)).status_code == 405

    # Void = reversal: balance returns to 1000, record kept + marked voided.
    r = await client.post(f"/api/v1/finance/expenses/{expense_id}/void", headers=h, json={"reason": "duplicate"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "voided"
    assert await _balance(client, h, acct) == 1000.0


async def test_only_managers_record_non_managers_view_within_scope(client):
    admin = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    br = await _branch(client, admin)
    acct = await _account(client, admin, "Cash", br, opening="500")
    exp = (await client.post("/api/v1/finance/expenses", headers=admin, json={
        "account_id": acct, "amount": "100", "expense_date": TODAY})).json()

    # A Cashier scoped to this branch: has finance.read (view) but NOT finance.expense.manage.
    email, pw = _rand("cash") + "@demo.com", "ScopeTest123!"
    await client.post("/api/v1/users", headers=admin, json={
        "email": email, "full_name": "Till cashier", "password": pw,
        "role_ids": [await _role_id(client, admin, "Cashier")], "branch_ids": [br]})
    u = await _headers(client, email, pw)

    # Can VIEW the branch's expenses.
    listed = {e["id"] for e in (await client.get("/api/v1/finance/expenses", headers=u)).json()}
    assert exp["id"] in listed
    # Cannot record (manager-only).
    r = await client.post("/api/v1/finance/expenses", headers=u, json={
        "account_id": acct, "amount": "20", "expense_date": TODAY})
    assert r.status_code == 403, r.text
    # Cannot void either.
    assert (await client.post(f"/api/v1/finance/expenses/{exp['id']}/void", headers=u,
                              json={"reason": "x"})).status_code == 403


async def test_branch_scoping_hides_foreign_expenses(client):
    admin = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    a_br, b_br = await _branch(client, admin), await _branch(client, admin)
    a_acct = await _account(client, admin, "Cash A", a_br, opening="100")
    b_acct = await _account(client, admin, "Cash B", b_br, opening="100")
    await client.post("/api/v1/finance/expenses", headers=admin, json={"account_id": a_acct, "amount": "10", "expense_date": TODAY})
    b_exp = (await client.post("/api/v1/finance/expenses", headers=admin, json={"account_id": b_acct, "amount": "10", "expense_date": TODAY})).json()

    email, pw = _rand("mgr") + "@demo.com", "ScopeTest123!"
    await client.post("/api/v1/users", headers=admin, json={
        "email": email, "full_name": "A finance", "password": pw,
        "role_ids": [await _role_id(client, admin, "Finance")], "branch_ids": [a_br]})
    u = await _headers(client, email, pw)

    branches_seen = {e["branch_id"] for e in (await client.get("/api/v1/finance/expenses", headers=u)).json()}
    assert a_br in branches_seen and b_br not in branches_seen
    # Direct read of the foreign expense is a 403.
    assert (await client.get(f"/api/v1/finance/expenses/{b_exp['id']}", headers=u)).status_code == 403
    # Cannot record against a foreign-branch account.
    assert (await client.post("/api/v1/finance/expenses", headers=u, json={
        "account_id": b_acct, "amount": "5", "expense_date": TODAY})).status_code == 403


async def test_receipt_attachment_round_trips(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    br = await _branch(client, h)
    acct = await _account(client, h, "Cash", br, opening="100")
    exp = (await client.post("/api/v1/finance/expenses", headers=h, json={
        "account_id": acct, "amount": "10", "expense_date": TODAY})).json()

    body = b"%PDF-1.4 fake receipt bytes"
    r = await client.post(f"/api/v1/finance/expenses/{exp['id']}/attachment", headers=h,
                         files={"file": ("receipt.pdf", body, "application/pdf")})
    assert r.status_code == 204, r.text
    # The list now flags it, and the bytes round-trip on download.
    got = next(e for e in (await client.get("/api/v1/finance/expenses", headers=h)).json() if e["id"] == exp["id"])
    assert got["has_attachment"] is True
    dl = await client.get(f"/api/v1/finance/expenses/{exp['id']}/attachment", headers=h)
    assert dl.status_code == 200 and dl.content == body
