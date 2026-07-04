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
    "Date Received", "Branch", "Status", "Hold Reason", "Customer Name", "Customer Phone",
    "Date Sold", "Registered", "Registration Number", "Unit Price", "Charged Price", "Supplier",
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
        "Hold Reason": "hold_reason",
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


def _opts(create_missing, value_maps):
    return {"create_missing_references": create_missing, "value_maps": value_maps or []}


async def _preview(client, admin_h, job_id, mapping, *, create_missing=False, value_maps=None):
    r = await client.post(f"/api/v1/imports/{KEY}/{job_id}/preview", headers=admin_h,
                          json={"mapping": mapping, "options": _opts(create_missing, value_maps)})
    assert r.status_code == 200, r.text
    return r.json()


async def _confirm(client, admin_h, job_id, mapping, *, create_missing=False, value_maps=None):
    r = await client.post(f"/api/v1/imports/{KEY}/{job_id}/confirm", headers=admin_h,
                          json={"mapping": mapping, "options": _opts(create_missing, value_maps)})
    assert r.status_code == 200, r.text
    return r.json()


async def _create_model(client, admin_h, name: str) -> None:
    r = await client.post("/api/v1/motorcycles/models", headers=admin_h,
                          json={"brand": _rand("Brand"), "name": name})
    assert r.status_code == 201, r.text


async def _unit_by_chassis(client, admin_h, chassis: str) -> dict:
    r = await client.get("/api/v1/motorcycles/units", headers=admin_h, params={"search": chassis})
    items = r.json()["items"]
    assert len(items) == 1, f"expected exactly one unit for {chassis}"
    return (await client.get(f"/api/v1/motorcycles/units/{items[0]['id']}", headers=admin_h)).json()


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
    assert u["registered"] is True and u["inspected"] is True  # sold historical -> inspected
    assert u["model_name"] == model  # the new model was created + linked (this row carried no colour)

    # Re-importing a chassis that now exists is rejected (DB uniqueness).
    job_id2, mapping2 = await _upload(client, admin_h, _csv([rows[1]]))
    p2 = await _preview(client, admin_h, job_id2, mapping2, create_missing=True)
    assert p2["invalid_count"] == 1
    assert any("already exists" in e for row in p2["sample_errors"] for e in row["errors"])


# ------------------------------------------------------------------------- #
# Value mapping: a typo status/model maps to an existing value (not created),
# a batch suffix splits into the consignment, and reserved-without-customer
# still errors. After mapping, a previously-erroring file imports clean.
# ------------------------------------------------------------------------- #
async def test_reserved_without_customer_still_errors(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    branch = await _a_branch(client, admin_h)
    base = _rand("HLX")
    await _create_model(client, admin_h, base)
    job_id, mapping = await _upload(client, admin_h, _csv([
        {"chassis": _rand("CHRES"), "model": base, "branch": branch, "status": "reserved"},  # no customer
    ]))
    p = await _preview(client, admin_h, job_id, mapping)
    assert p["invalid_count"] == 1
    assert any("Customer" in e for row in p["sample_errors"] for e in row["errors"])


async def test_mapping_resolves_status_and_model_splits_consignment_imports_clean(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    branch = await _a_branch(client, admin_h)
    base = _rand("HLX")                    # e.g. "HLX-1a2b3c4d" (an existing model)
    typo = base.replace("-", "")            # same model, written without the dash
    await _create_model(client, admin_h, base)

    ch_status, ch_typo = _rand("CHST"), _rand("CHTY")
    ch_cons, ch_hold = _rand("CHCO"), _rand("CHHO")
    rows = [
        {"chassis": ch_status, "model": base, "branch": branch, "status": "Assembly Required"},
        {"chassis": ch_typo, "model": typo, "branch": branch, "status": "assembled"},
        {"chassis": ch_cons, "model": f"{base} CONGO", "branch": branch, "status": "assembled"},
        {"chassis": ch_hold, "model": base, "branch": branch, "status": "on_hold",
         "hold_reason": "Cracked frame"},
    ]
    job_id, mapping = await _upload(client, admin_h, _csv(rows))

    # Preview WITHOUT mappings: the unknown status errors; the values surface for mapping,
    # incl. a split suggestion for "<base> CONGO".
    p = await _preview(client, admin_h, job_id, mapping)
    assert p["invalid_count"] >= 1
    res = {(v["kind"], v["value"]) for v in p["value_resolutions"]}
    assert ("status", "Assembly Required") in res
    split = next(v for v in p["value_resolutions"] if v["kind"] == "model" and v["value"] == f"{base} CONGO")
    assert split["suggestion"] == base and split["suggested_consignment"] == "CONGO"

    # Provide the mappings: status -> unassembled, typo -> existing base, "<base> CONGO"
    # -> base + consignment CONGO. All map to EXISTING values, so nothing is created.
    value_maps = [
        {"kind": "status", "value": "Assembly Required", "action": "map", "target": "unassembled"},
        {"kind": "model", "value": typo, "action": "map", "target": base},
        {"kind": "model", "value": f"{base} CONGO", "action": "map", "target": base, "consignment": "CONGO"},
    ]
    p2 = await _preview(client, admin_h, job_id, mapping, value_maps=value_maps)
    assert p2["invalid_count"] == 0 and p2["can_commit"] is True
    assert p2["new_references"] == []  # mapped to existing — nothing new to create

    job = await _confirm(client, admin_h, job_id, mapping, value_maps=value_maps)
    assert job["status"] == "completed" and job["imported_rows"] == 4

    # The status typo mapped to unassembled.
    assert (await _unit_by_chassis(client, admin_h, ch_status))["status"] == "unassembled"
    # The model typo linked to the existing base model (not a duplicate).
    assert (await _unit_by_chassis(client, admin_h, ch_typo))["model_name"] == base
    # The batch token split into the consignment; the model is the base.
    u_cons = await _unit_by_chassis(client, admin_h, ch_cons)
    assert u_cons["model_name"] == base and u_cons["container_ref"] == "CONGO"
    # on_hold imported with its reason and no customer.
    u_hold = await _unit_by_chassis(client, admin_h, ch_hold)
    assert u_hold["status"] == "on_hold" and u_hold["hold_reason"] == "Cracked frame"
    assert u_hold["customer_name"] is None

    # Exactly one model named `base` exists — the typo/split did NOT duplicate it.
    r = await client.get("/api/v1/motorcycles/models", headers=admin_h, params={"search": base})
    assert sum(1 for m in r.json()["items"] if m["name"] == base) == 1
