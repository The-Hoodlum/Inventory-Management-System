"""Integration tests for the atomic stock_replay reconstruction import over HTTP.

Verifies the CRITICAL rule: mixed-TYPE rows (receipt/sale/transfer/adjustment/return) are
merged into ONE timeline and replayed in strict chronological order through the real
inventory core, landing on the expected final stock — with every entry marked
imported_historical. Also: an out-of-order / missing-receipt file is caught by the
negative-stock stop (exact row/timestamp) and nothing is committed; a row that predates the
opening balance is rejected.

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

KEY = "stock_replay"
HEADERS = ["Type", "Timestamp", "Product", "Warehouse", "To Warehouse", "Quantity", "Reason / Reference"]
OPENING_HEADERS = ["Product", "Warehouse", "Branch", "Opening Quantity", "As-of Date"]


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


def _csv(headers: list[str], rows: list[list]) -> bytes:
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for row in rows:
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


async def _warehouse(client, h) -> tuple[str, str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()
    wh = (await client.post("/api/v1/warehouses", headers=h, json={
        "code": _rand("WH"), "name": _rand("WH"), "branch_id": br["id"], "is_active": True})).json()
    return wh["id"], wh["name"], br["name"]


async def _product(client, h) -> tuple[str, str]:
    p = (await client.post("/api/v1/products", headers=h, json={"sku": _rand("SKU"), "name": "Recon item"})).json()
    return p["id"], p["sku"]


async def _run(client, h, key, headers, rows) -> dict:
    files = {"file": ("f.csv", _csv(headers, rows), "text/csv")}
    up = (await client.post(f"/api/v1/imports/{key}/upload", headers=h, files=files)).json()
    body = {"mapping": up["detected_mapping"], "options": {"create_missing_references": False, "value_maps": []}}
    preview = (await client.post(f"/api/v1/imports/{key}/{up['job_id']}/preview", headers=h, json=body)).json()
    confirm = (await client.post(f"/api/v1/imports/{key}/{up['job_id']}/confirm", headers=h, json=body)).json()
    return {"preview": preview, "confirm": confirm}


async def _set_opening(client, h, sku, wh_name, br_name, qty, as_of) -> None:
    res = await _run(client, h, "opening_balances", OPENING_HEADERS,
                     [[sku, wh_name, br_name, str(qty), as_of]])
    assert res["confirm"]["status"] == "completed", res["confirm"]


async def _inv(client, h, wh, product) -> float:
    r = await client.get("/api/v1/inventory", headers=h, params={"warehouse_id": wh, "product_id": product})
    items = r.json()["items"]
    return float(items[0]["qty_on_hand"]) if items else 0.0


async def _movements(client, h, wh, product) -> list[dict]:
    r = await client.get("/api/v1/inventory/movements", headers=h, params={"warehouse_id": wh, "product_id": product})
    return r.json()["items"]


# ------------------------------------------------------------------------- #
async def test_target_listed_and_template_downloads(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.get("/api/v1/imports/targets", headers=h)
    assert any(t["key"] == KEY for t in r.json())
    r = await client.get(f"/api/v1/imports/targets/{KEY}/template", headers=h, params={"level": "basic"})
    assert r.status_code == 200 and b"Timestamp" in r.content


async def test_interleaved_timeline_replays_in_order_to_expected_final_stock(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, wh_name, br_name = await _warehouse(client, h)
    wh2, wh2_name, _br2 = await _warehouse(client, h)
    _pid, sku = await _product(client, h)

    # Opening 20 as of 2026-01-01, then a deliberately out-of-file-order timeline:
    #   01-05 receipt +30  -> 50
    #   01-10 sale    -15   -> 35
    #   01-12 transfer 10 to wh2 -> wh 25 / wh2 10
    #   01-15 adjustment -5 -> 20
    #   01-20 return  +4    -> 24
    await _set_opening(client, h, sku, wh_name, br_name, 20, "2026-01-01")
    rows = [
        ["adjustment", "2026-01-15", sku, wh_name, "", "-5", "stock count"],
        ["sale", "2026-01-10 09:00", sku, wh_name, "", "15", "INV-1"],
        ["return", "2026-01-20", sku, wh_name, "", "4", "CRN-1"],
        ["receipt", "2026-01-05", sku, wh_name, "", "30", "GRN-1"],
        ["transfer", "2026-01-12", sku, wh_name, wh2_name, "10", "TRF-1"],
    ]
    res = await _run(client, h, KEY, HEADERS, rows)
    assert res["preview"]["invalid_count"] == 0 and res["preview"]["can_commit"] is True
    assert res["confirm"]["status"] == "completed" and res["confirm"]["imported_rows"] == 5

    assert await _inv(client, h, wh, _pid) == 24.0     # source lands at 24
    assert await _inv(client, h, wh2, _pid) == 10.0    # destination got the transfer

    # Every replayed entry is flagged historical (opening balance + the 5 movements,
    # transfer writes an out+in pair so the source sees 6 rows).
    movements = await _movements(client, h, wh, _pid)
    assert all(m["imported_historical"] is True for m in movements)
    assert {m["movement_type"] for m in movements} >= {"opening_balance", "receipt", "issue", "adjustment", "transfer_out"}


async def test_missing_receipt_is_caught_by_negative_stock_stop(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, wh_name, br_name = await _warehouse(client, h)
    _pid, sku = await _product(client, h)

    await _set_opening(client, h, sku, wh_name, br_name, 5, "2026-01-01")
    # A sale of 10 while only 5 on hand and the receipt comes AFTER it -> negative mid-replay.
    rows = [
        ["sale", "2026-01-05", sku, wh_name, "", "10", "INV-9"],
        ["receipt", "2026-01-09", sku, wh_name, "", "50", "GRN-9"],
    ]
    res = await _run(client, h, KEY, HEADERS, rows)
    assert res["preview"]["invalid_count"] == 1 and res["preview"]["can_commit"] is False
    assert any("negative" in e.get("errors", [""])[0].lower() for e in res["preview"]["sample_errors"])
    assert res["confirm"]["status"] == "failed" and res["confirm"]["imported_rows"] == 0
    # Nothing replayed: stock stays at the opening 5.
    assert await _inv(client, h, wh, _pid) == 5.0


async def test_row_predating_opening_balance_is_rejected(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, wh_name, br_name = await _warehouse(client, h)
    _pid, sku = await _product(client, h)

    await _set_opening(client, h, sku, wh_name, br_name, 10, "2026-02-01")
    rows = [["receipt", "2026-01-15", sku, wh_name, "", "5", "early"]]  # before opening
    res = await _run(client, h, KEY, HEADERS, rows)
    assert res["preview"]["invalid_count"] == 1 and res["preview"]["can_commit"] is False
    assert any("predates" in e.get("errors", [""])[0].lower() for e in res["preview"]["sample_errors"])
    assert res["confirm"]["status"] == "failed"
