"""Demand-pipeline service: turn outbound stock movements into daily demand.

Deliberately framework-free (no pydantic / SQLAlchemy imports) so it is unit-
testable with a fake repository. Request validation lives in the API schema; the
API layer maps the returned dataclass onto the response model.

This is the seam for additional demand sources: ``rebuild_from_issues`` is the
automatic 'issue' channel today; CSV / POS / ERP importers will write to the same
``sales_daily`` table under their own ``source`` tag without touching forecasting.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class DemandRebuildSummary:
    start_date: dt.date
    end_date: dt.date
    rows_written: int
    warehouse_id: uuid.UUID | None


class DemandService:
    def __init__(self, repo, audit) -> None:
        self.repo = repo
        self.audit = audit

    async def rebuild_from_issues(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        start_date: dt.date | None = None,
        end_date: dt.date | None = None,
        window_days: int = 90,
        warehouse_id: uuid.UUID | None = None,
        ip: str | None = None,
    ) -> DemandRebuildSummary:
        """Recompute daily 'issue' demand over a window (defaults to the last
        ``window_days`` ending today) and record an audit entry."""
        end = end_date or dt.date.today()
        start = start_date or (end - dt.timedelta(days=window_days - 1))

        rows = await self.repo.aggregate_issues(
            start_date=start, end_date=end, warehouse_id=warehouse_id
        )

        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="demand.rebuild",
            entity_type="sales_daily",
            entity_id=None,
            changes={
                "source": "issue",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "warehouse_id": str(warehouse_id) if warehouse_id else None,
                "rows_written": rows,
            },
            ip_address=ip,
        )
        return DemandRebuildSummary(
            start_date=start, end_date=end, rows_written=rows, warehouse_id=warehouse_id
        )
