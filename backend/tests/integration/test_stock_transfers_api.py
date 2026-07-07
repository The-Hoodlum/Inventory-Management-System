"""Integration tests for the stock-transfer engine over HTTP:

create -> approve (reserve) -> issue (deduct source, in-transit) -> receive (credit
destination, reconcile) -> complete, plus reservation math, partial issue, the
reconciliation invariant, permission boundaries, and the immutable transfer ledger.

Requires a live database (DATABASE_URL) with the RBAC + demo seed; skipped otherwise.
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


async def _headers(client, email, password) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _role_id(client, admin_h, name) -> str:
    r = await client.get("/api/v1/users/roles", headers=admin_h)
    assert r.status_code == 200, r.text
    role = next((x for x in r.json() if x["name"] == name), None)
    assert role, f"system role {name!r} not found — re-seed the database"
    return role["id"]


async def _make_cashier(client, admin_h) -> tuple[str, str]:
    role_id = await _role_id(client, admin_h, "Cashier")
    email = f"cashier-{uuid.uuid4().hex[:8]}@demo.com"
    password = "CashierPass123"
    r = await client.post("/api/v1/users", headers=admin_h, json={
        "email": email, "full_name": "Test Cashier", "password": password, "role_ids": [role_id],
    })
    assert r.status_code == 201, r.text
    return email, password


async def _find_stocked(client, admin_h, min_qty=4.0) -> tuple[str, str]:
    """(product_id, source_warehouse_id) for an inventory row with enough available."""
    r = await client.get("/api/v1/inventory", headers=admin_h, params={"page_size": 200})
    assert r.status_code == 200, r.text
    for row in r.json()["items"]:
        if float(row["qty_available"]) >= min_qty:
            return row["product_id"], row["warehouse_id"]
    pytest.skip("no inventory with enough available stock in the demo data")


async def _other_location(client, admin_h, exclude: str) -> str:
    r = await client.get("/api/v1/warehouses", headers=admin_h, params={"page_size": 200})
    assert r.status_code == 200, r.text
    for w in r.json()["items"]:
        if w["id"] != exclude:
            return w["id"]
    pytest.skip("need at least two locations for a transfer")


async def _inv(client, h, product_id, wh_id) -> dict:
    r = await client.get("/api/v1/inventory", headers=h,
                         params={"product_id": product_id, "warehouse_id": wh_id})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    if not items:
        return {"qty_on_hand": 0.0, "qty_available": 0.0, "qty_reserved": 0.0}
    it = items[0]
    return {k: float(it[k]) for k in ("qty_on_hand", "qty_available", "qty_reserved")}


# ----------------------------- full lifecycle ------------------------------ #
async def test_transfer_reserve_issue_receive_complete(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    product_id, source = await _find_stocked(client, admin_h, min_qty=5)
    dest = await _other_location(client, admin_h, exclude=source)

    src0 = await _inv(client, admin_h, product_id, source)
    dst0 = await _inv(client, admin_h, product_id, dest)

    # create (transfer requires a reason + destination)
    r = await client.post("/api/v1/order-requests", headers=admin_h, json={
        "branch_id": source, "destination_branch_id": dest, "purpose": "branch_transfer",
        "comments": "Replenish destination", "lines": [{"product_id": product_id, "requested_qty": 4}],
    })
    assert r.status_code == 201, r.text
    req = r.json()
    rid, line_id = req["id"], req["lines"][0]["id"]
    assert req["transfer_type"] == "branch_transfer"
    assert req["dest_location_id"] == dest

    # approve -> reserve at source (available drops, on-hand unchanged)
    r = await client.post(f"/api/v1/order-requests/{rid}/approve", headers=admin_h,
                          json={"lines": [{"line_id": line_id, "approved_qty": 4}]})
    assert r.status_code == 200, r.text
    src1 = await _inv(client, admin_h, product_id, source)
    assert src1["qty_on_hand"] == src0["qty_on_hand"]
    assert src1["qty_reserved"] == src0["qty_reserved"] + 4
    assert src1["qty_available"] == src0["qty_available"] - 4

    # issue -> deduct source on-hand, in transit (destination NOT credited yet)
    r = await client.post(f"/api/v1/order-requests/{rid}/issue", headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_transit"
    src2 = await _inv(client, admin_h, product_id, source)
    dst2 = await _inv(client, admin_h, product_id, dest)
    assert src2["qty_on_hand"] == src0["qty_on_hand"] - 4
    assert src2["qty_reserved"] == src0["qty_reserved"]  # hold consumed
    assert dst2["qty_on_hand"] == dst0["qty_on_hand"]    # not credited until receipt

    # receive -> credit destination (all 4 good)
    r = await client.post(f"/api/v1/order-requests/{rid}/receive", headers=admin_h, json={
        "remarks": "All received", "lines": [{"line_id": line_id, "received_qty": 4}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received"
    dst3 = await _inv(client, admin_h, product_id, dest)
    assert dst3["qty_on_hand"] == dst0["qty_on_hand"] + 4

    # complete
    r = await client.post(f"/api/v1/order-requests/{rid}/complete", headers=admin_h,
                          json={"remarks": "Done"})
    assert r.status_code == 200 and r.json()["status"] == "completed"

    # ledger has the full movement trail (immutable, append-only)
    r = await client.get(f"/api/v1/order-requests/{rid}/ledger", headers=admin_h)
    assert r.status_code == 200, r.text
    events = {e["event"] for e in r.json()}
    assert {"reserved", "consumed", "issued", "received"}.issubset(events)


# ----------------------------- partial issue ------------------------------- #
async def test_partial_issue(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    product_id, source = await _find_stocked(client, admin_h, min_qty=4)
    dest = await _other_location(client, admin_h, exclude=source)

    r = await client.post("/api/v1/order-requests", headers=admin_h, json={
        "branch_id": source, "destination_branch_id": dest, "purpose": "internal_transfer",
        "comments": "Partial", "lines": [{"product_id": product_id, "requested_qty": 4}],
    })
    rid, line_id = r.json()["id"], r.json()["lines"][0]["id"]
    await client.post(f"/api/v1/order-requests/{rid}/approve", headers=admin_h,
                      json={"lines": [{"line_id": line_id, "approved_qty": 4}]})

    # issue only 2 of 4 -> partially_issued
    r = await client.post(f"/api/v1/order-requests/{rid}/issue", headers=admin_h,
                          json={"lines": [{"line_id": line_id, "issue_qty": 2}]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "partially_issued"
    assert r.json()["lines"][0]["issued_qty"] == 2

    # issue the rest -> in_transit
    r = await client.post(f"/api/v1/order-requests/{rid}/issue", headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_transit"
    assert r.json()["lines"][0]["issued_qty"] == 4


# --------------------------- reconciliation rules -------------------------- #
async def test_receive_missing_and_damaged_balanced(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    product_id, source = await _find_stocked(client, admin_h, min_qty=10)
    dest = await _other_location(client, admin_h, exclude=source)
    dst0 = await _inv(client, admin_h, product_id, dest)

    r = await client.post("/api/v1/order-requests", headers=admin_h, json={
        "branch_id": source, "destination_branch_id": dest, "purpose": "branch_transfer",
        "comments": "Recon", "lines": [{"product_id": product_id, "requested_qty": 10}],
    })
    rid, line_id = r.json()["id"], r.json()["lines"][0]["id"]
    await client.post(f"/api/v1/order-requests/{rid}/approve", headers=admin_h,
                      json={"lines": [{"line_id": line_id, "approved_qty": 10}]})
    await client.post(f"/api/v1/order-requests/{rid}/issue", headers=admin_h)

    # received 8 + missing 1 + damaged 1 == issued 10 -> VALID
    r = await client.post(f"/api/v1/order-requests/{rid}/receive", headers=admin_h, json={
        "remarks": "1 missing, 1 damaged",
        "lines": [{"line_id": line_id, "received_qty": 8, "missing_qty": 1, "damaged_qty": 1}],
    })
    assert r.status_code == 200, r.text
    line = r.json()["lines"][0]
    assert line["received_qty"] == 8 and line["missing_qty"] == 1 and line["damaged_qty"] == 1
    assert line["balanced"] is True and line["variance"] == 0
    # destination credited the 8 good units only
    dst1 = await _inv(client, admin_h, product_id, dest)
    assert dst1["qty_on_hand"] == dst0["qty_on_hand"] + 8


async def test_invalid_reconciliation_rejected(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    product_id, source = await _find_stocked(client, admin_h, min_qty=5)
    dest = await _other_location(client, admin_h, exclude=source)

    r = await client.post("/api/v1/order-requests", headers=admin_h, json={
        "branch_id": source, "destination_branch_id": dest, "purpose": "branch_transfer",
        "comments": "Bad recon", "lines": [{"product_id": product_id, "requested_qty": 5}],
    })
    rid, line_id = r.json()["id"], r.json()["lines"][0]["id"]
    await client.post(f"/api/v1/order-requests/{rid}/approve", headers=admin_h,
                      json={"lines": [{"line_id": line_id, "approved_qty": 5}]})
    await client.post(f"/api/v1/order-requests/{rid}/issue", headers=admin_h)

    # received 5 + missing 7 != issued 5 -> INVALID
    r = await client.post(f"/api/v1/order-requests/{rid}/receive", headers=admin_h, json={
        "remarks": "does not add up",
        "lines": [{"line_id": line_id, "received_qty": 5, "missing_qty": 7}],
    })
    assert r.status_code == 400, r.text
    assert "reconcile" in r.text.lower()


async def test_extra_over_delivery_balanced(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    product_id, source = await _find_stocked(client, admin_h, min_qty=5)
    dest = await _other_location(client, admin_h, exclude=source)
    dst0 = await _inv(client, admin_h, product_id, dest)

    r = await client.post("/api/v1/order-requests", headers=admin_h, json={
        "branch_id": source, "destination_branch_id": dest, "purpose": "branch_transfer",
        "comments": "Extra", "lines": [{"product_id": product_id, "requested_qty": 5}],
    })
    rid, line_id = r.json()["id"], r.json()["lines"][0]["id"]
    await client.post(f"/api/v1/order-requests/{rid}/approve", headers=admin_h,
                      json={"lines": [{"line_id": line_id, "approved_qty": 5}]})
    await client.post(f"/api/v1/order-requests/{rid}/issue", headers=admin_h)

    # received 7 with extra 2 == issued 5 + extra 2 -> VALID (over-delivery)
    r = await client.post(f"/api/v1/order-requests/{rid}/receive", headers=admin_h, json={
        "remarks": "found 2 extra",
        "lines": [{"line_id": line_id, "received_qty": 7, "extra_qty": 2}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["lines"][0]["balanced"] is True
    dst1 = await _inv(client, admin_h, product_id, dest)
    assert dst1["qty_on_hand"] == dst0["qty_on_hand"] + 7


# ------------------------------ permissions -------------------------------- #
async def test_request_user_cannot_approve_or_issue(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    email, password = await _make_cashier(client, admin_h)
    cashier_h = await _headers(client, email, password)
    product_id, source = await _find_stocked(client, admin_h, min_qty=2)
    dest = await _other_location(client, admin_h, exclude=source)

    # A branch_transfer is a managed move — the admin (stock manager) raises it; the cashier
    # lacks order_request.transfer so cannot create one (verified separately below).
    r = await client.post("/api/v1/order-requests", headers=admin_h, json={
        "source_location_id": source, "destination_location_id": dest, "purpose": "branch_transfer",
        "comments": "Please move", "lines": [{"product_id": product_id, "requested_qty": 1}],
    })
    assert r.status_code == 201, r.text
    rid, line_id = r.json()["id"], r.json()["lines"][0]["id"]

    # A cashier cannot even raise a managed transfer (needs order_request.transfer).
    denied = await client.post("/api/v1/order-requests", headers=cashier_h, json={
        "source_location_id": source, "destination_location_id": dest, "purpose": "branch_transfer",
        "comments": "nope", "lines": [{"product_id": product_id, "requested_qty": 1}],
    })
    assert denied.status_code == 403, denied.text

    # cashier (request user) cannot approve / issue / receive
    for path, body in [
        (f"/api/v1/order-requests/{rid}/approve", {"lines": [{"line_id": line_id, "approved_qty": 1}]}),
        (f"/api/v1/order-requests/{rid}/issue", None),
        (f"/api/v1/order-requests/{rid}/receive", {"remarks": "x", "lines": [{"line_id": line_id, "received_qty": 1}]}),
    ]:
        r = await client.post(path, headers=cashier_h, json=body)
        assert r.status_code == 403, f"{path} -> {r.status_code} {r.text}"


async def test_transfer_requires_reason(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    product_id, source = await _find_stocked(client, admin_h, min_qty=1)
    dest = await _other_location(client, admin_h, exclude=source)

    # no reason (comments) for a transfer -> 422 from the schema validator
    r = await client.post("/api/v1/order-requests", headers=admin_h, json={
        "branch_id": source, "destination_branch_id": dest, "purpose": "branch_transfer",
        "lines": [{"product_id": product_id, "requested_qty": 1}],
    })
    assert r.status_code == 422, r.text
