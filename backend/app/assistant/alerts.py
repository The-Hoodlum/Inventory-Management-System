"""Proactive alerts: low-stock, daily sales summary, weekly report, and pending
purchase-request notifications, delivered over the WhatsApp adapter.

Message builders are pure (dict -> WhatsApp text or None) so they're easy to test.
``AlertService`` fetches the data via the (RLS-scoped) AssistantRepository, builds the
messages, and broadcasts them to the tenant's registered WhatsApp numbers. Driven by
``AlertScheduler``; off unless ASSISTANT_ALERTS_ENABLED. Uses the same adapter as the
chat path, so it works with the mock today and Meta Cloud later with no code change.
"""
from __future__ import annotations

import datetime as dt

from app.assistant.repository import AssistantRepository
from app.assistant.whatsapp import WhatsAppAdapter

_MAX_BULLETS = 8


def build_low_stock_message(low: dict) -> str | None:
    items = low.get("items", [])
    if not items:
        return None
    lines = [f"- {it['name']} ({it['branch']}): *{int(it['available'])}* / reorder {it['reorder_point']}"
             for it in items[:_MAX_BULLETS]]
    more = len(items) - len(lines)
    if more > 0:
        lines.append(f"...and {more} more")
    return f"⚠️ *Low stock* — {low['count']} item(s) at/below reorder:\n" + "\n".join(lines)


def build_daily_summary_message(s: dict) -> str:
    ccy = s.get("currency", "")
    head = f"📊 *Daily summary* {s['date']}"
    body = [
        f"💰 Sales: *{s['units_sold']:g}* units, est. {ccy} *{s['estimated_revenue']:,.0f}*",
        f"🏆 Top: {s.get('top_item') or '—'} | Best branch: {s.get('best_branch') or '—'}",
        f"⚠️ Low stock: *{s.get('low_stock_count', 0)}* | 📝 Pending POs: *{s.get('pending_purchase_requests', 0)}*",
    ]
    return head + "\n" + "\n".join(body)


def build_weekly_report_message(perf: dict) -> str:
    ccy = perf.get("currency", "")
    lines = [f"📊 *Weekly report* {perf['period']}"]
    total_units = 0.0
    for b in perf.get("by_branch", [])[:_MAX_BULLETS]:
        total_units += b["units_sold"]
        lines.append(
            f"- {b['branch']}: *{b['units_sold']:g}* units, est. {ccy} {b['estimated_revenue']:,.0f}"
            f", {b['low_stock_items']} low"
        )
    lines.append(f"*Total:* {total_units:g} units")
    return "\n".join(lines)


def build_bike_stock_message(low: list[dict]) -> str | None:
    """Model/colours at or below their reorder point. ``low`` comes from
    MotorcycleService.low_stock_bikes — the single source for the threshold logic; this
    only renders it. Out-of-stock rows are called out explicitly, since "0 left" is the
    line a manager needs to see first."""
    if not low:
        return None
    lines = []
    for r in low[:_MAX_BULLETS]:
        name = r.get("model") or "Motorcycle"
        if r.get("colour"):
            name += f" ({r['colour']})"
        where = f" - {r['branch']}" if r.get("branch") else ""
        if int(r.get("available", 0)) <= 0:
            lines.append(f"- {name}{where}: *OUT OF STOCK*")
        else:
            lines.append(f"- {name}{where}: *{r['available']}* left / reorder {r['reorder_point']}")
    more = len(low) - len(lines)
    if more > 0:
        lines.append(f"...and {more} more")
    return f"🏍️ *Bike stock running low* — {len(low)} model/colour(s):\n" + "\n".join(lines)


def build_pending_pr_message(pending: dict) -> str | None:
    reqs = pending.get("requests", [])
    if not reqs:
        return None
    lines = [f"- {r['po_number']} ({r['branch']}): {r['currency']} {r['total']:,.0f} — {r['status']}"
             for r in reqs[:_MAX_BULLETS]]
    return f"📝 *{pending['count']} purchase request(s)* awaiting approval:\n" + "\n".join(lines)


_MAX_REQUEST_ITEMS = 5      # per request, before "…and N more items"
_MAX_DETAILED_REQUESTS = 3  # beyond this, fall back to one-liners so the message stays readable


def _qty(value) -> str:
    """Whole numbers without a trailing .0 — '10' not '10.0'."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "?"
    return str(int(f)) if f == int(f) else f"{f:g}"


def _request_block(r: dict) -> list[str]:
    """One request rendered with its requester, purpose and actual lines."""
    purpose = str(r.get("purpose") or "request").replace("_", " ")
    head = f"*{r['request_number']}* — {purpose}"
    who = r.get("requested_by")
    where = r.get("branch")
    origin = " · ".join(x for x in (who, where) if x)
    block = [head] + ([f"  From: {origin}"] if origin else [])
    items = r.get("items") or []
    for it in items[:_MAX_REQUEST_ITEMS]:
        block.append(f"  - {it['name']} x {_qty(it['qty'])}")
    hidden = len(items) - min(len(items), _MAX_REQUEST_ITEMS)
    if hidden > 0:
        block.append(f"  ...and {hidden} more item(s)")
    if not items:
        block.append(f"  ({r.get('item_count', 0)} item(s))")
    return block


def build_order_requests_message(pending: dict) -> str | None:
    """Requisitions awaiting approval, WITH what was actually requested.

    An approver should be able to decide from the message; listing only a request number
    and an item count forced them into the app to find out what was being asked for. A few
    requests are shown in full; beyond that it degrades to one-liners so a busy day doesn't
    produce an unreadable wall of text."""
    reqs = pending.get("requests", [])
    if not reqs:
        return None
    lines: list[str] = []
    for r in reqs[:_MAX_DETAILED_REQUESTS]:
        lines += _request_block(r)
    for r in reqs[_MAX_DETAILED_REQUESTS:_MAX_BULLETS]:
        lines.append(f"*{r['request_number']}* ({r['branch']}): {r['item_count']} item(s)")
    more = len(reqs) - min(len(reqs), _MAX_BULLETS)
    if more > 0:
        lines.append(f"...and {more} more request(s)")
    return (f"📝 *{pending['count']} order request(s)* awaiting approval — reply "
            f"\"approve REQ-…\" or \"reject REQ-…\":\n" + "\n".join(lines))


def due_alert_kinds(now: dt.datetime, settings) -> set[str]:
    """Which alert kinds are due at ``now``. Low-stock, pending POs, and pending order
    requests run every cycle; the daily summary fires at the closing hour; the weekly
    report on its weekday + hour."""
    kinds = {"low_stock", "pending_pr", "order_requests", "bike_stock"}
    if now.hour == settings.assistant_daily_summary_hour:
        kinds.add("daily")
        if now.weekday() == settings.assistant_weekly_report_weekday:
            kinds.add("weekly")
    return kinds


class AlertService:
    def __init__(self, repo: AssistantRepository, adapter: WhatsAppAdapter) -> None:
        self.repo = repo
        self.adapter = adapter

    async def _broadcast(self, message: str | None) -> int:
        if not message:
            return 0
        phones = await self.repo.alert_recipients()
        for phone in phones:
            await self.adapter.send(to=phone, text=message)
        return len(phones)

    async def run_due(
        self, kinds: set[str], *, currency: str, today: dt.date,
        low_bikes: list[dict] | None = None,
    ) -> dict[str, int]:
        """Build + broadcast each due alert. Returns {kind: recipients_messaged}.

        ``low_bikes`` is supplied by the caller (the scheduler) from
        MotorcycleService.low_stock_bikes, so the model/colour threshold logic lives in one
        place rather than being reimplemented here."""
        ids = await self.repo.all_warehouse_ids()
        sent: dict[str, int] = {}
        if "low_stock" in kinds:
            sent["low_stock"] = await self._broadcast(build_low_stock_message(await self.repo.low_stock(ids)))
        if "bike_stock" in kinds and low_bikes:
            sent["bike_stock"] = await self._broadcast(build_bike_stock_message(low_bikes))
        if "pending_pr" in kinds:
            msg = build_pending_pr_message(await self.repo.pending_purchase_requests(ids))
            sent["pending_pr"] = await self._broadcast(msg)
        if "order_requests" in kinds:
            msg = build_order_requests_message(await self.repo.pending_order_requests(ids))
            sent["order_requests"] = await self._broadcast(msg)
        if "daily" in kinds:
            summary = await self.repo.daily_summary(today, ids, currency)
            sent["daily"] = await self._broadcast(build_daily_summary_message(summary))
        if "weekly" in kinds:
            perf = await self.repo.branch_performance(today - dt.timedelta(days=7), today, ids, currency)
            sent["weekly"] = await self._broadcast(build_weekly_report_message(perf))
        return sent
