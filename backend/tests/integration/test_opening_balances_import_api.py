"""Integration tests for the atomic opening_balances reconstruction import over HTTP:

upload -> preview -> confirm, then verify that opening stock was set through the inventory
CORE as a back-dated, historical ``opening_balance`` ledger entry (never a raw write), and
that an unmatched product/warehouse fails the WHOLE batch (nothing written, no auto-create).

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

KEY = "opening_balances"
HEADERS = ["Product", "Warehouse", "Branch", "Opening Quantity", "As-of Date"]


@pytest_asyncio.fixture
async def client():
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _headers(client, email, password) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _rand(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _csv(rows: list[dict]) -> bytes:
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADERS)
    key = {"Product": "product", "Warehouse": "warehouse", "Branch": "branch",
           "Opening Quantity": "qty", "As-of Date": "as_of"}
    for row in rows:
        w.writerow([row.get(key[h], "") for h in HEADERS])
    return buf.getvalue().encode("utf-8")


async def _warehouse(client, h) -> tuple[str, str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()
    wh = (await client.post("/api/v1/warehouses", headers=h, json={
        "code": _rand("WH"), "name": _rand("WH"), "branch_id": br["id"], "is_active": True})).json()
    return wh["id"], wh["name"], br["name"]


async def _product(client, h) -> tuple[str, str]:
    p = (await client.post("/api/v1/products", headers=h, json={"sku": _rand("SKU"), "name": "Recon item"})).json()
    return p["id"], p["sku"]


async def _upload(client, h, data: bytes) -> tuple[str, dict]:
    files = {"file": ("opening.csv", data, "text/csv")}
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


async def _inv(client, h, wh, product) -> dict:
    r = await client.get("/api/v1/inventory", headers=h, params={"warehouse_id": wh, "product_id": product})
    items = r.json()["items"]
    if not items:
        return {"on_hand": 0.0}
    return {"on_hand": float(items[0]["qty_on_hand"])}


async def _movements(client, h, wh, product) -> list[dict]:
    r = await client.get("/api/v1/inventory/movements", headers=h, params={"warehouse_id": wh, "product_id": product})
    return r.json()["items"]


# ------------------------------------------------------------------------- #
async def test_target_listed_and_template_downloads(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.get("/api/v1/imports/targets", headers=h)
    assert any(t["key"] == KEY for t in r.json())
    r = await client.get(f"/api/v1/imports/targets/{KEY}/template", headers=h, params={"level": "basic"})
    assert r.status_code == 200 and b"Opening Quantity" in r.content


async def test_opening_balance_sets_stock_as_of_date_via_core(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, wh_name, br_name = await _warehouse(client, h)
    _pid, sku = await _product(client, h)
    assert (await _inv(client, h, wh, _pid))["on_hand"] == 0.0

    csv = _csv([{"product": sku, "warehouse": wh_name, "branch": br_name, "qty": "40", "as_of": "2026-01-01"}])
    job_id, mapping = await _upload(client, h, csv)
    p = await _preview(client, h, job_id, mapping)
    assert p["valid_count"] == 1 and p["invalid_count"] == 0 and p["can_commit"] is True
    job = await _confirm(client, h, job_id, mapping)
    assert job["status"] == "completed" and job["imported_rows"] == 1

    # Stock set through the core.
    assert (await _inv(client, h, wh, _pid))["on_hand"] == 40.0
    # Exactly one ledger entry: a back-dated, historical opening_balance.
    movements = await _movements(client, h, wh, _pid)
    assert len(movements) == 1
    mv = movements[0]
    assert mv["movement_type"] == "opening_balance"
    assert mv["imported_historical"] is True
    assert float(mv["quantity"]) == 40.0
    assert mv["occurred_at"] is not None and mv["occurred_at"].startswith("2026-01-01")


async def test_unmatched_product_fails_whole_batch_no_autocreate(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, wh_name, br_name = await _warehouse(client, h)
    _pid, sku = await _product(client, h)

    # Row 1 is valid; row 2 references a product that does not exist -> whole batch fails.
    csv = _csv([
        {"product": sku, "warehouse": wh_name, "branch": br_name, "qty": "10", "as_of": "2026-01-01"},
        {"product": "NO-SUCH-SKU-XYZ", "warehouse": wh_name, "qty": "5", "as_of": "2026-01-01"},
    ])
    job_id, mapping = await _upload(client, h, csv)
    p = await _preview(client, h, job_id, mapping)
    assert p["invalid_count"] == 1 and p["can_commit"] is False
    assert any("not found" in e.get("errors", [""])[0].lower() for e in p["sample_errors"])

    job = await _confirm(client, h, job_id, mapping)
    assert job["status"] == "failed" and job["imported_rows"] == 0
    # All-or-nothing: the valid row 1 was NOT written either.
    assert (await _inv(client, h, wh, _pid))["on_hand"] == 0.0
