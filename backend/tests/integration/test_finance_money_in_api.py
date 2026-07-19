"""Integration tests for finance money-in wiring (PR 2).

When a payment is recorded on a finance-active branch, finance posts one IN movement per
payment line to the account mapped to that method — so a split payment lands in the right
accounts, the figures reconcile EXACTLY with the sale, an unmapped method fails the sale
loudly, and voiding the sale reverses the money-in (originals preserved).

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


async def _enable_pos_no_vat(client, h) -> None:
    flags = dict((await client.get("/api/v1/tenant/settings", headers=h)).json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    r = await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags, "vat_rate": "0"})
    assert r.status_code == 200, r.text


async def _account(client, h, name, typ, branch_id) -> str:
    r = await client.post("/api/v1/finance/accounts", headers=h, json={
        "name": name, "type": typ, "branch_id": branch_id})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _balance(client, h, account_id) -> float:
    r = await client.get(f"/api/v1/finance/accounts/{account_id}", headers=h)
    assert r.status_code == 200, r.text
    return float(r.json()["balance"])


async def _setup_branch_stock(client, h):
    """A branch + location + a product with stock received into it."""
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    wh = (await client.post("/api/v1/warehouses", headers=h, json={
        "code": _rand("WH"), "name": _rand("WH"), "branch_id": br, "is_active": True})).json()["id"]
    prod = (await client.post("/api/v1/products", headers=h, json={"sku": _rand("SKU"), "name": "Widget"})).json()["id"]
    r = await client.post("/api/v1/inventory/receive", headers=h, json={
        "warehouse_id": wh, "reference_type": "manual", "lines": [{"product_id": prod, "quantity": 10}]})
    assert r.status_code in (200, 201), r.text
    return br, wh, prod


# ------------------------------------------------------------------------- #
async def test_split_payment_posts_to_mapped_accounts_and_reconciles(client):
    h = await _headers(client)
    await _enable_pos_no_vat(client, h)
    br, wh, prod = await _setup_branch_stock(client, h)
    cash = await _account(client, h, "Cash", "CASH", br)
    bank = await _account(client, h, "Bank", "BANK", br)
    # Map cash + bank_transfer for this branch (activates finance money-in for it).
    for method, acct in (("cash", cash), ("bank_transfer", bank)):
        r = await client.put("/api/v1/finance/payment-mappings", headers=h,
                             json={"branch_id": br, "method": method, "account_id": acct})
        assert r.status_code == 200, r.text

    # POS sale: 1 x 200 = 200 (VAT 0), paid split cash 120 + bank 80.
    r = await client.post("/api/v1/sales/pos/checkout", headers=h, json={
        "branch_id": br, "location_id": wh,
        "lines": [{"product_id": prod, "qty": 1, "unit_price": 200}],
        "payments": [{"method": "cash", "amount": 120}, {"method": "bank_transfer", "amount": 80}]})
    assert r.status_code == 201, r.text

    # One movement per line landed in the right account; sums reconcile exactly with the sale.
    assert await _balance(client, h, cash) == 120.0
    assert await _balance(client, h, bank) == 80.0


async def test_unmapped_method_fails_the_sale_loudly(client):
    h = await _headers(client)
    await _enable_pos_no_vat(client, h)
    br, wh, prod = await _setup_branch_stock(client, h)
    cash = await _account(client, h, "Cash", "CASH", br)
    # Branch is finance-active (cash mapped) but mobile_money is NOT mapped.
    r = await client.put("/api/v1/finance/payment-mappings", headers=h,
                        json={"branch_id": br, "method": "cash", "account_id": cash})
    assert r.status_code == 200, r.text

    r = await client.post("/api/v1/sales/pos/checkout", headers=h, json={
        "branch_id": br, "location_id": wh,
        "lines": [{"product_id": prod, "qty": 1, "unit_price": 200}],
        "payments": [{"method": "mobile_money", "amount": 200}]})
    # Fails loudly (400) rather than silently dropping the money; whole sale rolls back.
    assert r.status_code == 400, r.text
    assert "mobile_money" in r.text
    # Cash balance untouched — no stray movement was posted.
    assert await _balance(client, h, cash) == 0.0


async def test_dormant_branch_is_unaffected(client):
    h = await _headers(client)
    await _enable_pos_no_vat(client, h)
    br, wh, prod = await _setup_branch_stock(client, h)
    cash = await _account(client, h, "Cash", "CASH", br)  # account exists but NO mapping
    # No mappings -> finance money-in dormant for this branch: the sale succeeds and posts
    # nothing to finance (existing sales behaviour is untouched until finance is configured).
    r = await client.post("/api/v1/sales/pos/checkout", headers=h, json={
        "branch_id": br, "location_id": wh,
        "lines": [{"product_id": prod, "qty": 1, "unit_price": 200}],
        "payments": [{"method": "cash", "amount": 200}]})
    assert r.status_code == 201, r.text
    assert await _balance(client, h, cash) == 0.0


async def test_void_reverses_money_in(client):
    h = await _headers(client)
    await _enable_pos_no_vat(client, h)
    br, wh, prod = await _setup_branch_stock(client, h)
    cash = await _account(client, h, "Cash", "CASH", br)
    r = await client.put("/api/v1/finance/payment-mappings", headers=h,
                        json={"branch_id": br, "method": "cash", "account_id": cash})
    assert r.status_code == 200, r.text

    r = await client.post("/api/v1/sales/pos/checkout", headers=h, json={
        "branch_id": br, "location_id": wh,
        "lines": [{"product_id": prod, "qty": 1, "unit_price": 200}],
        "payments": [{"method": "cash", "amount": 200}]})
    assert r.status_code == 201, r.text
    invoice_id = r.json()["invoice"]["id"]
    assert await _balance(client, h, cash) == 200.0

    # Void the sale -> finance posts a reversing OUT; the balance returns to zero.
    r = await client.post(f"/api/v1/sales/invoices/{invoice_id}/void", headers=h,
                        json={"reason": "customer cancelled"})
    assert r.status_code == 200, r.text
    assert await _balance(client, h, cash) == 0.0
