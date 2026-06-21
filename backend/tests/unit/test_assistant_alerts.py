"""Proactive-alert message builders, due-window logic, and delivery."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.assistant.alerts import (
    AlertService,
    build_daily_summary_message,
    build_low_stock_message,
    build_pending_pr_message,
    build_weekly_report_message,
    due_alert_kinds,
)
from app.assistant.whatsapp import MockWhatsAppAdapter

_SETTINGS = SimpleNamespace(assistant_daily_summary_hour=17, assistant_weekly_report_weekday=0)


def test_low_stock_message_or_none():
    assert build_low_stock_message({"count": 0, "items": []}) is None
    msg = build_low_stock_message(
        {"count": 1, "items": [{"name": "HLX 150", "branch": "Lusaka", "available": 3, "reorder_point": 5}]}
    )
    assert "Low stock" in msg and "HLX 150" in msg and "Lusaka" in msg


def test_pending_pr_message_or_none():
    assert build_pending_pr_message({"count": 0, "requests": []}) is None
    msg = build_pending_pr_message(
        {"count": 1, "requests": [{"po_number": "PO-1", "branch": "Ndola", "total": 1000,
                                   "currency": "USD", "status": "pending_approval"}]}
    )
    assert "awaiting approval" in msg and "PO-1" in msg


def test_daily_and_weekly_messages():
    daily = build_daily_summary_message({
        "date": "2026-06-21", "currency": "USD", "units_sold": 23, "estimated_revenue": 7594,
        "top_item": "Spark Plug", "best_branch": "Lusaka", "low_stock_count": 9,
        "pending_purchase_requests": 0,
    })
    assert "2026-06-21" in daily and "23" in daily and "Lusaka" in daily
    weekly = build_weekly_report_message({
        "period": "2026-06-14 to 2026-06-21", "currency": "USD",
        "by_branch": [{"branch": "Lusaka", "units_sold": 50, "estimated_revenue": 1000, "low_stock_items": 2}],
    })
    assert "Weekly report" in weekly and "Total:" in weekly


def test_due_alert_kinds_windows():
    # low_stock + pending always due
    base = due_alert_kinds(dt.datetime(2026, 6, 23, 9, 0), _SETTINGS)  # Tue 09:00
    assert base == {"low_stock", "pending_pr"}
    # closing hour -> add daily
    at_close = due_alert_kinds(dt.datetime(2026, 6, 23, 17, 0), _SETTINGS)  # Tue 17:00
    assert "daily" in at_close and "weekly" not in at_close
    # closing hour on the weekly weekday (Monday=0) -> add weekly
    weekly = due_alert_kinds(dt.datetime(2026, 6, 22, 17, 0), _SETTINGS)  # Mon 17:00
    assert "weekly" in weekly and "daily" in weekly


class _FakeAlertRepo:
    async def all_warehouse_ids(self):
        return ["w1"]

    async def alert_recipients(self):
        return ["+260111", "+260222"]

    async def low_stock(self, ids):
        return {"count": 1, "items": [{"name": "HLX 150", "branch": "Lusaka", "available": 3, "reorder_point": 5}]}

    async def pending_purchase_requests(self, ids):
        return {"count": 0, "requests": []}

    async def daily_summary(self, day, ids, ccy):
        return {"date": str(day), "currency": ccy, "units_sold": 5, "estimated_revenue": 100,
                "top_item": "X", "best_branch": "Lusaka", "low_stock_count": 1, "pending_purchase_requests": 0}

    async def branch_performance(self, start, end, ids, ccy):
        return {"period": f"{start} to {end}", "currency": ccy,
                "by_branch": [{"branch": "Lusaka", "units_sold": 5, "estimated_revenue": 100, "low_stock_items": 1}]}


async def test_alert_service_broadcasts_to_recipients():
    adapter = MockWhatsAppAdapter()
    svc = AlertService(_FakeAlertRepo(), adapter)
    sent = await svc.run_due({"low_stock", "pending_pr", "daily", "weekly"}, currency="USD", today=dt.date(2026, 6, 21))
    assert sent["low_stock"] == 2   # 2 recipients
    assert sent["pending_pr"] == 0  # nothing pending -> no message -> 0
    assert sent["daily"] == 2 and sent["weekly"] == 2
    # 3 messages (low/daily/weekly) x 2 recipients = 6 deliveries
    assert len(adapter.sent) == 6
