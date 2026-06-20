"""Unit tests for the demand-pipeline service (fake repo, no database)."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from app.demand.service import DemandRebuildSummary, DemandService


class FakeDemandRepo:
    def __init__(self, rows: int) -> None:
        self.rows = rows
        self.calls: list[tuple] = []

    async def aggregate_issues(self, *, start_date, end_date, warehouse_id=None) -> int:
        self.calls.append((start_date, end_date, warehouse_id))
        return self.rows


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def add(self, **kwargs: Any):
        self.entries.append(kwargs)


async def test_rebuild_defaults_to_trailing_window_and_audits():
    repo = FakeDemandRepo(rows=7)
    audit = FakeAudit()
    svc = DemandService(repo, audit)
    end = dt.date(2026, 6, 13)

    summary = await svc.rebuild_from_issues(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), end_date=end, window_days=90
    )

    assert isinstance(summary, DemandRebuildSummary)
    assert summary.rows_written == 7
    assert summary.end_date == end
    assert summary.start_date == end - dt.timedelta(days=89)  # inclusive 90-day window
    # the repo was asked for exactly that range, no warehouse filter
    assert repo.calls == [(summary.start_date, end, None)]
    # exactly one audit entry, correctly tagged
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry["action"] == "demand.rebuild"
    assert entry["entity_type"] == "sales_daily"
    assert entry["changes"]["source"] == "issue"
    assert entry["changes"]["rows_written"] == 7


async def test_rebuild_respects_explicit_range_and_warehouse():
    repo = FakeDemandRepo(rows=3)
    audit = FakeAudit()
    svc = DemandService(repo, audit)
    wh = uuid.uuid4()

    summary = await svc.rebuild_from_issues(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        start_date=dt.date(2026, 1, 1),
        end_date=dt.date(2026, 1, 31),
        warehouse_id=wh,
    )

    assert summary.start_date == dt.date(2026, 1, 1)
    assert summary.end_date == dt.date(2026, 1, 31)
    assert summary.warehouse_id == wh
    assert repo.calls[0] == (dt.date(2026, 1, 1), dt.date(2026, 1, 31), wh)
    assert audit.entries[0]["changes"]["warehouse_id"] == str(wh)
