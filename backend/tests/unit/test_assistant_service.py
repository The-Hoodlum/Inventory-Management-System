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
P1 = uuid.uuid4()


class FakeRepo:
    def __init__(self, *, phone_user: uuid.UUID | None = None, roles: list[str] | None = None,
                 permissions: set[str] | None = None, product=None) -> None:
        self.warehouses = [
            SimpleNamespace(id=LUSAKA, name="Lusaka", code="LUS"),
            SimpleNamespace(id=NDOLA, name="Ndola", code="NDL"),
        ]
        self.phone_user = phone_user
        self.roles = roles if roles is not None else ["Admin"]
        self.permissions = permissions if permissions is not None else set()
        self.product = product  # (id, sku, name) | None for find_product
        self.messages: list[dict] = []
        self.calls: dict[str, tuple] = {}
        self.conversations: list[dict] = []

    async def accessible_warehouses(self, user_id):
        return self.warehouses

    async def user_roles(self, user_id):
        return self.roles

    async def user_permissions(self, user_id):
        return self.permissions

    async def find_product(self, term):
        self.calls["find_product"] = (term,)
        return self.product

    async def tenant_currency(self):
        return "ZMW"

    async def tenant_config(self):
        from app.assistant.domain.prompt import TenantConfig
        return TenantConfig(company_name="Demo Co", industry="Retail", currency="ZMW")

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

    async def top_items(self, start, end, ids, limit, category=None):
        self.calls["top_items"] = (start, end, ids, limit, category)
        return {"items": []}

    async def branch_summary(self, day, ids, currency):
        self.calls["branch_summary"] = (day, ids, currency)
        return {"by_branch": []}

    async def stock_movements(self, term, ids, days, limit=20):
        self.calls["stock_movements"] = (term, ids, days)
        return {"movements": []}

    async def slow_moving(self, start, ids, limit=10):
        self.calls["slow_moving"] = (start, ids, limit)
        return {"items": []}

    async def pending_purchase_requests(self, ids):
        self.calls["pending_purchase_requests"] = (ids,)
        return {"count": 0, "requests": []}

    async def reorder_proposal(self, ids, currency):
        self.calls["reorder_proposal"] = (ids, currency)
        return {"is_proposal": True, "count": 0, "items": []}

    async def branch_performance(self, start, end, ids, currency):
        self.calls["branch_performance"] = (start, end, ids, currency)
        return {"by_branch": []}

    async def daily_summary(self, day, ids, currency):
        self.calls["daily_summary"] = (day, ids, currency)
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


class _FakeOrderRequests:
    def __init__(self):
        self.created = []
        self.approved = []
        self.rejected = []

    async def create(self, *, tenant_id, user_id, payload):
        self.created.append(payload)
        return SimpleNamespace(
            request_number="REQ-2026-00009", status="pending", branch_name="Lusaka",
            purpose=payload.purpose,
            lines=[SimpleNamespace(name="Oil Filter", requested_qty=ln.requested_qty) for ln in payload.lines],
        )

    async def history(self, *, viewer_id, is_admin, filters):
        self.last_history = {"viewer_id": viewer_id, "is_admin": is_admin, "filters": filters}
        return [SimpleNamespace(request_number="REQ-2026-00007", branch_name="Lusaka",
                                requester_name="Demo Cashier", purpose="for_sale", status="pending",
                                lines=[SimpleNamespace()])]

    async def get_by_number(self, number):
        if number != "REQ-2026-00007":
            return None
        return SimpleNamespace(id=uuid.uuid4(),
                               lines=[SimpleNamespace(id=uuid.uuid4(), requested_qty=5)])

    async def approve(self, *, tenant_id, actor_id, request_id, payload):
        self.approved.append((request_id, payload))
        return SimpleNamespace(request_number="REQ-2026-00007", status="approved")

    async def reject(self, *, tenant_id, actor_id, request_id, payload):
        self.rejected.append((request_id, payload.reason))
        return SimpleNamespace(request_number="REQ-2026-00007", status="rejected")


async def test_act_on_order_request_approve():
    repo = FakeRepo(roles=["Branch Manager"], permissions={"order_request.approve"})
    orq = _FakeOrderRequests()
    prov = ScriptedProvider([("act_on_order_request", {"request_number": "REQ-2026-00007", "action": "approve"})])
    svc = AssistantService(repo, prov, order_requests=orq)
    await svc.ask(tenant_id=TENANT, user_id=USER, question="approve REQ-2026-00007")
    res = prov.results[0][1]
    assert res["status"] == "approved" and len(orq.approved) == 1
    assert orq.approved[0][1].lines[0].approved_qty == 5  # approved in full


async def test_act_on_order_request_requires_approve_permission():
    # Viewer sees the tool (unrestricted role) but lacks order_request.approve -> blocked.
    repo = FakeRepo(roles=["Viewer"], permissions={"order_request.read"})
    orq = _FakeOrderRequests()
    prov = ScriptedProvider([("act_on_order_request", {"request_number": "REQ-2026-00007", "action": "approve"})])
    svc = AssistantService(repo, prov, order_requests=orq)
    await svc.ask(tenant_id=TENANT, user_id=USER, question="approve it")
    assert "permission" in prov.results[0][1]["error"].lower()
    assert orq.approved == []


async def test_act_on_order_request_reject_needs_reason():
    repo = FakeRepo(roles=["Branch Manager"], permissions={"order_request.approve"})
    orq = _FakeOrderRequests()
    prov = ScriptedProvider([("act_on_order_request", {"request_number": "REQ-2026-00007", "action": "reject"})])
    svc = AssistantService(repo, prov, order_requests=orq)
    await svc.ask(tenant_id=TENANT, user_id=USER, question="reject it")
    assert "reason" in prov.results[0][1]["error"].lower()
    assert orq.rejected == []


async def test_get_order_requests_lists_for_approver():
    repo = FakeRepo(roles=["Branch Manager"], permissions={"order_request.approve"})
    orq = _FakeOrderRequests()
    prov = ScriptedProvider([("get_order_requests", {"status": "pending"})])
    svc = AssistantService(repo, prov, order_requests=orq)
    await svc.ask(tenant_id=TENANT, user_id=USER, question="show pending requests")
    res = prov.results[0][1]
    assert res["count"] == 1 and res["requests"][0]["request_number"] == "REQ-2026-00007"
    assert orq.last_history["is_admin"] is True  # approver sees all


async def test_create_order_request_requires_permission():
    repo = FakeRepo(roles=["Cashier"], permissions=set())  # lacks order_request.create
    orq = _FakeOrderRequests()
    prov = ScriptedProvider([("create_order_request",
                              {"items": [{"item": "Oil Filter", "quantity": 5}], "branch": "Lusaka"})])
    svc = AssistantService(repo, prov, order_requests=orq)
    await svc.ask(tenant_id=TENANT, user_id=USER, question="request 5 oil filters")
    assert "permission" in prov.results[0][1]["error"].lower()
    assert orq.created == []  # nothing written


async def test_create_order_request_creates_pending():
    repo = FakeRepo(roles=["Cashier"], permissions={"order_request.create"}, product=(P1, "OF-1", "Oil Filter"))
    orq = _FakeOrderRequests()
    prov = ScriptedProvider([("create_order_request",
                              {"items": [{"item": "Oil Filter", "quantity": 5}],
                               "branch": "Lusaka", "purpose": "for_sale"})])
    svc = AssistantService(repo, prov, order_requests=orq)
    await svc.ask(tenant_id=TENANT, user_id=USER, question="request 5 oil filters")
    res = prov.results[0][1]
    assert res["created"] is True and res["request_number"] == "REQ-2026-00009"
    assert len(orq.created) == 1
    payload = orq.created[0]
    assert payload.branch_id == LUSAKA and payload.purpose == "for_sale"
    assert len(payload.lines) == 1 and payload.lines[0].product_id == P1 and payload.lines[0].requested_qty == 5


async def test_create_order_request_unknown_item_errors():
    repo = FakeRepo(roles=["Cashier"], permissions={"order_request.create"}, product=None)
    orq = _FakeOrderRequests()
    prov = ScriptedProvider([("create_order_request",
                              {"items": [{"item": "Nonexistent", "quantity": 2}], "branch": "Lusaka"})])
    svc = AssistantService(repo, prov, order_requests=orq)
    await svc.ask(tenant_id=TENANT, user_id=USER, question="request 2 widgets")
    assert "couldn't find" in prov.results[0][1]["error"].lower()
    assert orq.created == []


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
    start, end, _, limit, category = repo.calls["top_items"]
    assert limit == 10
    assert (end - start).days == 30
    assert end == dt.date.today()
    assert category is None


async def test_top_selling_items_passes_category():
    repo = FakeRepo()
    await _ask(repo, [("get_top_selling_items", {"category": "Beverages"})])
    assert repo.calls["top_items"][4] == "Beverages"  # generic category filter, any industry


async def test_stock_movements_defaults_to_7_days():
    repo = FakeRepo()
    await _ask(repo, [("get_stock_movements", {"item_name": "HLX"})])
    term, ids, days = repo.calls["stock_movements"]
    assert term == "HLX" and ids == [LUSAKA, NDOLA] and days == 7


async def test_pending_purchase_requests_dispatches():
    repo = FakeRepo()
    await _ask(repo, [("get_pending_purchase_requests", {})])
    assert repo.calls["pending_purchase_requests"] == ([LUSAKA, NDOLA],)


async def test_create_reorder_proposal_is_read_only_dispatch():
    repo = FakeRepo()
    await _ask(repo, [("create_reorder_proposal", {"branch": "Lusaka"})])
    assert repo.calls["reorder_proposal"] == ([LUSAKA], "ZMW")


async def test_branch_performance_defaults_to_30_days():
    repo = FakeRepo()
    await _ask(repo, [("get_branch_performance", {})])
    start, end, ids, currency = repo.calls["branch_performance"]
    assert (end - start).days == 30 and end == dt.date.today() and currency == "ZMW"


async def test_slow_moving_and_daily_summary_dispatch():
    repo = FakeRepo()
    await _ask(repo, [
        ("get_slow_moving_items", {"days": 14}),
        ("get_daily_summary", {"date": "2026-06-21"}),
    ])
    assert (dt.date.today() - repo.calls["slow_moving"][0]).days == 14
    assert repo.calls["daily_summary"][0] == dt.date(2026, 6, 21)


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
