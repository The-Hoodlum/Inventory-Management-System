"""Integration tests for the reconciliation GATE over HTTP.

Verifies the whole point of a reconstruction: after opening + replay, the system's computed
stock is compared to the user's actual physical count; the preview reports computed vs actual
+ delta; a clean run (deltas all zero) commits a no-op; a run WITH deltas is BLOCKED until the
user accepts, and accepting posts correcting adjustments so the system matches reality.

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

KEY = "stock_reconciliation"
HEADERS = ["Product", "Warehouse", "Branch", "Actual Count"]
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


async def _upload(client, h, key, headers, rows) -> tuple[str, dict]:
    files = {"file": ("f.csv", _csv(headers, rows), "text/csv")}
    up = (await client.post(f"/api/v1/imports/{key}/upload", headers=h, files=files)).json()
    return up["job_id"], up["detected_mapping"]


async def _preview(client, h, key, job_id, mapping, *, accept_deltas=False):
    body = {"mapping": mapping, "options": {"accept_deltas": accept_deltas, "value_maps": []}}
    r = await client.post(f"/api/v1/imports/{key}/{job_id}/preview", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def _confirm(client, h, key, job_id, mapping, *, accept_deltas=False):
    body = {"mapping": mapping, "options": {"accept_deltas": accept_deltas, "value_maps": []}}
    r = await client.post(f"/api/v1/imports/{key}/{job_id}/confirm", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def _set_opening(client, h, sku, wh_name, br_name, qty) -> None:
    job_id, mapping = await _upload(client, h, "opening_balances", OPENING_HEADERS,
                                    [[sku, wh_name, br_name, str(qty), "2026-01-01"]])
    body = {"mapping": mapping, "options": {"create_missing_references": False, "value_maps": []}}
    r = await client.post(f"/api/v1/imports/opening_balances/{job_id}/confirm", headers=h, json=body)
    assert r.json()["status"] == "completed", r.json()


async def _inv(client, h, wh, product) -> float:
    r = await client.get("/api/v1/inventory", headers=h, params={"warehouse_id": wh, "product_id": product})
    items = r.json()["items"]
    return float(items[0]["qty_on_hand"]) if items else 0.0


# ------------------------------------------------------------------------- #
async def test_clean_run_reports_zero_deltas_and_commits_a_noop(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, wh_name, br_name = await _warehouse(client, h)
    pid, sku = await _product(client, h)
    await _set_opening(client, h, sku, wh_name, br_name, 30)  # system now 30

    job_id, mapping = await _upload(client, h, KEY, HEADERS, [[sku, wh_name, br_name, "30"]])
    p = await _preview(client, h, KEY, job_id, mapping)
    assert p["has_deltas"] is False and p["can_commit"] is True
    line = p["reconciliation"][0]
    assert float(line["computed"]) == 30.0 and float(line["actual"]) == 30.0 and float(line["delta"]) == 0.0

    job = await _confirm(client, h, KEY, job_id, mapping)
    assert job["status"] == "completed" and job["imported_rows"] == 0  # nothing to adjust
    assert await _inv(client, h, wh, pid) == 30.0


async def test_delta_blocks_commit_until_accepted_then_posts_adjustment(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    wh, wh_name, br_name = await _warehouse(client, h)
    pid, sku = await _product(client, h)
    await _set_opening(client, h, sku, wh_name, br_name, 30)  # system computes 30

    # Actual count is 27 -> delta -3. Preview surfaces it and refuses commit.
    job_id, mapping = await _upload(client, h, KEY, HEADERS, [[sku, wh_name, br_name, "27"]])
    p = await _preview(client, h, KEY, job_id, mapping)
    assert p["has_deltas"] is True and p["can_commit"] is False
    line = p["reconciliation"][0]
    assert float(line["computed"]) == 30.0 and float(line["actual"]) == 27.0 and float(line["delta"]) == -3.0

    # Confirm WITHOUT accepting -> blocked, nothing written (still 30).
    blocked = await _confirm(client, h, KEY, job_id, mapping)
    assert blocked["status"] == "failed" and blocked["imported_rows"] == 0
    assert await _inv(client, h, wh, pid) == 30.0

    # Accept deltas (a fresh job — a failed job is terminal): a correcting adjustment brings
    # the system to the counted 27.
    job2, mapping2 = await _upload(client, h, KEY, HEADERS, [[sku, wh_name, br_name, "27"]])
    p2 = await _preview(client, h, KEY, job2, mapping2, accept_deltas=True)
    assert p2["has_deltas"] is True and p2["can_commit"] is True
    job = await _confirm(client, h, KEY, job2, mapping2, accept_deltas=True)
    assert job["status"] == "completed" and job["imported_rows"] == 1
    assert await _inv(client, h, wh, pid) == 27.0


async def test_unmatched_product_is_a_row_error(client):
    h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    _wh, wh_name, _br = await _warehouse(client, h)
    job_id, mapping = await _upload(client, h, KEY, HEADERS, [["NO-SUCH-SKU", wh_name, "", "5"]])
    p = await _preview(client, h, KEY, job_id, mapping)
    assert p["invalid_count"] == 1 and p["can_commit"] is False
    assert any("not found" in e.get("errors", [""])[0].lower() for e in p["sample_errors"])
