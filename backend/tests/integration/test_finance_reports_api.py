"""Integration tests for the finance dashboard, account statement and day book (PR 5).

- the account statement carries a running balance (opening -> per-row -> closing);
- the day book's closing == opening + money in - expenses - handovers for the period, per
  branch, and renders as a PDF;
- the dashboard reflects the period's money in (from real sale payments), expenses out and
  handovers out, and lists per-account balances.

Uses a fresh branch per test (deterministic) and a whole-month / wide window (so the UTC
"now" of each movement always falls inside the range, regardless of the runner's timezone).

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


async def _headers(client) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _branch(client, h) -> str:
    return (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]


async def _account(client, h, name, typ, branch_id, opening="0") -> str:
    r = await client.post("/api/v1/finance/accounts", headers=h, json={
        "name": name, "type": typ, "branch_id": branch_id, "opening_balance": opening})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _expense(client, h, account_id, amount) -> None:
    r = await client.post("/api/v1/finance/expenses", headers=h, json={
        "account_id": account_id, "amount": str(amount), "expense_date": TODAY.isoformat()})
    assert r.status_code == 201, r.text


async def _handover(client, h, from_id, to_id, amount) -> None:
    r = await client.post("/api/v1/finance/handovers", headers=h, json={
        "from_account_id": from_id, "to_account_id": to_id, "amount": str(amount),
        "received_by_name": "Grace"})
    assert r.status_code == 201, r.text


# ------------------------------------------------------------------------- #
async def test_account_statement_running_balance(client):
    h = await _headers(client)
    br = await _branch(client, h)
    cash = await _account(client, h, "Cash", "CASH", br, opening="500")
    bank = await _account(client, h, "Bank", "BANK", br, opening="0")
    await _expense(client, h, cash, 100)                                        # OUT 100
    await client.post("/api/v1/finance/transfers", headers=h, json={            # OUT 50
        "from_account_id": cash, "to_account_id": bank, "amount": "50"})

    params = {"date_from": (TODAY - dt.timedelta(days=1)).isoformat(),
              "date_to": (TODAY + dt.timedelta(days=1)).isoformat()}
    stmt = (await client.get(f"/api/v1/finance/accounts/{cash}/statement", headers=h, params=params)).json()
    assert float(stmt["opening_balance"]) == 500.0
    balances = [float(r["running_balance"]) for r in stmt["rows"]]
    assert balances[-1] == 350.0                       # 500 - 100 - 50
    assert float(stmt["closing_balance"]) == 350.0
    # PDF renders.
    pdf = await client.get(f"/api/v1/finance/accounts/{cash}/statement.pdf", headers=h, params=params)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


async def test_day_book_invariant_and_pdf(client):
    h = await _headers(client)
    br = await _branch(client, h)
    cash = await _account(client, h, "Cash", "CASH", br, opening="1000")
    custody = await _account(client, h, "Custody", "CUSTODY", None)
    await _expense(client, h, cash, 120)
    await _handover(client, h, cash, custody, 300)

    params = {"period": "monthly", "date": TODAY.isoformat(), "branch_id": br}
    book = (await client.get("/api/v1/finance/day-book", headers=h, params=params)).json()
    row = next(r for r in book["rows"] if r["branch_id"] == br)
    assert float(row["opening"]) == 1000.0
    assert float(row["expenses"]) == 120.0
    assert float(row["handovers"]) == 300.0
    # The invariant: closing == opening + money_in - expenses - handovers.
    expected = float(row["opening"]) + float(row["money_in"]) - float(row["expenses"]) - float(row["handovers"])
    assert float(row["closing"]) == expected == 580.0

    pdf = await client.get("/api/v1/finance/day-book.pdf", headers=h, params=params)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


async def test_dashboard_reflects_money_in_expenses_handovers(client):
    h = await _headers(client)
    # Enable POS so a real sale posts money in.
    flags = dict((await client.get("/api/v1/tenant/settings", headers=h)).json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags, "vat_rate": "0"})

    br = await _branch(client, h)
    wh = (await client.post("/api/v1/warehouses", headers=h, json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": br, "is_active": True})).json()["id"]
    prod = (await client.post("/api/v1/products", headers=h, json={"sku": _rand("SKU"), "name": "Widget"})).json()["id"]
    await client.post("/api/v1/inventory/receive", headers=h, json={"warehouse_id": wh, "reference_type": "manual", "lines": [{"product_id": prod, "quantity": 5}]})
    cash = await _account(client, h, "Cash", "CASH", br, opening="0")
    custody = await _account(client, h, "Custody", "CUSTODY", None)
    await client.put("/api/v1/finance/payment-mappings", headers=h, json={"branch_id": br, "method": "cash", "account_id": cash})

    # A POS cash sale posts money IN 200.
    r = await client.post("/api/v1/sales/pos/checkout", headers=h, json={
        "branch_id": br, "location_id": wh, "lines": [{"product_id": prod, "qty": 1, "unit_price": 200}],
        "payments": [{"method": "cash", "amount": 200}]})
    assert r.status_code == 201, r.text
    await _expense(client, h, cash, 50)
    await _handover(client, h, cash, custody, 30)

    params = {"date_from": (TODAY - dt.timedelta(days=1)).isoformat(),
              "date_to": (TODAY + dt.timedelta(days=1)).isoformat(), "branch_id": br}
    dash = (await client.get("/api/v1/finance/dashboard", headers=h, params=params)).json()
    assert float(dash["money_in"]) == 200.0
    assert float(dash["expenses_out"]) == 50.0
    assert float(dash["handovers_out"]) == 30.0
    # The cash account KPI reflects the derived balance: 0 + 200 - 50 - 30 = 120.
    kpi = next(a for a in dash["accounts"] if a["id"] == cash)
    assert float(kpi["balance"]) == 120.0
    # Money-in-by-account carries the sale payment.
    assert any(m["account_id"] == cash and float(m["amount"]) == 200.0 for m in dash["money_in_by_account"])

    await client.put("/api/v1/tenant/settings", headers=h, json={"vat_rate": 0})
