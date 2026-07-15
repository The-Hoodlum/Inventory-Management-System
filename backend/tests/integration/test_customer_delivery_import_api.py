"""Integration tests for the customer-delivery-notes import over HTTP:

upload -> preview (chassis matched / unmatched / duplicate) -> confirm (record-only:
a completed customer_deliveries row per bike, no stock/sale fabricated) -> verify.

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

KEY = "customer_delivery_notes"
HEADERS = ["Delivery Date", "Chassis Number", "Customer", "Invoice No.", "Received By", "Remarks"]


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
    key_by_label = {
        "Delivery Date": "date", "Chassis Number": "chassis", "Customer": "customer",
        "Invoice No.": "invoice", "Received By": "received_by", "Remarks": "remarks",
    }
    for row in rows:
        w.writerow([row.get(key_by_label[h], "") for h in HEADERS])
    return buf.getvalue().encode("utf-8")


async def _upload(client, h, data: bytes) -> tuple[str, dict]:
    files = {"file": ("deliveries.csv", data, "text/csv")}
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


async def _warehouse(client, h) -> tuple[str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]
    wh = (await client.post("/api/v1/warehouses", headers=h, json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": br, "is_active": True})).json()["id"]
    return wh, br


async def _sold_bike(client, h) -> tuple[str, str]:
    """Create a bike in a branch/warehouse and sell it to a named customer; return
    (chassis, customer_name)."""
    await _enable_sales(client, h)
    wh, br = await _warehouse(client, h)
    model = (await client.post("/api/v1/motorcycles/models", headers=h, json={"brand": _rand("Br"), "name": _rand("Md")})).json()["id"]
    chassis = _rand("CH")
    unit = (await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": chassis, "model_id": model, "warehouse_id": wh, "branch_id": br,
        "selling_price": 20000, "assembly_required": False})).json()
    name = _rand("Buyer")
    cust = (await client.post("/api/v1/customers", headers=h, json={"name": name})).json()["id"]
    r = await client.post("/api/v1/sales/bike-sale", headers=h, json={"unit_id": unit["id"], "customer_id": cust, "price": 20000})
    assert r.status_code == 201, r.text
    return chassis, name


async def _deliveries_for_chassis(client, h, chassis: str) -> list[dict]:
    r = await client.get("/api/v1/customer-deliveries", headers=h, params={"limit": 500})
    return [cd for cd in r.json() if any(ln.get("chassis_number") == chassis for ln in cd["lines"])]


# ------------------------------------------------------------------------- #
async def test_target_listed_and_template_downloads(client):
    h = await _headers(client)
    r = await client.get("/api/v1/imports/targets", headers=h)
    assert any(t["key"] == KEY for t in r.json())
    r = await client.get(f"/api/v1/imports/targets/{KEY}/template", headers=h, params={"level": "standard"})
    assert r.status_code == 200 and b"Chassis Number" in r.content and b"Delivery Date" in r.content


async def test_imports_delivery_note_and_dedupes(client):
    h = await _headers(client)
    chassis, buyer = await _sold_bike(client, h)

    # Customer auto-resolves from the sold bike; only Date + Chassis are needed.
    job_id, mapping = await _upload(client, h, _csv([{"date": "2026-03-04", "chassis": chassis, "remarks": "Handed over"}]))
    p = await _preview(client, h, job_id, mapping)
    assert p["valid_count"] == 1 and p["invalid_count"] == 0 and p["can_commit"] is True

    job = await _confirm(client, h, job_id, mapping)
    assert job["status"] == "completed" and job["imported_rows"] == 1

    got = await _deliveries_for_chassis(client, h, chassis)
    assert len(got) == 1
    cd = got[0]
    assert cd["delivery_mode"] == "sale" and cd["status"] == "delivered"
    assert cd["customer_name"] == buyer
    assert any(ln["line_kind"] == "motorcycle" and ln["chassis_number"] == chassis for ln in cd["lines"])

    # Re-importing the same chassis is rejected (already has a delivery note).
    job_id2, mapping2 = await _upload(client, h, _csv([{"date": "2026-03-05", "chassis": chassis}]))
    p2 = await _preview(client, h, job_id2, mapping2)
    assert p2["invalid_count"] == 1
    assert any("already has a delivery note" in e for row in p2["sample_errors"] for e in row["errors"])


async def test_unknown_chassis_and_in_file_duplicate_error(client):
    h = await _headers(client)
    ch = _rand("DUP")
    # Two rows for the same (unknown) chassis: the first errors as not-on-record, the
    # second additionally as an in-file duplicate.
    rows = [
        {"date": "2026-03-04", "chassis": _rand("GHOST")},   # not on record
        {"date": "2026-03-04", "chassis": ch},
        {"date": "2026-03-05", "chassis": ch},               # duplicate in file
    ]
    job_id, mapping = await _upload(client, h, _csv(rows))
    p = await _preview(client, h, job_id, mapping)
    assert p["valid_count"] == 0 and p["invalid_count"] == 3
    joined = " ".join(e for row in p["sample_errors"] for e in row["errors"])
    assert "not on record" in joined and "Duplicate chassis" in joined
