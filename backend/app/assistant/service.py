"""Assistant orchestration: turn a natural-language question into tool calls over the
read services, log the conversation, and return a formatted answer.

The LLM may only call the allow-listed tools; this layer executes them against the
repository with the user's branch access enforced, parses branch/date arguments, and
keeps a transcript. Tool failures are returned to the model as ``{"error": ...}`` so
one bad call never crashes the turn.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid

from app.assistant.domain.capabilities import allowed_tools
from app.assistant.domain.tools import SYSTEM_PROMPT, TOOL_SPECS
from app.assistant.providers import LLMProvider
from app.assistant.repository import AssistantRepository
from app.assistant.schemas import AskResponse, WhatsAppReply

_ALL_BRANCH = ("", "all", "none", "any")


class AssistantService:
    def __init__(self, repo: AssistantRepository, provider: LLMProvider, *, max_tool_rounds: int = 5) -> None:
        self.repo = repo
        self.provider = provider
        self.max_tool_rounds = max_tool_rounds

    async def ask(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, question: str,
        channel: str = "api", external_id: str | None = None,
    ) -> AskResponse:
        warehouses = await self.repo.accessible_warehouses(user_id)
        all_ids = [w.id for w in warehouses]
        name_map: dict[str, uuid.UUID] = {}
        for w in warehouses:
            name_map[w.name.strip().lower()] = w.id
            if w.code:
                name_map[w.code.strip().lower()] = w.id
        currency = await self.repo.tenant_currency()
        today = dt.date.today()

        # Role-based tool access: only expose (and accept) the tools this user's roles allow.
        roles = await self.repo.user_roles(user_id)
        allowed = allowed_tools(roles)
        tools = [t for t in TOOL_SPECS if t["function"]["name"] in allowed]

        conv = await self.repo.create_conversation(
            tenant_id=tenant_id, user_id=user_id, channel=channel, external_id=external_id
        )
        await self.repo.add_message(tenant_id=tenant_id, conversation_id=conv.id, role="user", content=question)

        def resolve_branch(arg) -> tuple[list[uuid.UUID] | None, str | None]:
            if arg is None or str(arg).strip().lower() in _ALL_BRANCH:
                return all_ids, None
            wid = name_map.get(str(arg).strip().lower())
            if wid is None:
                return None, f"Branch '{arg}' was not found or you don't have access to it."
            return [wid], None

        def parse_date(arg, default: dt.date) -> tuple[dt.date | None, str | None]:
            s = (str(arg).strip().lower() if arg is not None else "")
            if s in ("", "today"):
                return default, None
            if s == "yesterday":
                return default - dt.timedelta(days=1), None
            try:
                return dt.date.fromisoformat(s), None
            except ValueError:
                return None, f"Invalid date '{arg}' — use YYYY-MM-DD."

        async def tool_executor(name: str, args: dict) -> dict:
            await self.repo.add_message(
                tenant_id=tenant_id, conversation_id=conv.id, role="tool",
                tool_name=name, content=json.dumps(args, default=str)[:400],
            )
            if name not in allowed:  # defence in depth — the model only saw allowed tools
                return {"error": "That action isn't available for your role."}
            try:
                return await self._dispatch(name, args, resolve_branch, parse_date, today, currency)
            except Exception as exc:  # noqa: BLE001 — hand the error back to the model
                return {"error": f"{name} failed: {exc}"}

        # Ground the model in the real date — otherwise it guesses (e.g. a training-era
        # date) when a question says "today"/"this week" and silently queries the wrong day.
        system = f"{SYSTEM_PROMPT}\n\nToday's date is {today.isoformat()} ({today:%A}). " \
                 "Use this for 'today', 'yesterday', and any relative date the user gives."
        run = await self.provider.run(
            system=system, user=question, tools=tools,
            tool_executor=tool_executor, max_rounds=self.max_tool_rounds,
        )
        await self.repo.add_message(
            tenant_id=tenant_id, conversation_id=conv.id, role="assistant", content=run.answer
        )
        return AskResponse(
            answer=run.answer, ok=run.ok, conversation_id=conv.id,
            tools_used=sorted({c["name"] for c in run.tool_calls}),
        )

    async def _dispatch(self, name, args, resolve_branch, parse_date, today, currency) -> dict:
        ids, berr = resolve_branch(args.get("branch"))
        if berr:
            return {"error": berr}

        if name == "get_stock_level":
            term = (args.get("item_name") or "").strip()
            return {"error": "item_name is required."} if not term else await self.repo.stock_by_item(term, ids)
        if name == "get_motorcycle_stock":
            term = (args.get("model") or "").strip()
            return {"error": "model is required."} if not term else await self.repo.stock_by_item(term, ids)
        if name == "get_low_stock_items":
            return await self.repo.low_stock(ids)
        if name == "get_reorder_recommendations":
            return await self.repo.reorder_recommendations(ids)
        if name == "get_inventory_valuation":
            return await self.repo.valuation(ids, currency)
        if name == "get_purchase_orders":
            return await self.repo.purchase_orders(args.get("status"), ids)
        if name == "get_sales_report":
            d, derr = parse_date(args.get("date"), today)
            return {"error": derr} if derr else await self.repo.sales_summary(d, d, ids, currency)
        if name == "get_sales_between_dates":
            start, e1 = parse_date(args.get("start_date"), today)
            end, e2 = parse_date(args.get("end_date"), today)
            if e1 or e2:
                return {"error": e1 or e2}
            return await self.repo.sales_summary(start, end, ids, currency)
        if name == "get_top_selling_items":
            end, e2 = parse_date(args.get("end_date"), today)
            start, e1 = parse_date(args.get("start_date"), (end or today) - dt.timedelta(days=30))
            if e1 or e2:
                return {"error": e1 or e2}
            return await self.repo.top_items(start, end, ids, int(args.get("limit") or 10))
        if name == "get_fast_moving_items":
            days = int(args.get("days") or 30)
            return await self.repo.top_items(today - dt.timedelta(days=days), today, ids, 10)
        if name == "get_branch_summary":
            d, derr = parse_date(args.get("date"), today)
            return {"error": derr} if derr else await self.repo.branch_summary(d, ids, currency)
        if name == "get_stock_movements":
            days = int(args.get("days") or 7)
            return await self.repo.stock_movements(args.get("item_name"), ids, days)
        if name == "get_top_selling_motorcycles":
            end, e2 = parse_date(args.get("end_date"), today)
            start, e1 = parse_date(args.get("start_date"), (end or today) - dt.timedelta(days=30))
            if e1 or e2:
                return {"error": e1 or e2}
            return await self.repo.top_motorcycles(start, end, ids, int(args.get("limit") or 10))
        if name == "get_slow_moving_items":
            days = int(args.get("days") or 30)
            return await self.repo.slow_moving(today - dt.timedelta(days=days), ids, int(args.get("limit") or 10))
        if name == "get_pending_purchase_requests":
            return await self.repo.pending_purchase_requests(ids)
        if name == "create_reorder_proposal":
            return await self.repo.reorder_proposal(ids, currency)
        if name == "get_branch_performance":
            end, e2 = parse_date(args.get("end_date"), today)
            start, e1 = parse_date(args.get("start_date"), (end or today) - dt.timedelta(days=30))
            if e1 or e2:
                return {"error": e1 or e2}
            return await self.repo.branch_performance(start, end, ids, currency)
        if name == "get_daily_summary":
            d, derr = parse_date(args.get("date"), today)
            return {"error": derr} if derr else await self.repo.daily_summary(d, ids, currency)
        if name == "get_assembly_status":
            return {"available": False,
                    "message": "Assembly status is not tracked in the system yet."}
        return {"error": f"Unknown tool '{name}'."}

    # ------------------------------ WhatsApp --------------------------- #
    async def whatsapp_reply(self, *, tenant_id: uuid.UUID, phone: str, text: str) -> WhatsAppReply:
        user_id = await self.repo.user_id_for_phone(phone)
        if user_id is None:
            return WhatsAppReply(
                reply="Sorry — this number isn't registered for the assistant. Contact your administrator.",
                ok=False, matched_user=False,
            )
        resp = await self.ask(
            tenant_id=tenant_id, user_id=user_id, question=text, channel="whatsapp", external_id=phone
        )
        return WhatsAppReply(reply=resp.answer, ok=resp.ok, matched_user=True)
