"""Bike stock reorder points: which model/colours are running out.

The reorder engine covers parts only, so nothing previously flagged a motorcycle colour
running low. These tests cover the threshold resolution (colour-specific beats the
model-wide default; unconfigured models stay silent) and, critically, that a combo which
just sold its LAST unit is still reported at zero.

Requires a live database (DATABASE_URL); skipped otherwise.
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


async def _model(client, h) -> str:
    return (await client.post("/api/v1/motorcycles/models", headers=h,
            json={"name": _rand("Model"), "brand": "TVS"})).json()["id"]


async def _colour(client, h) -> tuple[str, str]:
    name = _rand("Colour")
    r = await client.post("/api/v1/motorcycles/colours", headers=h, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"], name


async def _unit(client, h, *, model_id, colour_id, branch_id) -> dict:
    r = await client.post("/api/v1/motorcycles/units", headers=h, json={
        "chassis_number": _rand("CH"), "engine_number": _rand("EN"),
        "model_id": model_id, "colour_id": colour_id, "branch_id": branch_id,
        "selling_price": 15000})
    assert r.status_code == 201, r.text
    return r.json()


async def _branch(client, h) -> str:
    return (await client.post("/api/v1/branches", headers=h,
            json={"code": _rand("BR"), "name": _rand("Branch")})).json()["id"]


async def _low_for(client, h, branch_id) -> list[dict]:
    r = await client.get("/api/v1/motorcycles/low-stock", headers=h, params={"branch_id": branch_id})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------- #
async def test_unconfigured_models_are_never_reported(client):
    """Thresholds are opt-in — a tenant that configures nothing gets no noise."""
    h = await _headers(client)
    branch, model = await _branch(client, h), None
    model = await _model(client, h)
    colour_id, _ = await _colour(client, h)
    await _unit(client, h, model_id=model, colour_id=colour_id, branch_id=branch)

    assert await _low_for(client, h, branch) == []


async def test_colour_below_its_reorder_point_is_reported(client):
    h = await _headers(client)
    branch = await _branch(client, h)
    model = await _model(client, h)
    colour_id, colour_name = await _colour(client, h)
    await _unit(client, h, model_id=model, colour_id=colour_id, branch_id=branch)  # 1 sellable

    # Threshold of 3 -> 1 available is low.
    r = await client.put("/api/v1/motorcycles/reorder-points", headers=h, json={
        "model_id": model, "colour_id": colour_id, "reorder_point": 3})
    assert r.status_code == 200, r.text

    low = await _low_for(client, h, branch)
    assert len(low) == 1
    assert low[0]["colour"] == colour_name and low[0]["available"] == 1
    assert low[0]["reorder_point"] == 3


async def test_colour_rule_beats_the_model_wide_default(client):
    h = await _headers(client)
    branch = await _branch(client, h)
    model = await _model(client, h)
    colour_id, _ = await _colour(client, h)
    await _unit(client, h, model_id=model, colour_id=colour_id, branch_id=branch)  # 1 sellable

    # Model-wide default says 5 (so 1 is low)...
    await client.put("/api/v1/motorcycles/reorder-points", headers=h, json={
        "model_id": model, "reorder_point": 5})
    assert len(await _low_for(client, h, branch)) == 1
    # ...but a colour-specific 0 overrides it, so this colour is no longer low.
    await client.put("/api/v1/motorcycles/reorder-points", headers=h, json={
        "model_id": model, "colour_id": colour_id, "reorder_point": 0})
    assert await _low_for(client, h, branch) == []


async def test_selling_the_last_unit_reports_out_of_stock(client):
    """The case that matters most: a colour that sells out must still be reported at 0.
    Grouping only on sellable units would make the row vanish entirely."""
    h = await _headers(client)
    flags = dict((await client.get("/api/v1/tenant/settings", headers=h)).json().get("feature_flags", {}))
    flags.update({"sales_orders": True, "pos": True})
    await client.put("/api/v1/tenant/settings", headers=h, json={"feature_flags": flags, "vat_rate": "0"})

    branch = await _branch(client, h)
    model = await _model(client, h)
    colour_id, _ = await _colour(client, h)
    unit = await _unit(client, h, model_id=model, colour_id=colour_id, branch_id=branch)
    await client.put("/api/v1/motorcycles/reorder-points", headers=h, json={
        "model_id": model, "colour_id": colour_id, "reorder_point": 1})

    # Sell the only one.
    r = await client.post("/api/v1/sales/bike-sale", headers=h, json={
        "unit_id": unit["id"], "branch_id": branch, "price": 15000})
    assert r.status_code == 201, r.text

    low = await _low_for(client, h, branch)
    assert len(low) == 1 and low[0]["available"] == 0


async def test_deleting_the_reorder_point_stops_monitoring(client):
    h = await _headers(client)
    branch = await _branch(client, h)
    model = await _model(client, h)
    colour_id, _ = await _colour(client, h)
    await _unit(client, h, model_id=model, colour_id=colour_id, branch_id=branch)
    rp = (await client.put("/api/v1/motorcycles/reorder-points", headers=h, json={
        "model_id": model, "colour_id": colour_id, "reorder_point": 3})).json()
    assert len(await _low_for(client, h, branch)) == 1

    assert (await client.delete(f"/api/v1/motorcycles/reorder-points/{rp['id']}", headers=h)).status_code == 204
    assert await _low_for(client, h, branch) == []
