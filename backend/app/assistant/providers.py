"""LLM provider for the assistant — OpenAI function-calling, inert unless configured.

``OpenAIProvider.run`` drives the tool loop: ask the model, execute any tool calls it
requests (via the injected ``tool_executor``), feed results back, repeat until it
returns a final answer or the round cap is hit. The model can only call the tools we
pass; execution is the caller's (RLS/branch-scoped) code. ``NullProvider`` is the
inert default so the app runs with no OpenAI key.
"""
from __future__ import annotations

import abc
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

ToolExecutor = Callable[[str, dict], Awaitable[dict]]


@dataclass
class AssistantRun:
    answer: str
    tool_calls: list[dict] = field(default_factory=list)  # [{"name", "args"}]
    ok: bool = True


class LLMProvider(abc.ABC):
    enabled: bool = False

    @abc.abstractmethod
    async def run(
        self, *, system: str, user: str, tools: list[dict], tool_executor: ToolExecutor,
        max_rounds: int = 5,
    ) -> AssistantRun: ...


class NullProvider(LLMProvider):
    """Used when the assistant LLM isn't configured."""

    enabled = False

    async def run(self, *, system, user, tools, tool_executor, max_rounds=5) -> AssistantRun:
        return AssistantRun(
            answer="The assistant is not configured (set ASSISTANT_ENABLED=true and OPENAI_API_KEY).",
            ok=False,
        )


class OpenAIProvider(LLMProvider):
    enabled = True

    def __init__(
        self, *, api_key: str, model: str, base_url: str, max_tokens: int,
        timeout_seconds: float, client: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        if client is not None:  # injected (tests)
            self._client = client
        else:
            from openai import AsyncOpenAI  # lazy: keep module importable without the dep

            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)

    def __repr__(self) -> str:  # never leak the key
        return f"OpenAIProvider(model={self.model!r}, key=***redacted***)"

    async def run(
        self, *, system, user, tools, tool_executor, max_rounds=5,
    ) -> AssistantRun:
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        calls_made: list[dict] = []
        try:
            for _ in range(max_rounds):
                resp = await self._client.chat.completions.create(
                    model=self.model, messages=messages, tools=tools,
                    tool_choice="auto", max_tokens=self.max_tokens,
                )
                msg = resp.choices[0].message
                tool_calls = msg.tool_calls or []
                if not tool_calls:
                    return AssistantRun(answer=(msg.content or "").strip(), tool_calls=calls_made)

                messages.append(msg.model_dump(exclude_none=True))  # assistant turn w/ tool_calls
                for tc in tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except (ValueError, TypeError):
                        args = {}
                    result = await tool_executor(name, args)
                    calls_made.append({"name": name, "args": args})
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str),
                    })

            # Round cap reached: ask once more with no tools for a final summary.
            resp = await self._client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=self.max_tokens,
            )
            return AssistantRun(answer=(resp.choices[0].message.content or "").strip(), tool_calls=calls_made)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully, never 500 the channel
            logger.warning("assistant_llm_failed", error=str(exc))
            return AssistantRun(
                answer="Sorry — I couldn't process that just now. Please try again.",
                tool_calls=calls_made, ok=False,
            )


def build_llm_provider(settings) -> LLMProvider:
    if getattr(settings, "assistant_configured", False):
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            max_tokens=settings.assistant_max_tokens,
            timeout_seconds=settings.assistant_timeout_seconds,
        )
    return NullProvider()
