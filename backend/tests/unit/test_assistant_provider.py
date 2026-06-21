"""OpenAIProvider tool-loop, exercised with a scripted fake OpenAI client (no network).

Verifies the provider asks the model, executes the tool calls it requests via the
injected executor, feeds the results back, and returns the model's final answer —
and that NullProvider stays inert.
"""
from __future__ import annotations

from app.assistant.providers import NullProvider, OpenAIProvider


# --- minimal stand-ins for the openai response objects the provider touches --- #
class _Func:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, id: str, name: str, arguments: str) -> None:
        self.id = id
        self.type = "function"
        self.function = _Func(name, arguments)


class _Msg:
    def __init__(self, content=None, tool_calls=None) -> None:
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none: bool = False) -> dict:
        d = {
            "role": "assistant",
            "content": self.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in (self.tool_calls or [])
            ] or None,
        }
        return {k: v for k, v in d.items() if v is not None} if exclude_none else d


class _Resp:
    def __init__(self, msg: _Msg) -> None:
        self.choices = [type("C", (), {"message": msg})()]


class _Completions:
    def __init__(self, scripted: list[_Msg]) -> None:
        self._scripted = list(scripted)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp(self._scripted.pop(0))


class _Client:
    def __init__(self, scripted: list[_Msg]) -> None:
        self.chat = type("Chat", (), {"completions": _Completions(scripted)})()


def _provider(client: _Client) -> OpenAIProvider:
    return OpenAIProvider(
        api_key="sk-test", model="gpt-4o-mini", base_url="https://example",
        max_tokens=128, timeout_seconds=5.0, client=client,
    )


async def test_run_executes_requested_tool_then_returns_answer():
    client = _Client([
        _Msg(tool_calls=[_ToolCall("call_1", "get_low_stock_items", '{"branch": "Lusaka"}')]),
        _Msg(content="3 items are low in Lusaka."),
    ])
    provider = _provider(client)

    executed: list[tuple[str, dict]] = []

    async def executor(name: str, args: dict) -> dict:
        executed.append((name, args))
        return {"count": 3}

    run = await provider.run(system="s", user="how is Lusaka?", tools=[], tool_executor=executor)

    assert run.ok is True
    assert run.answer == "3 items are low in Lusaka."
    assert executed == [("get_low_stock_items", {"branch": "Lusaka"})]
    assert run.tool_calls == [{"name": "get_low_stock_items", "args": {"branch": "Lusaka"}}]
    # the tool result was fed back into the second model call
    second_call_roles = [m.get("role") for m in client.chat.completions.calls[1]["messages"]]
    assert "tool" in second_call_roles


async def test_run_returns_answer_with_no_tool_calls():
    client = _Client([_Msg(content="Hello, how can I help?")])
    run = await _provider(client).run(system="s", user="hi", tools=[], tool_executor=None)  # type: ignore[arg-type]
    assert run.answer == "Hello, how can I help?"
    assert run.tool_calls == []


async def test_run_degrades_gracefully_on_client_error():
    class _Boom:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                async def create(**kwargs):
                    raise RuntimeError("network down")

    provider = OpenAIProvider(
        api_key="sk", model="m", base_url="b", max_tokens=10, timeout_seconds=1.0, client=_Boom(),
    )
    run = await provider.run(system="s", user="u", tools=[], tool_executor=None)  # type: ignore[arg-type]
    assert run.ok is False
    assert "couldn't process" in run.answer


async def test_repr_redacts_key():
    provider = _provider(_Client([_Msg(content="x")]))
    assert "sk-test" not in repr(provider)
    assert "redacted" in repr(provider)


async def test_null_provider_is_inert():
    provider = NullProvider()
    assert provider.enabled is False
    run = await provider.run(system="s", user="u", tools=[], tool_executor=None)  # type: ignore[arg-type]
    assert run.ok is False
    assert "not configured" in run.answer
