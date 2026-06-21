"""Integration tests for the assistant HTTP surface.

The LLM is inert by default (ASSISTANT_ENABLED=false), so these assert the wiring
that must hold regardless of the model: authentication, the ``assistant.use``
permission gate, structured responses, conversation logging, and the mock WhatsApp
phone->user path. The live OpenAI tool-loop is covered by unit tests.

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


async def _make_user(client, admin_h, role_ids, password) -> str:
    email = f"noperm-{uuid.uuid4().hex[:8]}@demo.com"
    r = await client.post(
        "/api/v1/users",
        headers=admin_h,
        json={"email": email, "full_name": "No Perm", "password": password, "role_ids": role_ids},
    )
    assert r.status_code == 201, r.text
    return email


async def test_ask_requires_authentication(client):
    r = await client.post("/api/v1/assistant/ask", json={"question": "hi"})
    assert r.status_code in (401, 403), r.text


async def test_ask_is_permission_gated(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    # A user with no roles has no permissions -> the assistant.use gate must reject.
    email = await _make_user(client, admin_h, [], "NoPermPass123")
    h = await _headers(client, email, "NoPermPass123")
    r = await client.post("/api/v1/assistant/ask", headers=h, json={"question": "stock?"})
    assert r.status_code == 403, r.text


async def test_ask_returns_structured_response_and_logs(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.post(
        "/api/v1/assistant/ask", headers=admin_h, json={"question": "How is stock in all branches?"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Inert LLM: a well-formed, honest response (not a 500), with a logged conversation.
    assert set(["answer", "ok", "conversation_id", "tools_used"]).issubset(body)
    assert isinstance(body["answer"], str) and body["answer"]
    assert body["conversation_id"], "the turn must be logged even when the LLM is inert"
    assert isinstance(body["tools_used"], list)


async def test_ask_validates_empty_question(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    r = await client.post("/api/v1/assistant/ask", headers=admin_h, json={"question": ""})
    assert r.status_code == 422, r.text


async def test_whatsapp_mock_rejects_unregistered_number(client):
    admin_h = await _headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    phone = f"+999{uuid.uuid4().int % 10_000_000:07d}"
    r = await client.post(
        "/api/v1/assistant/whatsapp/mock", headers=admin_h, json={"from": phone, "text": "stock?"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matched_user"] is False
    assert body["ok"] is False
