"""LLM provider adapters for the advisor (network; inert unless configured).

Parallels ``app/intelligence/sources``: a real adapter that stays dormant until the
operator opts in. ``build_llm_provider`` returns the inert ``NullLLMProvider`` unless
the advisor LLM is both enabled and holding an API key, so the default build makes no
external calls and incurs no cost.
"""
from __future__ import annotations

import httpx

from app.advisor.domain.briefing import AdvisoryContext
from app.advisor.domain.llm import LLMProvider, NullLLMProvider, build_advisory_prompt
from app.core.logging import get_logger

logger = get_logger(__name__)

_ANTHROPIC_VERSION = "2023-06-01"


class ClaudeLLMProvider(LLMProvider):
    """Narrates grounded findings via the Anthropic Messages API. Built only when the
    advisor LLM is configured. On any API error it degrades to ``None`` so the
    deterministic briefing is still served."""

    enabled = True

    def __init__(
        self, *, api_key: str, model: str, base_url: str, max_tokens: int, timeout_seconds: float
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.timeout = timeout_seconds

    def __repr__(self) -> str:  # never leak the key in logs/reprs
        return f"ClaudeLLMProvider(model={self.model!r}, key=***redacted***)"

    async def narrate(self, context: AdvisoryContext, question: str | None = None) -> str | None:
        system, user = build_advisory_prompt(context, question)
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.base_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            parts = data.get("content") or []
            text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
            return text or None
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.warning("advisor_llm_failed", error=str(exc))
            return None


def build_llm_provider(settings) -> LLMProvider:
    """Claude when the advisor LLM is configured (enabled + key); inert Null otherwise."""
    if getattr(settings, "advisor_llm_configured", False):
        return ClaudeLLMProvider(
            api_key=settings.anthropic_api_key,
            model=settings.advisor_model,
            base_url=settings.advisor_base_url,
            max_tokens=settings.advisor_max_tokens,
            timeout_seconds=settings.advisor_timeout_seconds,
        )
    return NullLLMProvider()
