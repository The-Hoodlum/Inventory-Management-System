"""Integration tests for the branch-transfer + internal-issuance import variants.

Both are record-only history matched by chassis: a transfer row becomes a completed
dispatch note (from the unit's branch → the sheet's To Branch); an issuance row becomes a
closed issuance. Neither moves stock or mutates the unit.

Requires a live database; skipped otherwise.
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


def _csv(headers: list[str], rows: list[list]) -> bytes:
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for row in rows:
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


async def _run(client, h, key, headers, rows) -> dict:
    files = {"file": ("f.csv", _csv(headers, rows), "text/csv")}
    up = (await client.post(f"/api/v1/imports/{key}/upload", headers=h, files=files)).json()
    mapping = up["detected_mapping"]
    opts = {"mapping": mapping, "options": {"create_missing_references": False, "value_maps": []}}
    preview = (await client.post(f"/api/v1/imports/{key}/{up['job_id']}/preview", headers=h, json=opts)).json()
    job = (await client.post(f"/api/v1/imports/{key}/{up['job_id']}/confirm", headers=h, json=opts)).json()
    return {"preview": preview, "job": job}


async def _warehouse(client, h) -> tuple[str, str, str]:
    br = (await client.post("/api/v1/branches", headers=h, json={"code": _rand("BR"), "name": _rand("Branch")})).json()
    wh = (await client.post("/api/v1/warehouses", headers=h, json={"code": _rand("WH"), "name": _rand("WH"), "branch_id": br["id"], "is_active": True})).json()["id"]
    return wh, br["id"], br["name"]


async def _unit(client, h, wh, br) -> dict:
    model = (await client.post("/api/v1/motorcycles/models", headers=h, json={"brand": _rand("Br"), "name": _rand("Md")})).json()["id"]
    return (await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "model_id": model, "warehouse_id": wh, "branch_id": br})).json()


# --------------------------------- branch transfer ------------------------- #
async def test_branch_transfer_import(client):
    h = await _headers(client)
    wh_a, br_a, _ = await _warehouse(client, h)
    _wh_b, _br_b, name_b = await _warehouse(client, h)     # destination branch
    unit = await _unit(client, h, wh_a, br_a)

    HEAD = ["Transfer Date", "Chassis Number", "To Branch", "Remarks"]
    res = await _run(client, h, "branch_transfer_notes", HEAD,
                     [["2026-03-04", unit["chassis_number"], name_b, "moved north"]])
    assert res["preview"]["valid_count"] == 1 and res["preview"]["invalid_count"] == 0
    assert res["job"]["status"] == "completed" and res["job"]["imported_rows"] == 1

    notes = (await client.get("/api/v1/delivery-notes", headers=h, params={"limit": 500})).json()
    mine = [n for n in notes if any(ln.get("chassis_number") == unit["chassis_number"] for ln in n["lines"])]
    assert len(mine) == 1
    n = mine[0]
    assert n["status"] == "received" and n["to_branch_name"] == name_b

    # unknown chassis + unknown destination both error.
    bad = await _run(client, h, "branch_transfer_notes", HEAD,
                     [["2026-03-04", _rand("GHOST"), name_b, ""],
                      ["2026-03-04", unit["chassis_number"], "No Such Branch Zz", ""]])
    assert bad["preview"]["valid_count"] == 0 and bad["preview"]["invalid_count"] == 2


# --------------------------------- internal issuance ----------------------- #
async def test_internal_issuance_import(client):
    h = await _headers(client)
    wh, br, _ = await _warehouse(client, h)
    unit = await _unit(client, h, wh, br)

    HEAD = ["Issue Date", "Chassis Number", "Requestor", "Department", "Purpose", "Remarks"]
    res = await _run(client, h, "internal_issuance_notes", HEAD,
                     [["2026-03-04", unit["chassis_number"], "James Banda", "Workshop", "PDI", "test ride"]])
    assert res["preview"]["valid_count"] == 1 and res["preview"]["invalid_count"] == 0
    assert res["job"]["status"] == "completed" and res["job"]["imported_rows"] == 1

    isss = (await client.get("/api/v1/issuances", headers=h, params={"limit": 500})).json()
    mine = [i for i in isss if any(ln.get("chassis_number") == unit["chassis_number"] for ln in i["lines"])]
    assert len(mine) == 1
    i = mine[0]
    assert i["status"] == "returned" and i["requestor"] == "James Banda" and i["department"] == "Workshop"

    # the bike stays sellable — a closed historical issuance doesn't hold it.
    u = (await client.get(f"/api/v1/motorcycles/units/{unit['id']}", headers=h)).json()
    assert "sold" in u["allowed_next"] or u["status"] in ("assembled", "unassembled")

    # missing requestor errors.
    bad = await _run(client, h, "internal_issuance_notes", HEAD,
                     [["2026-03-04", unit["chassis_number"], "", "Workshop", "", ""]])
    assert bad["preview"]["invalid_count"] == 1
    assert any("requestor" in e.lower() for row in bad["preview"]["sample_errors"] for e in row["errors"])
