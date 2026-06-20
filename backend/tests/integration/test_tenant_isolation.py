"""Cross-tenant RLS isolation — the multi-tenant security cornerstone.

Two seeded tenants (demo / globex) must never see each other's data over the API.
This proves PostgreSQL Row-Level Security is enforced end to end: the app connects
as the non-superuser ``app_user`` and sets the tenant GUC transaction-locally per
request, so every business query is scoped to the caller's tenant.

Requires the demo seed (both tenants) and a live database; skipped otherwise.
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

TENANT_A = (
    os.getenv("DEMO_ADMIN_EMAIL", "admin@demo.com"),
    os.getenv("DEMO_ADMIN_PASSWORD", "ChangeMe123!"),
)
TENANT_B = ("admin@globex.com", "ChangeMe123!")
B_ONLY_SKU = "GX-WIDGET-001"  # exists only in the globex tenant


@pytest_asyncio.fixture
async def client():
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _login(client, email: str, password: str) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _all_skus(client, headers) -> list[str]:
    skus: list[str] = []
    page = 1
    while True:
        r = await client.get(
            "/api/v1/products", headers=headers, params={"page": page, "page_size": 100}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        skus += [p["sku"] for p in body["items"]]
        if not body["items"] or page >= (body.get("total_pages") or 1):
            break
        page += 1
    return skus


async def test_tenants_have_disjoint_catalogs(client):
    a_skus = set(await _all_skus(client, await _login(client, *TENANT_A)))
    b_skus = set(await _all_skus(client, await _login(client, *TENANT_B)))

    assert a_skus, "tenant A (demo) should have seeded products"
    assert B_ONLY_SKU in b_skus            # B sees its own product
    assert B_ONLY_SKU not in a_skus        # A cannot see B's product
    assert a_skus.isdisjoint(b_skus)       # catalogs do not overlap at all


async def test_cross_tenant_fetch_by_id_is_404(client):
    # A reads one of its own product ids...
    a = await _login(client, *TENANT_A)
    r = await client.get("/api/v1/products", headers=a, params={"page_size": 1})
    assert r.status_code == 200 and r.json()["items"], r.text
    a_product_id = r.json()["items"][0]["id"]

    # ...and B must not be able to fetch it: RLS hides the row, so it is 404 (not 403).
    b = await _login(client, *TENANT_B)
    r = await client.get(f"/api/v1/products/{a_product_id}", headers=b)
    assert r.status_code == 404, r.text


async def test_unknown_product_id_is_404_within_tenant(client):
    # Sanity: a genuinely missing id is 404 too, so the cross-tenant 404 above is
    # the RLS boundary behaving like "does not exist", not a different error path.
    a = await _login(client, *TENANT_A)
    r = await client.get(f"/api/v1/products/{uuid.uuid4()}", headers=a)
    assert r.status_code == 404, r.text
