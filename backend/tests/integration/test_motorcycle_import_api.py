"""Integration tests for the atomic motorcycle-units bulk import over HTTP:

upload -> preview (rows ok / rows with errors / new reference values awaiting confirm)
-> confirm (all-or-nothing; new references only created when confirmed) -> summary.

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

KEY = "motorcycle_units"
HEADERS = [
    "Chassis Number", "Engine Number", "Model", "Make / Brand", "Variant", "Colour",
    "Date Received", "Branch", "Status", "Customer Name", "Customer Phone", "Date Sold",
    "Registered", "Registration Number", "Unit Price", "Charged Price", "Supplier",
]


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


async def _a_branch(client, admin_h) -> str:
    r = await client.get("/api/v1/branches", headers=admin_h, params={"page_size": 1})
    items = r.json()["items"]
    if items:
        return items[0]["name"]
    r = await client.post("/api/v1/branches", headers=admin_h, json={"code": _rand("BR"), "name": _rand("Branch")})
    return r.json()["name"]


def _csv(rows: list[dict]) -> bytes:
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADERS)
    key_by_label = {  # header label -> row dict key
        "Chassis Number": "chassis", "Engine Number": "engine", "Model": "model",
        "Make / Brand": "make", "Variant": "variant", "Colour": "colour",
        "Date Received": "date_received", "Branch": "branch", "Status": "status",
        "Customer Name": "customer", "Customer Phone": "phone", "Date Sold": "date_sold",
        "Registered": "registered", "Registration Number": "reg_no", "Unit Price": "unit_price",
        "Charged Price": "charged", "Supplier": "supplier",
    }
    for row in rows:
        w.writerow([row.get(key_by_label[h], "") for h in HEADERS])
    return buf.getvalue().encode("utf-8")


async def _upload(client, admin_h, data: bytes) -> tuple[str, dict]:
    files = {"file": ("units.csv", data, "text/csv")}
    r = await client.post(f"/api/v1/imports/{KEY}/upload", headers=admin_h, files=files)
    assert r.status_code == 200, r.text
    j = r.json()
    return j["job_id"], j["detected_mapping"]


async def _preview(client, admin_h, job_id, mapping, *, create_missing=False):
    r = await client.post(f"/api/v1/imports/{KEY}/{job_id}/preview", headers=admin_h,
                          json={"mapping": mapping, "options": {"create_missing_references": create_missing}})
    assert r.status_code == 200, r.text
    return r.json()


async def _confirm(client, admin_h, job_id, mapping, *, create_missing=False):
    r = await client.post(f"/api/v1/imports/{KEY}/{job_id}/confirm", headers=admin_h,
                          json={"mapping": mapping, "options": {"create_missing_references": create_missing}})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------- #
# The target is registered and templated.
# ------------------------------------------------------------------------- #
async def test_target_listed_and_template_downloads(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.get("/api/v1/imports/targets", headers=admin_h)
    assert any(t["key"] == KEY for t in r.json())
    r = await client.get(f"/api/v1/imports/targets/{KEY}/template", headers=admin_h, params={"level": "standard"})
    assert r.status_code == 200 and b"Chassis Number" in r.content


# ------------------------------------------------------------------------- #
# Preview buckets rows: ok / errors / new references. Confirm with errors is
# all-or-nothing: nothing is written.
# ------------------------------------------------------------------------- #
async def test_preview_reports_errors_new_refs_and_confirm_is_all_or_nothing(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    branch = await _a_branch(client, admin_h)
    model = _rand("ModelX")
    colour = _rand("Galaxy")
    dupe = _rand("CHDUP")
    rows = [
        {"chassis": _rand("CHOK"), "model": model, "colour": colour, "branch": branch, "status": "unassembled"},
        {"chassis": _rand("CHSOLD"), "model": model, "branch": branch, "status": "sold",
         "customer": "Buyer One", "date_sold": "2026-01-05", "charged": "5000"},
        {"chassis": _rand("CHBAD"), "model": model, "branch": "No Such Branch Xyz", "status": "assembled"},
        {"chassis": _rand("CHSOLD2"), "model": model, "branch": branch, "status": "sold"},  # missing customer + date_sold
        {"chassis": dupe, "model": model, "branch": branch, "status": "assembled"},
        {"chassis": dupe, "model": model, "branch": branch, "status": "assembled"},  # dup in file
        {"chassis": _rand("CHCONS"), "model": model, "branch": branch, "status": "assembled",
         "date_sold": "2026-01-01"},  # non-sold carrying a sold-only field
    ]
    job_id, mapping = await _upload(client, admin_h, _csv(rows))

    p = await _preview(client, admin_h, job_id, mapping)
    assert p["atomic"] is True
    # ok: A, B, and the FIRST dup occurrence = 3; errors: bad branch, sold-missing-fields,
    # the SECOND dup, and the non-sold-with-sold-field = 4.
    assert p["valid_count"] == 3 and p["invalid_count"] == 4
    kinds = {(n["kind"], n["value"].lower()) for n in p["new_references"]}
    assert ("model", model.lower()) in kinds and ("colour", colour.lower()) in kinds
    assert p["can_commit"] is False  # errors present

    # Confirm with errors -> whole batch fails, nothing created.
    job = await _confirm(client, admin_h, job_id, mapping, create_missing=True)
    assert job["status"] == "failed" and job["imported_rows"] == 0
    r = await client.get("/api/v1/motorcycles/units", headers=admin_h, params={"search": model, "page_size": 5})
    assert r.json()["total"] == 0  # the new model was never even created


# ------------------------------------------------------------------------- #
# A clean batch needs reference confirmation, then commits atomically; sold rows
# become historical; a re-import of a committed chassis is rejected.
# ------------------------------------------------------------------------- #
async def test_clean_batch_confirms_refs_commits_and_dedupes_against_db(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    branch = await _a_branch(client, admin_h)
    model = _rand("ModelZ")
    ch_sold = _rand("CHZH")
    rows = [
        {"chassis": _rand("CHZG"), "model": model, "make": "TVS", "variant": "Deluxe",
         "colour": _rand("Ocean"), "supplier": _rand("ImpSup"), "branch": branch, "status": "unassembled"},
        {"chassis": ch_sold, "model": model, "branch": branch, "status": "sold",
         "customer": "Buyer Two", "phone": "099000111", "date_sold": "2026-02-10",
         "charged": "5200", "registered": "yes", "reg_no": _rand("REG")},
        {"chassis": _rand("CHZI"), "model": model, "branch": branch, "status": "reserved",
         "customer": "Buyer Three"},
    ]
    job_id, mapping = await _upload(client, admin_h, _csv(rows))

    p = await _preview(client, admin_h, job_id, mapping)
    assert p["invalid_count"] == 0 and p["valid_count"] == 3
    assert p["can_commit"] is False  # new refs need confirmation
    values = {n["value"].lower() for n in p["new_references"]}
    assert model.lower() in values and f"{model} / deluxe".lower() in values

    # Confirm WITHOUT authorizing new references -> blocked, nothing written.
    job = await _confirm(client, admin_h, job_id, mapping, create_missing=False)
    assert job["status"] == "failed" and job["imported_rows"] == 0

    # Re-upload (the job is single-use) and confirm WITH creation -> all committed.
    job_id, mapping = await _upload(client, admin_h, _csv(rows))
    job = await _confirm(client, admin_h, job_id, mapping, create_missing=True)
    assert job["status"] == "completed" and job["imported_rows"] == 3

    # The sold unit is historical: linked to no invoice, price + date set, flagged.
    r = await client.get("/api/v1/motorcycles/units", headers=admin_h, params={"search": ch_sold})
    items = r.json()["items"]
    assert len(items) == 1
    unit_id = items[0]["id"]
    u = (await client.get(f"/api/v1/motorcycles/units/{unit_id}", headers=admin_h)).json()
    assert u["status"] == "sold" and u["imported_historical"] is True
    assert u["sold_ref"] is None and u["sold_invoice_number"] is None  # no fabricated sales doc
    assert u["customer_name"] and u["price_charged"] == 5200 and u["date_sold"] == "2026-02-10"
    assert u["registration_status"] == "registered"
    assert u["model_name"] == model  # the new model was created + linked (this row carried no colour)

    # Re-importing a chassis that now exists is rejected (DB uniqueness).
    job_id2, mapping2 = await _upload(client, admin_h, _csv([rows[1]]))
    p2 = await _preview(client, admin_h, job_id2, mapping2, create_missing=True)
    assert p2["invalid_count"] == 1
    assert any("already exists" in e for row in p2["sample_errors"] for e in row["errors"])
