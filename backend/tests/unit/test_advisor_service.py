"""Unit tests for AdvisorService and the LLM provider factory (no network)."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx

from app.advisor.domain.llm import NullLLMProvider
from app.advisor.providers import ClaudeLLMProvider, build_llm_provider
from app.advisor.service import AdvisorService

D = Decimal


class FakeReorderRepo:
    def __init__(self, recs=()):
        self._recs = list(recs)

    async def list_recommendations(self, **kwargs):
        return list(self._recs), len(self._recs)


class FakeIntelRepo:
    def __init__(self, signals=(), scores=()):
        self._signals = list(signals)
        self._scores = list(scores)

    async def active(self):
        return list(self._signals)

    async def latest_supplier_scores(self):
        return list(self._scores)


class FakeForecastRepo:
    def __init__(self, forecasts=()):
        self._f = list(forecasts)

    async def latest_per_pair(self):
        return list(self._f)


class FakeContainerRepo:
    def __init__(self, products=()):
        self._p = {p.id: p for p in products}

    async def load_products(self, ids):
        return {i: self._p[i] for i in ids if i in self._p}


class FakeLLM:
    enabled = True

    def __init__(self, text):
        self._text = text

    async def narrate(self, context, question=None):
        return self._text


def _rec(sku="A", qty="10", risk="0.8", expedite=True):
    return SimpleNamespace(
        product_id=uuid.uuid4(), sku=sku, recommended_qty=D(qty),
        risk_score=D(risk), expedite=expedite, risk_cost_impact=D("0"), risk_drivers=[],
    )


async def test_briefing_is_deterministic_without_llm():
    svc = AdvisorService(
        FakeReorderRepo([_rec()]), FakeIntelRepo(), FakeForecastRepo(),
        FakeContainerRepo(), NullLLMProvider(),
    )
    resp = await svc.briefing()
    assert resp.llm_enabled is False
    assert resp.narrative is None
    assert resp.findings and resp.findings[0].category == "reorder"
    assert resp.metrics["reorder_pending"] == 1
    assert resp.summary


async def test_briefing_includes_llm_narrative_when_configured():
    svc = AdvisorService(
        FakeReorderRepo([_rec(expedite=False)]), FakeIntelRepo(), FakeForecastRepo(),
        FakeContainerRepo(), FakeLLM("Order A now."),
    )
    resp = await svc.briefing(question="what should I do?")
    assert resp.llm_enabled is True
    assert resp.narrative == "Order A now."


async def test_briefing_handles_empty_state():
    svc = AdvisorService(
        FakeReorderRepo(), FakeIntelRepo(), FakeForecastRepo(),
        FakeContainerRepo(), NullLLMProvider(),
    )
    resp = await svc.briefing()
    assert resp.findings == []
    assert resp.metrics["reorder_pending"] == 0


async def test_briefing_flags_under_utilised_container():
    sid, pid = uuid.uuid4(), uuid.uuid4()
    rec = SimpleNamespace(
        product_id=pid, sku="C", recommended_qty=D("100"), recommended_cartons=10,
        risk_score=D("0"), expedite=False, risk_cost_impact=D("0"), risk_drivers=[],
        supplier_id=sid,
    )
    product = SimpleNamespace(
        id=pid, sku="C", volume_per_carton=D("0.5"), weight_per_carton=D("10"), units_per_carton=1
    )
    svc = AdvisorService(
        FakeReorderRepo([rec]), FakeIntelRepo(), FakeForecastRepo(),
        FakeContainerRepo([product]), NullLLMProvider(),
    )
    resp = await svc.briefing()
    # 10 cartons × 0.5 m³ = 5 m³ -> 1 × 20GP at ~17% fill -> a container finding.
    assert resp.metrics["container_findings"] >= 1
    assert any(f.category == "container" for f in resp.findings)


async def test_ask_returns_relevant_findings_deterministically():
    sup = SimpleNamespace(supplier_id=uuid.uuid4(), risk_score=D("0.7"), grade="D")
    svc = AdvisorService(
        FakeReorderRepo([_rec()]), FakeIntelRepo(scores=[sup]), FakeForecastRepo(),
        FakeContainerRepo(), NullLLMProvider(),
    )
    resp = await svc.ask(question="which suppliers are risky?")
    assert resp.question == "which suppliers are risky?"
    assert resp.llm_enabled is False
    assert resp.answer is None
    assert any(f.category == "supplier_risk" for f in resp.relevant_findings)


async def test_ask_includes_llm_answer_when_configured():
    svc = AdvisorService(
        FakeReorderRepo([_rec()]), FakeIntelRepo(), FakeForecastRepo(),
        FakeContainerRepo(), FakeLLM("Here is the grounded answer."),
    )
    resp = await svc.ask(question="anything")
    assert resp.llm_enabled is True
    assert resp.answer == "Here is the grounded answer."


# ------------------------------ provider factory --------------------------- #
def test_build_llm_provider_inert_by_default():
    settings = SimpleNamespace(advisor_llm_configured=False)
    assert isinstance(build_llm_provider(settings), NullLLMProvider)


def test_build_llm_provider_returns_claude_when_configured():
    settings = SimpleNamespace(
        advisor_llm_configured=True, anthropic_api_key="k", advisor_model="claude-opus-4-8",
        advisor_base_url="https://api.anthropic.com/v1/messages", advisor_max_tokens=10,
        advisor_timeout_seconds=1.0,
    )
    provider = build_llm_provider(settings)
    assert isinstance(provider, ClaudeLLMProvider)
    assert provider.enabled is True


def test_claude_provider_repr_redacts_key():
    provider = ClaudeLLMProvider(
        api_key="super-secret", model="claude-opus-4-8",
        base_url="x", max_tokens=10, timeout_seconds=1.0,
    )
    rendered = repr(provider)
    assert "super-secret" not in rendered
    assert "redacted" in rendered.lower()


# ------------------------- ClaudeLLMProvider.narrate ----------------------- #
# Exercise the real narrator HTTP path (request shape, headers, response parse,
# error degradation) without a network call or API credits, by routing the
# provider's httpx.AsyncClient through a MockTransport.
def _stub_context(summary="1 SKU below reorder point.", findings=()):
    """Minimal stand-in for AdvisoryContext: narrate() only reads these two attrs
    (via build_advisory_prompt -> serialize_findings)."""
    return SimpleNamespace(summary_line=summary, findings=list(findings))


def _route_through_mock(monkeypatch, handler):
    """Make the provider's ``httpx.AsyncClient(...)`` use a MockTransport. Binds the
    real class first so the replacement factory doesn't recurse into itself."""
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def test_claude_provider_narrate_posts_grounded_request_and_parses_text(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "Expedite SKU-A. "},
                    {"type": "thinking", "text": "(non-text block, must be skipped)"},
                    {"type": "text", "text": "Supplier X is high-risk."},
                ]
            },
        )

    _route_through_mock(monkeypatch, handler)
    provider = ClaudeLLMProvider(
        api_key="super-secret", model="claude-opus-4-8",
        base_url="https://api.anthropic.com/v1/messages",
        max_tokens=512, timeout_seconds=5.0,
    )

    result = await provider.narrate(_stub_context(), question="what should I act on?")

    # Only text blocks are concatenated; non-text blocks are skipped.
    assert result == "Expedite SKU-A. Supplier X is high-risk."
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "super-secret"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    body = captured["body"]
    assert body["model"] == "claude-opus-4-8"
    assert body["max_tokens"] == 512
    assert body["system"]  # the deterministic grounding system prompt is sent
    assert body["messages"][0]["role"] == "user"
    assert "what should I act on?" in body["messages"][0]["content"]


async def test_claude_provider_narrate_degrades_to_none_on_api_error(monkeypatch):
    _route_through_mock(
        monkeypatch,
        lambda request: httpx.Response(401, json={"error": {"type": "authentication_error"}}),
    )
    provider = ClaudeLLMProvider(
        api_key="bad-key", model="claude-opus-4-8",
        base_url="https://api.anthropic.com/v1/messages",
        max_tokens=10, timeout_seconds=1.0,
    )
    # A failed call must NOT raise — it degrades to None so the deterministic briefing still serves.
    assert await provider.narrate(_stub_context()) is None


async def test_claude_provider_narrate_returns_none_when_no_text_block(monkeypatch):
    _route_through_mock(monkeypatch, lambda request: httpx.Response(200, json={"content": []}))
    provider = ClaudeLLMProvider(
        api_key="k", model="claude-opus-4-8",
        base_url="https://api.anthropic.com/v1/messages",
        max_tokens=10, timeout_seconds=1.0,
    )
    assert await provider.narrate(_stub_context()) is None
