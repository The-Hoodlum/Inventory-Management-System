"""Integration tests for the pending-bike-sales import over HTTP:

upload -> preview -> confirm -> the bike is now SOLD and its invoice appears on the
accounts-receivable (outstanding) list with the right balance, aging and preserved
invoice number.

Requires a live database (DATABASE_URL) with the RBAC + demo seed; skipped otherwise.
"""
from __future__ import annotations

import io
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

KEY = "pending_bike_sales"
HEADERS = ["Sale Date", "Chassis Number", "Customer", "Price (ZMW)", "Amount Paid (ZMW)",
           "Phone", "Address", "Payment Method", "Invoice No."]
_LABEL_TO_KEY = {
    "Sale Date": "date", "Chassis Number": "chassis", "Customer": "customer",
    "Price (ZMW)": "price", "Amount Paid (ZMW)": "paid", "Phone": "phone",
    "Address": "address", "Payment Method": "method", "Invoice No.": "invoice",
}


@pytest_asyncio.fixture
async def client():
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _headers(client) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _rand(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _csv(rows: list[dict]) -> bytes:
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADERS)
    for row in rows:
        w.writerow([row.get(_LABEL_TO_KEY[h], "") for h in HEADERS])
    return buf.getvalue().encode("utf-8")


async def _upload(client, h, data: bytes) -> tuple[str, dict]:
    files = {"file": ("pending.csv", data, "text/csv")}
    r = await client.post(f"/api/v1/imports/{KEY}/upload", headers=h, files=files)
    assert r.status_code == 200, r.text
    j = r.json()
    return j["job_id"], j["detected_mapping"]


async def _preview(client, h, job_id, mapping):
    r = await client.post(f"/api/v1/imports/{KEY}/{job_id}/preview", headers=h,
                          json={"mapping": mapping, "options": {"create_missing_references": False, "value_maps": []}})
    assert r.status_code == 200, r.text
    return r.json()


async def _confirm(client, h, job_id, mapping):
    r = await client.post(f"/api/v1/imports/{KEY}/{job_id}/confirm", headers=h,
                          json={"mapping": mapping, "options": {"create_missing_references": False, "value_maps": []}})
    assert r.status_code == 200, r.text
    return r.json()


async def _enable_sales(client, h) -> None:
    flags = dict((await client.get("/api/v1/tenant/settings", headers=h)).json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    assert (await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags})).status_code == 200


async def _stock_bike(client, h) -> str:
    """Create a bike in stock (NOT sold) and return its chassis."""
    await _enable_sales(client, h)
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    wh = (await client.post("/api/v1/warehouses", headers=h, json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": br, "is_active": True})).json()["id"]
    model = (await client.post("/api/v1/motorcycles/models", headers=h, json={"brand": _rand("Br"), "name": _rand("Md")})).json()["id"]
    chassis = _rand("CH")
    r = await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": chassis, "model_id": model, "warehouse_id": wh, "branch_id": br,
        "selling_price": 20000, "assembly_required": False})
    assert r.status_code == 201, r.text
    return chassis


async def _outstanding_by_number(client, h, inv_no: str) -> dict | None:
    r = await client.get("/api/v1/sales/invoices/outstanding", headers=h, params={"limit": 500})
    assert r.status_code == 200, r.text
    for inv in r.json():
        if inv["invoice_number"] == inv_no:
            return inv
    return None


# ------------------------------------------------------------------------- #
async def test_target_listed_and_template_downloads(client):
    h = await _headers(client)
    r = await client.get("/api/v1/imports/targets", headers=h)
    assert any(t["key"] == KEY for t in r.json())
    r = await client.get(f"/api/v1/imports/targets/{KEY}/template", headers=h, params={"level": "standard"})
    assert r.status_code == 200 and b"Chassis Number" in r.content and b"Sale Date" in r.content
    assert b"Price" in r.content


async def test_imports_pending_sale_onto_ar(client):
    h = await _headers(client)
    chassis = await _stock_bike(client, h)
    buyer = _rand("Buyer")
    inv_no = _rand("INV")

    rows = [{"date": "2026-02-01", "chassis": chassis, "customer": buyer,
             "price": "20000", "paid": "5000", "phone": "260970000001",
             "method": "cash", "invoice": inv_no}]
    job_id, mapping = await _upload(client, h, _csv(rows))
    p = await _preview(client, h, job_id, mapping)
    assert p["valid_count"] == 1 and p["invalid_count"] == 0 and p["can_commit"] is True

    job = await _confirm(client, h, job_id, mapping)
    assert job["status"] == "completed" and job["imported_rows"] == 1

    # It now owes 15,000, dated to the original sale date, under the preserved invoice number.
    inv = await _outstanding_by_number(client, h, inv_no)
    assert inv is not None, "imported pending sale did not reach the outstanding list"
    assert abs(inv["balance"] - 15000) < 0.01
    assert abs(inv["amount_paid"] - 5000) < 0.01
    assert inv["invoice_date"] == "2026-02-01"

    # The bike is now sold (its chassis can't be sold again).
    p2 = await _preview(client, h, *(await _upload(client, h, _csv(
        [{"date": "2026-02-02", "chassis": chassis, "customer": buyer, "price": "20000", "paid": "1000"}]))))
    assert p2["invalid_count"] == 1
    assert any("cannot be sold" in e for row in p2["sample_errors"] for e in row["errors"])


async def test_validation_errors(client):
    h = await _headers(client)
    ch = await _stock_bike(client, h)
    dup = _rand("DUP")
    rows = [
        {"date": "2026-02-01", "chassis": _rand("GHOST"), "customer": "X", "price": "20000", "paid": "0"},  # not on record
        {"date": "2026-02-01", "chassis": ch, "customer": "Y", "price": "20000", "paid": "20000"},          # fully paid
        {"date": "2026-02-01", "chassis": dup, "customer": "Z", "price": "20000", "paid": "0"},
        {"date": "2026-02-02", "chassis": dup, "customer": "Z", "price": "20000", "paid": "0"},              # in-file dup
    ]
    job_id, mapping = await _upload(client, h, _csv(rows))
    p = await _preview(client, h, job_id, mapping)
    assert p["valid_count"] == 0 and p["invalid_count"] == 4
    joined = " ".join(e for row in p["sample_errors"] for e in row["errors"])
    assert "not on record" in joined
    assert "fully paid" in joined
    assert "Duplicate chassis" in joined
