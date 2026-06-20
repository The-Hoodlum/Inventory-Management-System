"""Data access for the intelligence layer (tenant-scoped by RLS).

Includes the supplier-performance query that powers the (real) supplier-risk
provider: per-supplier on-time rate, lead-time mean/variance, and fill rate,
derived from purchase orders, their lifecycle events, and line receipts.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.intelligence.domain.supplier_risk import SupplierMetrics
from app.intelligence.domain.supplier_score import SupplierHistory
from app.intelligence.providers.base import Observation
from app.models import IntelligenceSignal, Supplier, SupplierScore

# Per-supplier delivery performance from PO history + the lifecycle event timeline.
_SUPPLIER_METRICS_SQL = text(
    """
    WITH ev AS (
        SELECT po_id,
               MAX(created_at) FILTER (WHERE action = 'sent')                         AS sent_at,
               MAX(created_at) FILTER (WHERE to_status = 'received' OR action = 'received') AS received_at
        FROM purchase_order_events
        GROUP BY po_id
    ),
    ln AS (
        SELECT po_id, SUM(ordered_qty) AS ordered, SUM(received_qty) AS received
        FROM purchase_order_lines GROUP BY po_id
    ),
    po AS (
        SELECT p.id, p.supplier_id, p.status, p.expected_date, p.created_at,
               ev.received_at,
               COALESCE(ln.ordered, 0)  AS ordered,
               COALESCE(ln.received, 0) AS received,
               CASE WHEN ev.received_at IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (ev.received_at - COALESCE(ev.sent_at, p.created_at))) / 86400.0
               END AS lead_days
        FROM purchase_orders p
        LEFT JOIN ev ON ev.po_id = p.id
        LEFT JOIN ln ON ln.po_id = p.id
    )
    SELECT s.id, s.name, s.country,
           COUNT(*) FILTER (WHERE po.status = 'received')                          AS received_count,
           AVG(po.lead_days) FILTER (WHERE po.lead_days >= 0)                       AS avg_lead,
           STDDEV_SAMP(po.lead_days) FILTER (WHERE po.lead_days >= 0)               AS stdev_lead,
           COUNT(*) FILTER (WHERE po.status = 'received' AND po.expected_date IS NOT NULL) AS exp_recv,
           COUNT(*) FILTER (WHERE po.status = 'received' AND po.expected_date IS NOT NULL
                                  AND po.received_at::date <= po.expected_date)     AS on_time,
           SUM(po.ordered)  FILTER (WHERE po.status NOT IN ('draft','cancelled','rejected')) AS ordered_sum,
           SUM(po.received) FILTER (WHERE po.status NOT IN ('draft','cancelled','rejected')) AS received_sum
    FROM suppliers s
    LEFT JOIN po ON po.supplier_id = s.id
    WHERE s.deleted_at IS NULL
    GROUP BY s.id, s.name, s.country
    """
)

# As above, plus the purchase-history aggregates for the supplier scorecard.
_SUPPLIER_SCORE_SQL = text(
    """
    WITH ev AS (
        SELECT po_id,
               MAX(created_at) FILTER (WHERE action = 'sent')                         AS sent_at,
               MAX(created_at) FILTER (WHERE to_status = 'received' OR action = 'received') AS received_at
        FROM purchase_order_events
        GROUP BY po_id
    ),
    ln AS (
        SELECT po_id, SUM(ordered_qty) AS ordered, SUM(received_qty) AS received
        FROM purchase_order_lines GROUP BY po_id
    ),
    po AS (
        SELECT p.id, p.supplier_id, p.status, p.expected_date, p.created_at, p.total,
               ev.received_at,
               COALESCE(ln.ordered, 0)  AS ordered,
               COALESCE(ln.received, 0) AS received,
               CASE WHEN ev.received_at IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (ev.received_at - COALESCE(ev.sent_at, p.created_at))) / 86400.0
               END AS lead_days
        FROM purchase_orders p
        LEFT JOIN ev ON ev.po_id = p.id
        LEFT JOIN ln ON ln.po_id = p.id
    )
    SELECT s.id, s.name,
           COUNT(*) FILTER (WHERE po.status = 'received')                          AS received_count,
           AVG(po.lead_days) FILTER (WHERE po.lead_days >= 0)                       AS avg_lead,
           STDDEV_SAMP(po.lead_days) FILTER (WHERE po.lead_days >= 0)               AS stdev_lead,
           COUNT(*) FILTER (WHERE po.status = 'received' AND po.expected_date IS NOT NULL) AS exp_recv,
           COUNT(*) FILTER (WHERE po.status = 'received' AND po.expected_date IS NOT NULL
                                  AND po.received_at::date <= po.expected_date)     AS on_time,
           SUM(po.ordered)  FILTER (WHERE po.status NOT IN ('draft','cancelled','rejected')) AS ordered_sum,
           SUM(po.received) FILTER (WHERE po.status NOT IN ('draft','cancelled','rejected')) AS received_sum,
           s.country,
           COUNT(po.id)                                                            AS po_count,
           COALESCE(SUM(po.total) FILTER (WHERE po.status NOT IN ('draft','cancelled','rejected')), 0) AS total_spend,
           MAX(po.created_at)                                                      AS last_order_at
    FROM suppliers s
    LEFT JOIN po ON po.supplier_id = s.id
    WHERE s.deleted_at IS NULL
    GROUP BY s.id, s.name, s.country
    """
)


class IntelligenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ----------------------------- writes ------------------------------ #
    async def add_observation(self, tenant_id: uuid.UUID, obs: Observation) -> IntelligenceSignal:
        row = IntelligenceSignal(
            tenant_id=tenant_id,
            category=obs.category,
            scope_type=obs.scope_type,
            scope_key=obs.scope_key,
            severity=obs.severity,
            demand_factor=obs.demand_factor,
            confidence=obs.confidence,
            headline=obs.headline,
            value=obs.value,
            unit=obs.unit,
            trend=obs.trend,
            source=obs.source,
            expires_at=obs.expires_at,
            detail=obs.detail,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete_by_source(self, source: str) -> None:
        """Clear prior observations from a (re-computable) source before re-ingest,
        so the table holds the current view rather than an ever-growing history."""
        await self.session.execute(
            text("DELETE FROM intelligence_signals WHERE source = :s"), {"s": source}
        )

    # ----------------------------- reads ------------------------------- #
    async def active(self) -> list[IntelligenceSignal]:
        stmt = select(IntelligenceSignal).where(
            or_(
                IntelligenceSignal.expires_at.is_(None),
                IntelligenceSignal.expires_at > func.now(),
            )
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list(
        self,
        *,
        category: str | None = None,
        scope_type: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[IntelligenceSignal], int]:
        base = select(IntelligenceSignal)
        if category:
            base = base.where(IntelligenceSignal.category == category)
        if scope_type:
            base = base.where(IntelligenceSignal.scope_type == scope_type)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        stmt = (
            base.order_by(IntelligenceSignal.severity.desc(), IntelligenceSignal.observed_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, int(total or 0)

    async def supplier_country_map(self) -> dict[str, str]:
        stmt = select(Supplier.id, Supplier.country).where(Supplier.deleted_at.is_(None))
        return {
            str(sid): country
            for sid, country in (await self.session.execute(stmt)).all()
            if country
        }

    async def supplier_metrics(self) -> list[tuple[uuid.UUID, str, str | None, SupplierMetrics]]:
        rows = (await self.session.execute(_SUPPLIER_METRICS_SQL)).all()
        out: list[tuple[uuid.UUID, str, str | None, SupplierMetrics]] = []
        for r in rows:
            (sid, name, country, received_count, avg_lead, stdev_lead,
             exp_recv, on_time, ordered_sum, received_sum) = r
            on_time_rate = (on_time / exp_recv) if exp_recv else None
            fill_rate = (float(received_sum) / float(ordered_sum)) if ordered_sum else None
            metrics = SupplierMetrics(
                on_time_rate=on_time_rate,
                avg_lead_time_days=float(avg_lead) if avg_lead is not None else None,
                lead_time_stdev_days=float(stdev_lead) if stdev_lead is not None else None,
                fill_rate=fill_rate,
                received_po_count=int(received_count or 0),
            )
            out.append((sid, name, country, metrics))
        return out

    async def supplier_score_inputs(
        self,
    ) -> list[tuple[uuid.UUID, str, str | None, SupplierMetrics, SupplierHistory]]:
        """Per-supplier metrics + purchase history for the scorecard."""
        rows = (await self.session.execute(_SUPPLIER_SCORE_SQL)).all()
        out: list[tuple[uuid.UUID, str, str | None, SupplierMetrics, SupplierHistory]] = []
        for r in rows:
            (sid, name, received_count, avg_lead, stdev_lead, exp_recv, on_time,
             ordered_sum, received_sum, country, po_count, total_spend, last_order_at) = r
            on_time_rate = (on_time / exp_recv) if exp_recv else None
            fill_rate = (float(received_sum) / float(ordered_sum)) if ordered_sum else None
            metrics = SupplierMetrics(
                on_time_rate=on_time_rate,
                avg_lead_time_days=float(avg_lead) if avg_lead is not None else None,
                lead_time_stdev_days=float(stdev_lead) if stdev_lead is not None else None,
                fill_rate=fill_rate,
                received_po_count=int(received_count or 0),
            )
            history = SupplierHistory(
                po_count=int(po_count or 0),
                received_po_count=int(received_count or 0),
                total_spend=Decimal(total_spend or 0),
                last_order_at=last_order_at,
            )
            out.append((sid, name, country, metrics, history))
        return out

    # ------------------------- supplier scores ------------------------- #
    async def save_supplier_score(self, **fields) -> SupplierScore:
        row = SupplierScore(**fields)
        self.session.add(row)
        await self.session.flush()
        return row

    async def latest_supplier_scores(self) -> list[SupplierScore]:
        """Most recent score per supplier (backs the supplier list view)."""
        stmt = (
            select(SupplierScore)
            .distinct(SupplierScore.supplier_id)
            .order_by(SupplierScore.supplier_id, SupplierScore.computed_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def supplier_score_history(
        self, supplier_id: uuid.UUID, *, limit: int = 30
    ) -> list[SupplierScore]:
        stmt = (
            select(SupplierScore)
            .where(SupplierScore.supplier_id == supplier_id)
            .order_by(SupplierScore.computed_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
