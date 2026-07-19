"""A completed bike sale alerts the branch's MANAGERS in real time, with the detail they
would otherwise have to open the app for: what went out, for how much, to whom, and how it
was paid.

Recipients are resolved by ROLE (Branch Manager) within the sale's branch — a manager of a
different branch must not be told. The seller is excluded from their own alert.

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


async def _login(client, email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}, _claims(tok)


async def _enable_sales(client, h) -> None:
    flags = dict((await client.get("/api/v1/tenant/settings", headers=h)).json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags, "vat_rate": "0"})


async def _branch_manager(client, h, branch_ids) -> uuid.UUID:
    roles = (await client.get("/api/v1/users/roles", headers=h)).json()
    role_id = next(r["id"] for r in roles if r["name"] == "Branch Manager")
    r = await client.post("/api/v1/users", headers=h, json={
        "email": f"{_rand('bm')}@demo.com", "full_name": "Branch Boss",
        "password": "ScopeTest123!", "role_ids": [role_id], "branch_ids": branch_ids})
    assert r.status_code in (200, 201), r.text
    return uuid.UUID(r.json()["id"])


async def _notifications_for(tenant_id, user_id) -> list[dict]:
    """Read a user's stored notifications straight from the DB (they have no session here).

    The tenant MUST be the one the sale happened in — notifications are RLS-scoped, so a
    wrong tenant silently returns nothing.
    """
    from sqlalchemy import select, text

    from app.db.session import AsyncSessionLocal
    from app.models import Notification

    async with AsyncSessionLocal() as s:
        await s.execute(text("SELECT set_config('app.current_tenant', :t, true)"),
                        {"t": str(tenant_id)})
        rows = (await s.execute(
            select(Notification).where(Notification.recipient_user_id == user_id)
            .order_by(Notification.created_at.desc())
        )).scalars().all()
        return [{"event_type": n.event_type, "title": n.title, "body": n.body,
                 "severity": n.severity, "branch_id": n.branch_id} for n in rows]


async def _assembled_unit(client, h, *, price, branch_id=None, colour=None) -> dict:
    model = (await client.post("/api/v1/motorcycles/models", headers=h,
             json={"name": _rand("Model"), "brand": "TVS"})).json()
    body = {"chassis_number": _rand("CH"), "engine_number": _rand("EN"),
            "model_id": model["id"], "selling_price": price}
    if branch_id:
        body["branch_id"] = branch_id
    if colour:
        c = await client.post("/api/v1/motorcycles/colours", headers=h, json={"name": colour})
        assert c.status_code == 201, c.text
        body["colour_id"] = c.json()["id"]
    r = await client.post("/api/v1/motorcycles/units", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _customer(client, h, *, name, phone, city) -> dict:
    r = await client.post("/api/v1/customers", headers=h, json={
        "name": name, "phone": phone,
        "addresses": [{"line1": "12 Cairo Road", "city": city, "is_default": True}]})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------------- #
async def test_bike_sale_alerts_the_branch_manager_with_full_details(client):
    h, claims = await _login(client)
    tenant_id = claims["tenant_id"]
    await _enable_sales(client, h)
    branch = (await client.post("/api/v1/branches", headers=h,
              json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    manager = await _branch_manager(client, h, [branch])
    colour = _rand("MetallicRed")
    unit = await _assembled_unit(client, h, price=18000, branch_id=branch, colour=colour)
    buyer = await _customer(client, h, name=_rand("Grace"), phone="+260971234567", city="Lusaka")

    r = await client.post("/api/v1/sales/bike-sale", headers=h, json={
        "unit_id": unit["id"], "branch_id": branch, "price": 18000,
        "customer_id": buyer["id"], "payments": [{"method": "cash", "amount": 18000}]})
    assert r.status_code == 201, r.text

    notes = [n for n in await _notifications_for(tenant_id, manager) if n["event_type"] == "bike.sold"]
    assert len(notes) == 1, "the branch manager should be alerted exactly once"
    note = notes[0]
    # Routine event -> info severity (push is opted into separately, not via severity).
    assert note["severity"] == "info"
    body = note["body"]
    assert unit["model_name"] in note["title"]            # model
    assert colour in note["title"]                        # colour
    assert "18,000" in note["title"]                      # price charged
    assert unit["chassis_number"] in body                 # which bike
    assert buyer["name"] in body                          # customer name
    assert "+260971234567" in body                        # phone
    assert "Cairo Road" in body and "Lusaka" in body      # address
    assert "Invoice:" in body                             # invoice number
    assert "cash" in body.lower() and "Paid:" in body     # how much and how
    assert "fully paid" in body.lower()                   # nothing outstanding


async def test_partial_payment_reports_the_outstanding_balance(client):
    h, claims = await _login(client)
    tenant_id = claims["tenant_id"]
    await _enable_sales(client, h)
    branch = (await client.post("/api/v1/branches", headers=h,
              json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    manager = await _branch_manager(client, h, [branch])
    unit = await _assembled_unit(client, h, price=20000, branch_id=branch, colour=_rand("Blue"))
    buyer = await _customer(client, h, name=_rand("Mwansa"), phone="+260955000111", city="Ndola")

    # Pays 15,000 of 20,000 -> 5,000 still owed.
    r = await client.post("/api/v1/sales/bike-sale", headers=h, json={
        "unit_id": unit["id"], "branch_id": branch, "price": 20000,
        "customer_id": buyer["id"], "payments": [{"method": "mobile_money", "amount": 15000}]})
    assert r.status_code == 201, r.text

    note = next(n for n in await _notifications_for(tenant_id, manager) if n["event_type"] == "bike.sold")
    body = note["body"]
    assert "15,000" in body and "mobile money" in body.lower()
    assert "Balance due:" in body and "5,000" in body


async def test_manager_of_another_branch_is_not_told(client):
    h, claims = await _login(client)
    tenant_id = claims["tenant_id"]
    await _enable_sales(client, h)
    selling_branch = (await client.post("/api/v1/branches", headers=h,
                      json={"code": _rand("BR"), "name": _rand("Sell")})).json()["id"]
    other_branch = (await client.post("/api/v1/branches", headers=h,
                    json={"code": _rand("BR"), "name": _rand("Other")})).json()["id"]
    other_manager = await _branch_manager(client, h, [other_branch])
    unit = await _assembled_unit(client, h, price=9000, branch_id=selling_branch)

    r = await client.post("/api/v1/sales/bike-sale", headers=h, json={
        "unit_id": unit["id"], "branch_id": selling_branch, "price": 9000})
    assert r.status_code == 201, r.text

    notes = [n for n in await _notifications_for(tenant_id, other_manager) if n["event_type"] == "bike.sold"]
    assert notes == [], "a manager of a different branch must not receive the alert"


async def test_bulk_sale_alerts_once_summarising_every_bike(client):
    h, claims = await _login(client)
    tenant_id = claims["tenant_id"]
    await _enable_sales(client, h)
    branch = (await client.post("/api/v1/branches", headers=h,
              json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    manager = await _branch_manager(client, h, [branch])
    a = await _assembled_unit(client, h, price=10000, branch_id=branch)
    b = await _assembled_unit(client, h, price=12000, branch_id=branch)

    r = await client.post("/api/v1/sales/bike-sale/bulk", headers=h, json={
        "branch_id": branch,
        "lines": [{"unit_id": a["id"], "price": 10000}, {"unit_id": b["id"], "price": 12000}],
        "payments": [{"method": "mobile_money", "amount": 22000}]})
    assert r.status_code == 201, r.text

    notes = [n for n in await _notifications_for(tenant_id, manager) if n["event_type"] == "bike.sold"]
    assert len(notes) == 1, "one alert for the whole basket, not one per bike"
    note = notes[0]
    assert "2 bikes sold" in note["title"] and "22,000" in note["title"]
    assert a["chassis_number"] in note["body"] and b["chassis_number"] in note["body"]
    assert "mobile money" in note["body"].lower()
