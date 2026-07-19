"""Integration tests for finance transfers + cash handovers (PR 4).

- a transfer posts a paired OUT + IN (net zero across the two accounts) and reverses cleanly;
- a handover posts an OUT on record (branch cash drops; destination NOT credited yet — the
  money is in transit, not counted in both), confirming posts the IN, and a short
  confirmation records a discrepancy with a mandatory reason (never absorbed);
- the printable slip renders and the register carries both names; no delete route exists.

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
    return (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]


async def _account(client, h, name, typ, branch_id, opening="0") -> str:
    r = await client.post("/api/v1/finance/accounts", headers=h, json={
        "name": name, "type": typ, "branch_id": branch_id, "opening_balance": opening})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _balance(client, h, account_id) -> float:
    return float((await client.get(f"/api/v1/finance/accounts/{account_id}", headers=h)).json()["balance"])


# ------------------------------------------------------------------------- #
async def test_transfer_paired_and_reversible(client):
    h = await _headers(client)
    br = await _branch(client, h)
    cash = await _account(client, h, "Cash", "CASH", br, opening="1000")
    bank = await _account(client, h, "Bank", "BANK", br, opening="0")

    r = await client.post("/api/v1/finance/transfers", headers=h, json={
        "from_account_id": cash, "to_account_id": bank, "amount": "400", "notes": "Banking cash"})
    assert r.status_code == 201, r.text
    transfer_id = r.json()["id"]
    assert await _balance(client, h, cash) == 600.0
    assert await _balance(client, h, bank) == 400.0

    # Reverse -> paired reversing pair nets both back.
    r = await client.post(f"/api/v1/finance/transfers/{transfer_id}/reverse", headers=h, json={"reason": "wrong account"})
    assert r.status_code == 200, r.text
    assert await _balance(client, h, cash) == 1000.0
    assert await _balance(client, h, bank) == 0.0


async def test_handover_two_sided_with_discrepancy_and_slip(client):
    h = await _headers(client)
    br = await _branch(client, h)
    cash = await _account(client, h, "Till", "CASH", br, opening="1000")
    custody = await _account(client, h, "HQ custody", "CUSTODY", None)

    # Record -> OUT posted immediately; branch drops, destination not yet credited.
    r = await client.post("/api/v1/finance/handovers", headers=h, json={
        "from_account_id": cash, "to_account_id": custody, "amount": "600",
        "handed_over_by_name": "John (cashier)", "received_by_name": "Grace (accountant)",
        "denomination_breakdown": {"K100": 5, "K50": 2}})
    assert r.status_code == 201, r.text
    ho = r.json()
    assert ho["status"] == "PENDING_CONFIRMATION"
    assert await _balance(client, h, cash) == 400.0       # money left the branch
    assert await _balance(client, h, custody) == 0.0      # in transit — not in both

    # A short confirmation with NO reason is rejected (shortfall never absorbed).
    r = await client.post(f"/api/v1/finance/handovers/{ho['id']}/confirm", headers=h, json={"confirmed_amount": "550"})
    assert r.status_code == 400, r.text

    # With a reason -> DISPUTED, discrepancy recorded, only what was received is credited.
    r = await client.post(f"/api/v1/finance/handovers/{ho['id']}/confirm", headers=h,
                         json={"confirmed_amount": "550", "discrepancy_reason": "K50 note missing"})
    assert r.status_code == 200, r.text
    confirmed = r.json()
    assert confirmed["status"] == "DISPUTED"
    assert float(confirmed["discrepancy_amount"]) == 50.0
    assert await _balance(client, h, custody) == 550.0    # only actual received credited
    assert await _balance(client, h, cash) == 400.0       # shortfall surfaced, not restored

    # The printable slip renders and carries both names in the register.
    slip = await client.get(f"/api/v1/finance/handovers/{ho['id']}/slip", headers=h)
    assert slip.status_code == 200 and slip.content[:4] == b"%PDF"
    reg = next(x for x in (await client.get("/api/v1/finance/handovers", headers=h)).json() if x["id"] == ho["id"])
    assert reg["received_by_name"] == "Grace (accountant)" and reg["handed_over_by_name"] == "John (cashier)"

    # No hard-delete for a handover record.
    assert (await client.delete(f"/api/v1/finance/handovers/{ho['id']}", headers=h)).status_code == 405


async def test_handover_confirm_matching_credits_full(client):
    h = await _headers(client)
    br = await _branch(client, h)
    cash = await _account(client, h, "Till", "CASH", br, opening="500")
    custody = await _account(client, h, "HQ custody 2", "CUSTODY", None)
    ho = (await client.post("/api/v1/finance/handovers", headers=h, json={
        "from_account_id": cash, "to_account_id": custody, "amount": "500",
        "received_by_name": "Grace"})).json()
    r = await client.post(f"/api/v1/finance/handovers/{ho['id']}/confirm", headers=h, json={"confirmed_amount": "500"})
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED"
    assert await _balance(client, h, custody) == 500.0
