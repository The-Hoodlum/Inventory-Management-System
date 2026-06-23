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
from typing import TYPE_CHECKING

from app.assistant.domain.capabilities import WRITE_TOOL_PERMISSION, allowed_tools
from app.assistant.domain.prompt import build_system_prompt
from app.assistant.domain.tools import TOOL_SPECS
from app.assistant.providers import LLMProvider
from app.assistant.repository import AssistantRepository
from app.assistant.schemas import AskResponse, WhatsAppReply
from app.order_requests.domain.status import PURPOSES
from app.order_requests.schemas import (
    ApproveRequest,
    LineApproval,
    OrderRequestCreate,
    OrderRequestLineCreate,
    RejectRequest,
)

if TYPE_CHECKING:
    from app.order_requests.service import OrderRequestService

_ALL_BRANCH = ("", "all", "none", "any")


class AssistantService:
    def __init__(
        self, repo: AssistantRepository, provider: LLMProvider, *, max_tool_rounds: int = 5,
        order_requests: OrderRequestService | None = None,
    ) -> None:
        self.repo = repo
        self.provider = provider
        self.max_tool_rounds = max_tool_rounds
        self.order_requests = order_requests  # enables the create_order_request write tool

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
        config = await self.repo.tenant_config()
        currency = config.currency
        today = dt.date.today()

        # Role-based tool access: only expose (and accept) the tools this user's roles allow.
        roles = await self.repo.user_roles(user_id)
        allowed = allowed_tools(roles)
        # Write tools (e.g. create_order_request) are additionally gated by permission.
        permissions = await self.repo.user_permissions(user_id)
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
            required = WRITE_TOOL_PERMISSION.get(name)
            if required and required not in permissions:
                return {"error": "You don't have permission to do that."}
            try:
                if name == "create_order_request":
                    return await self._create_order_request(
                        args, tenant_id=tenant_id, user_id=user_id, all_ids=all_ids,
                        resolve_branch=resolve_branch,
                    )
                if name == "get_order_requests":
                    return await self._list_order_requests(args, user_id=user_id, permissions=permissions)
                if name == "act_on_order_request":
                    return await self._act_on_order_request(args, tenant_id=tenant_id, user_id=user_id)
                return await self._dispatch(name, args, resolve_branch, parse_date, today, currency)
            except Exception as exc:  # noqa: BLE001 — hand the error back to the model
                return {"error": f"{name} failed: {exc}"}

        # Build the system prompt dynamically from tenant configuration (industry-agnostic):
        # identity, custom instructions, currency, and the real date all come from settings.
        system = build_system_prompt(config, today)
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
            return await self.repo.top_items(start, end, ids, int(args.get("limit") or 10),
                                             category=args.get("category"))
        if name == "get_fast_moving_items":
            days = int(args.get("days") or 30)
            return await self.repo.top_items(today - dt.timedelta(days=days), today, ids, 10)
        if name == "get_branch_summary":
            d, derr = parse_date(args.get("date"), today)
            return {"error": derr} if derr else await self.repo.branch_summary(d, ids, currency)
        if name == "get_stock_movements":
            days = int(args.get("days") or 7)
            return await self.repo.stock_movements(args.get("item_name"), ids, days)
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

    async def _create_order_request(
        self, args: dict, *, tenant_id, user_id, all_ids, resolve_branch,
    ) -> dict:
        """Create a PENDING requisition from a chat request (no inventory change).
        Permission already checked by the caller; admins approve/issue elsewhere."""
        if self.order_requests is None:
            return {"error": "Order requests aren't enabled here."}
        branch_arg = args.get("branch")
        if branch_arg:
            ids, berr = resolve_branch(branch_arg)
            if berr:
                return {"error": berr}
            branch_id = ids[0]
        elif len(all_ids) == 1:
            branch_id = all_ids[0]
        else:
            return {"error": "Please say which branch this request is for."}

        items = args.get("items") or []
        lines: list[OrderRequestLineCreate] = []
        unresolved: list[str] = []
        for it in items:
            term = str((it or {}).get("item") or "").strip()
            qty = (it or {}).get("quantity")
            if not term or qty is None or float(qty) <= 0:
                unresolved.append(term or "(unnamed item)")
                continue
            match = await self.repo.find_product(term)
            if match is None:
                unresolved.append(term)
                continue
            lines.append(OrderRequestLineCreate(product_id=match[0], requested_qty=float(qty)))
        if unresolved:
            return {"error": f"Couldn't find: {', '.join(unresolved)}. Use the exact item name or SKU."}
        if not lines:
            return {"error": "No valid items to request."}

        purpose = args.get("purpose")
        if purpose not in PURPOSES:
            purpose = "other"
        out = await self.order_requests.create(
            tenant_id=tenant_id, user_id=user_id,
            payload=OrderRequestCreate(branch_id=branch_id, purpose=purpose, lines=lines),
        )
        return {
            "created": True, "request_number": out.request_number, "status": out.status,
            "branch": out.branch_name, "purpose": out.purpose,
            "items": [{"item": ln.name, "quantity": ln.requested_qty} for ln in out.lines],
            "note": "Pending an admin's approval; no stock has moved.",
        }

    async def _list_order_requests(self, args: dict, *, user_id, permissions: set[str]) -> dict:
        if self.order_requests is None:
            return {"error": "Order requests aren't enabled here."}
        is_admin = "order_request.approve" in permissions  # approvers see all; others see their own
        filters: dict = {"limit": 20}
        if args.get("status"):
            filters["status"] = args["status"]
        reqs = await self.order_requests.history(viewer_id=user_id, is_admin=is_admin, filters=filters)
        return {
            "count": len(reqs),
            "requests": [
                {"request_number": r.request_number, "branch": r.branch_name, "requester": r.requester_name,
                 "purpose": r.purpose, "status": r.status, "item_count": len(r.lines)}
                for r in reqs
            ],
        }

    async def _act_on_order_request(self, args: dict, *, tenant_id, user_id) -> dict:
        """Approve (in full) or reject a request by number. Permission already checked.
        Approving moves no stock — issuing stays a deliberate action in the app."""
        if self.order_requests is None:
            return {"error": "Order requests aren't enabled here."}
        number = (args.get("request_number") or "").strip()
        action = (args.get("action") or "").strip().lower()
        if not number:
            return {"error": "request_number is required."}
        req = await self.order_requests.get_by_number(number)
        if req is None:
            return {"error": f"Request {number} not found."}
        if action == "approve":
            payload = ApproveRequest(
                lines=[LineApproval(line_id=ln.id, approved_qty=ln.requested_qty) for ln in req.lines]
            )
            out = await self.order_requests.approve(
                tenant_id=tenant_id, actor_id=user_id, request_id=req.id, payload=payload
            )
            note = "Approved in full. An admin issues the stock in the app (stock moves only then)."
        elif action == "reject":
            reason = (args.get("reason") or "").strip()
            if not reason:
                return {"error": "A reason is required to reject a request."}
            out = await self.order_requests.reject(
                tenant_id=tenant_id, actor_id=user_id, request_id=req.id,
                payload=RejectRequest(reason=reason),
            )
            note = "Rejected."
        else:
            return {"error": "action must be 'approve' or 'reject'."}
        return {"request_number": out.request_number, "status": out.status, "note": note}

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
