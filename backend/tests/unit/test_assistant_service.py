"""AssistantService orchestration: branch-access resolution, date parsing, honest
fallbacks, conversation logging, and the WhatsApp phone->user path — all with a fake
repository and a scripted fake provider (no DB, no OpenAI)."""
from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from app.assistant.providers import AssistantRun, LLMProvider
from app.assistant.service import AssistantService

LUSAKA = uuid.uuid4()
NDOLA = uuid.uuid4()
TENANT = uuid.uuid4()
USER = uuid.uuid4()


class FakeRepo:
    def __init__(self, *, phone_user: uuid.UUID | None = None, roles: list[str] | None = None) -> None:
        self.warehouses = [
            SimpleNamespace(id=LUSAKA, name="Lusaka", code="LUS"),
            SimpleNamespace(id=NDOLA, name="Ndola", code="NDL"),
        ]
        self.phone_user = phone_user
        self.roles = roles if roles is not None else ["Admin"]
        self.messages: list[dict] = []
        self.calls: dict[str, tuple] = {}
        self.conversations: list[dict] = []

    async def accessible_warehouses(self, user_id):
        return self.warehouses

    async def user_roles(self, user_id):
        return self.roles

    async def tenant_currency(self):
        return "ZMW"

    async def user_id_for_phone(self, phone):
        return self.phone_user

    async def create_conversation(self, **kw):
        self.conversations.append(kw)
        return SimpleNamespace(id=uuid.uuid4(), **kw)

    async def add_message(self, **kw):
        self.messages.append(kw)

    async def stock_by_item(self, term, ids):
        self.calls["stock_by_item"] = (term, ids)
        return {"items": []}

    async def low_stock(self, ids):
        self.calls["low_stock"] = (ids,)
        return {"count": 0, "items": []}

    async def reorder_recommendations(self, ids):
        self.calls["reorder"] = (ids,)
        return {"count": 0}

    async def valuation(self, ids, currency):
        self.calls["valuation"] = (ids, currency)
        return {"total": 0.0}

    async def purchase_orders(self, status, ids):
        self.calls["purchase_orders"] = (status, ids)
        return {"count": 0}

    async def sales_summary(self, start, end, ids, currency):
        self.calls["sales_summary"] = (start, end, ids, currency)
        return {"units_sold": 0.0}

    async def top_items(self, start, end, ids, limit):
        self.calls["top_items"] = (start, end, ids, limit)
        return {"items": []}

    async def branch_summary(self, day, ids, currency):
        self.calls["branch_summary"] = (day, ids, currency)
        return {"by_branch": []}


class ScriptedProvider(LLMProvider):
    """Calls the executor for a fixed plan of (tool, args), then returns `answer`."""

    enabled = True

    def __init__(self, plan: list[tuple[str, dict]], answer: str = "done") -> None:
        self.plan = plan
        self.answer = answer
        self.results: list[tuple[str, dict]] = []
        self.system: str | None = None

    async def run(self, *, system, user, tools, tool_executor, max_rounds=5) -> AssistantRun:
        self.system = system
        calls = []
        for name, args in self.plan:
            self.results.append((name, await tool_executor(name, args)))
            calls.append({"name": name, "args": args})
        return AssistantRun(answer=self.answer, tool_calls=calls, ok=True)


def _service(repo: FakeRepo, plan: list[tuple[str, dict]], answer: str = "done"):
    provider = ScriptedProvider(plan, answer)
    return AssistantService(repo, provider), provider


async def _ask(repo, plan, answer="done"):
    svc, provider = _service(repo, plan, answer)
    resp = await svc.ask(tenant_id=TENANT, user_id=USER, question="q")
    return resp, provider


async def test_named_branch_scopes_to_that_warehouse():
    repo = FakeRepo()
    resp, _ = await _ask(repo, [("get_stock_level", {"item_name": "spark plug", "branch": "Lusaka"})])
    assert repo.calls["stock_by_item"] == ("spark plug", [LUSAKA])
    assert resp.tools_used == ["get_stock_level"]


async def test_branch_code_resolves_too():
    repo = FakeRepo()
    await _ask(repo, [("get_low_stock_items", {"branch": "ndl"})])
    assert repo.calls["low_stock"] == ([NDOLA],)


async def test_omitted_branch_uses_all_accessible():
    repo = FakeRepo()
    await _ask(repo, [("get_low_stock_items", {})])
    assert repo.calls["low_stock"] == ([LUSAKA, NDOLA],)


async def test_unknown_branch_errors_without_calling_repo():
    repo = FakeRepo()
    _, provider = await _ask(repo, [("get_stock_level", {"item_name": "x", "branch": "Kitwe"})])
    assert "stock_by_item" not in repo.calls
    assert "Kitwe" in provider.results[0][1]["error"]


async def test_sales_report_parses_explicit_date():
    repo = FakeRepo()
    await _ask(repo, [("get_sales_report", {"date": "2026-06-20"})])
    start, end, ids, currency = repo.calls["sales_summary"]
    assert start == dt.date(2026, 6, 20) and end == dt.date(2026, 6, 20)
    assert ids == [LUSAKA, NDOLA] and currency == "ZMW"


async def test_sales_between_dates_passes_range():
    repo = FakeRepo()
    await _ask(repo, [("get_sales_between_dates", {"start_date": "2026-06-01", "end_date": "2026-06-07"})])
    start, end, _, _ = repo.calls["sales_summary"]
    assert start == dt.date(2026, 6, 1) and end == dt.date(2026, 6, 7)


async def test_invalid_date_errors_without_calling_repo():
    repo = FakeRepo()
    _, provider = await _ask(repo, [("get_sales_report", {"date": "last tuesday"})])
    assert "sales_summary" not in repo.calls
    assert "Invalid date" in provider.results[0][1]["error"]


async def test_top_selling_defaults_to_last_30_days():
    repo = FakeRepo()
    await _ask(repo, [("get_top_selling_items", {})])
    start, end, _, limit = repo.calls["top_items"]
    assert limit == 10
    assert (end - start).days == 30
    assert end == dt.date.today()


async def test_assembly_status_is_honest_not_fabricated():
    repo = FakeRepo()
    _, provider = await _ask(repo, [("get_assembly_status", {})])
    result = provider.results[0][1]
    assert result["available"] is False
    assert "assembly" in result["message"].lower()


async def test_conversation_is_logged():
    repo = FakeRepo()
    await _ask(repo, [("get_low_stock_items", {})], answer="2 items low.")
    roles = [m["role"] for m in repo.messages]
    assert roles[0] == "user"
    assert "tool" in roles
    assert roles[-1] == "assistant"
    assert repo.messages[-1]["content"] == "2 items low."
    assert repo.conversations[0]["channel"] == "api"


async def test_role_restriction_blocks_disallowed_tool():
    # A Cashier may do stock + sales, but NOT inventory valuation.
    repo = FakeRepo(roles=["Cashier"])
    _, provider = await _ask(repo, [
        ("get_inventory_valuation", {}),       # disallowed -> error, repo untouched
        ("get_sales_report", {"date": "2026-06-20"}),  # allowed
    ])
    assert "valuation" not in repo.calls
    assert "role" in provider.results[0][1]["error"].lower()
    assert "sales_summary" in repo.calls  # the allowed one ran


async def test_unrestricted_role_sees_all_tools():
    repo = FakeRepo(roles=["Branch Manager"])  # not in the restricted map -> full access
    await _ask(repo, [("get_inventory_valuation", {})])
    assert "valuation" in repo.calls


async def test_system_prompt_grounds_today():
    repo = FakeRepo()
    svc, provider = _service(repo, [("get_low_stock_items", {})])
    await svc.ask(tenant_id=TENANT, user_id=USER, question="q")
    assert dt.date.today().isoformat() in provider.system  # model is told the real date


async def test_whatsapp_unknown_phone_is_rejected():
    repo = FakeRepo(phone_user=None)
    svc, _ = _service(repo, [])
    reply = await svc.whatsapp_reply(tenant_id=TENANT, phone="+260999999999", text="stock?")
    assert reply.matched_user is False
    assert reply.ok is False
    assert not repo.conversations  # never ran the engine


async def test_whatsapp_known_phone_runs_engine():
    repo = FakeRepo(phone_user=USER)
    svc, _ = _service(repo, [("get_low_stock_items", {})], answer="All good.")
    reply = await svc.whatsapp_reply(tenant_id=TENANT, phone="+260977000111", text="low stock?")
    assert reply.matched_user is True
    assert reply.reply == "All good."
    assert repo.conversations[0]["channel"] == "whatsapp"
    assert repo.conversations[0]["external_id"] == "+260977000111"
