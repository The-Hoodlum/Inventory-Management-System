"""Data access for the demand pipeline.

Two responsibilities:
  * aggregate_issues — roll outbound 'issue' stock movements up into daily demand
    rows tagged source='issue'. Idempotent: it recomputes each day from the
    ledger and upserts, so re-running over the same window cannot double-count.
  * daily_series — the canonical per-day demand series (summed across all
    sources) that BOTH the forecast engine and the reorder engine consume.

Tenant scoping is enforced by PostgreSQL RLS (the request sets
``app.current_tenant``); the INSERT...SELECT only sees and writes this tenant's
rows, and the RLS WITH CHECK passes because tenant_id is carried through.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.forecast.domain.models import DemandPoint
from app.models import SalesDaily


class DemandRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def aggregate_issues(
        self,
        *,
        start_date: dt.date,
        end_date: dt.date,
        warehouse_id: uuid.UUID | None = None,
    ) -> int:
        """Upsert daily 'issue' demand for [start_date, end_date] (inclusive).

        Issues are stored as negative quantities in the ledger, so the day's sold
        units are ``SUM(-quantity)``. Returns the number of daily rows written.
        """
        params: dict[str, object] = {
            "start": start_date,
            "end_excl": end_date + dt.timedelta(days=1),
        }
        wh_clause = ""
        if warehouse_id is not None:
            wh_clause = "AND warehouse_id = CAST(:wh AS uuid)"
            params["wh"] = str(warehouse_id)

        sql = text(
            f"""
            INSERT INTO sales_daily
                (tenant_id, product_id, warehouse_id, sale_date, qty_sold, source)
            SELECT tenant_id,
                   product_id,
                   warehouse_id,
                   (created_at AT TIME ZONE 'UTC')::date AS d,
                   SUM(-quantity)                        AS qty,
                   'issue'
            FROM stock_movements
            WHERE movement_type = 'issue'
              AND created_at >= :start
              AND created_at <  :end_excl
              {wh_clause}
            GROUP BY tenant_id, product_id, warehouse_id, d
            ON CONFLICT (product_id, warehouse_id, sale_date, source)
            DO UPDATE SET qty_sold = EXCLUDED.qty_sold
            """
        )
        result = await self.session.execute(sql, params)
        return result.rowcount or 0

    async def daily_series(
        self,
        *,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        start_date: dt.date,
        end_date: dt.date,
    ) -> list[DemandPoint]:
        """Per-day demand totals (summed across sources), oldest -> newest."""
        stmt = (
            select(SalesDaily.sale_date, func.coalesce(func.sum(SalesDaily.qty_sold), 0))
            .where(
                SalesDaily.product_id == product_id,
                SalesDaily.warehouse_id == warehouse_id,
                SalesDaily.sale_date >= start_date,
                SalesDaily.sale_date <= end_date,
            )
            .group_by(SalesDaily.sale_date)
            .order_by(SalesDaily.sale_date)
        )
        rows = (await self.session.execute(stmt)).all()
        return [DemandPoint(day=row[0], quantity=Decimal(row[1])) for row in rows]
