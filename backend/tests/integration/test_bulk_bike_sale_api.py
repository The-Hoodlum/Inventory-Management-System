"""Integration: selling SEVERAL bikes to one customer on ONE invoice.

- a bulk sale raises a single invoice for the combined total, marks every unit sold and
  links each to THAT invoice, takes one payment, and reports each bike (incl. any still
  owing assembly);
- it is all-or-nothing: if one bike can't be sold, nothing is;
- a bike listed twice is rejected;
- the (multi-bike) invoice PDF renders.

Requires a live database; skipped otherwise.
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


async def _enable_sales(client, h) -> None:
    flags = dict((await client.get("/api/v1/tenant/settings", headers=h)).json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    assert (await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags})).status_code == 200


async def _warehouse(client, h) -> tuple[str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    wh = (await client.post("/api/v1/warehouses", headers=h, json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": br, "is_active": True})).json()["id"]
    return wh, br


async def _unit(client, h, wh, br, *, price, assembly_required=False) -> dict:
    model = (await client.post("/api/v1/motorcycles/models", headers=h, json={"brand": _rand("Br"), "name": _rand("Md")})).json()["id"]
    r = await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "model_id": model, "warehouse_id": wh, "branch_id": br,
        "selling_price": price, "assembly_required": assembly_required})
    assert r.status_code == 201, r.text
    return r.json()


async def _unit_status(client, h, uid) -> dict:
    return (await client.get(f"/api/v1/motorcycles/units/{uid}", headers=h)).json()


async def test_bulk_sells_many_on_one_invoice(client):
    h = await _headers(client)
    await _enable_sales(client, h)
    wh, br = await _warehouse(client, h)
    a = await _unit(client, h, wh, br, price=20000)                          # assembled
    b = await _unit(client, h, wh, br, price=56000)                          # assembled
    c = await _unit(client, h, wh, br, price=24500, assembly_required=True)  # unassembled
    cust = (await client.post("/api/v1/customers", headers=h, json={"name": _rand("Buyer")})).json()["id"]

    total = 20000 + 56000 + 24500
    r = await client.post("/api/v1/sales/bike-sale/bulk", headers=h, json={
        "customer_id": cust,
        "lines": [{"unit_id": a["id"]}, {"unit_id": b["id"]}, {"unit_id": c["id"]}],
        "payments": [{"method": "cash", "amount": total}],
    })
    assert r.status_code == 201, r.text
    res = r.json()

    # One invoice for the combined total; three bikes; a receipt.
    assert res["total"] == total
    assert float(res["invoice"]["grand_total_zmw"]) == total
    assert len(res["bikes"]) == 3
    assert res["receipt"] is not None
    inv_no = res["invoice"]["invoice_number"]

    # Every unit is sold and linked to the SAME invoice; the unassembled one owes assembly.
    for u in (a, b, c):
        s = await _unit_status(client, h, u["id"])
        assert s["status"] == "sold" and s["sold_invoice_number"] == inv_no
    assert (await _unit_status(client, h, c["id"]))["assembly_pending"] is True
    assert next(x for x in res["bikes"] if x["unit_id"] == c["id"])["assembly_pending"] is True

    # The multi-bike invoice PDF renders.
    pdf = await client.get(f"/api/v1/sales/invoices/{res['invoice']['id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


async def test_bulk_is_all_or_nothing(client):
    h = await _headers(client)
    await _enable_sales(client, h)
    wh, br = await _warehouse(client, h)
    a = await _unit(client, h, wh, br, price=20000)
    b = await _unit(client, h, wh, br, price=30000)
    # Put b on hold -> not sellable.
    assert (await client.post(f"/api/v1/motorcycles/units/{b['id']}/transition", headers=h,
            json={"to_status": "on_hold", "hold_reason": "damaged"})).status_code == 200

    r = await client.post("/api/v1/sales/bike-sale/bulk", headers=h, json={
        "lines": [{"unit_id": a["id"]}, {"unit_id": b["id"]}]})
    assert r.status_code == 400
    # a must NOT have been sold — the whole batch rolled back.
    assert (await _unit_status(client, h, a["id"]))["status"] != "sold"


async def test_bulk_rejects_duplicate_unit(client):
    h = await _headers(client)
    await _enable_sales(client, h)
    wh, br = await _warehouse(client, h)
    a = await _unit(client, h, wh, br, price=20000)
    r = await client.post("/api/v1/sales/bike-sale/bulk", headers=h, json={
        "lines": [{"unit_id": a["id"]}, {"unit_id": a["id"]}]})
    assert r.status_code == 400 and "more than once" in r.text.lower()
    assert (await _unit_status(client, h, a["id"]))["status"] != "sold"
