"""Daily intelligence scheduler.

Pulls every enabled provider for every tenant, converts results into intelligence
signals, and refreshes supplier scorecards. Those signals already feed risk scoring,
forecasting, and the reorder overlay (via the registered SignalPipeline), so a daily
cycle keeps the whole engine current with no manual action.

Off by default (``INTEL_SCHEDULER_ENABLED``). Multi-tenant: each tenant is processed
in its own transaction with the RLS GUC (``app.current_tenant``) set exactly as a
request would, so isolation holds. Per-tenant and per-cycle errors are isolated and
logged (type only) so one failure never stops the rest or crashes the loop. System
runs are audited with a null user (``audit_logs.user_id`` is nullable).
"""
from __future__ import annotations

import asyncio
import contextlib

from sqlalchemy import text

from app.core.logging import get_logger
from app.intelligence.providers.registry import build_free_providers
from app.intelligence.repository import IntelligenceRepository
from app.intelligence.service import IntelligenceService
from app.intelligence.sources.factory import build_external_source
from app.repositories.audit_repo import AuditRepository

logger = get_logger(__name__)


class IntelligenceScheduler:
    def __init__(self, session_factory, settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    @property
    def interval_seconds(self) -> float:
        return max(1, int(self._settings.intel_scheduler_interval_hours)) * 3600

    async def list_tenant_ids(self) -> list:
        async with self._session_factory() as session:
            rows = await session.execute(text("SELECT id FROM tenants"))
            return [r[0] for r in rows.all()]

    async def run_for_tenant(self, tenant_id) -> tuple[int, int]:
        """One tenant's cycle in its own RLS-scoped transaction: ingest all enabled
        providers, then refresh supplier scores. Returns (ingested, scored)."""
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :t, true)"),
                    {"t": str(tenant_id)},
                )
                svc = IntelligenceService(
                    IntelligenceRepository(session),
                    AuditRepository(session),
                    source=build_external_source(self._settings),
                    extra_providers=build_free_providers(self._settings),
                )
                ingested = (await svc.ingest(tenant_id=tenant_id, user_id=None)).ingested
                scored = (await svc.refresh_supplier_scores(tenant_id=tenant_id, user_id=None)).scored
                return ingested, scored

    async def run_cycle(self) -> dict:
        tenant_ids = await self.list_tenant_ids()
        ingested = scored = ok = 0
        for tid in tenant_ids:
            try:
                i, s = await self.run_for_tenant(tid)
                ingested += i
                scored += s
                ok += 1
            except Exception as exc:  # noqa: BLE001 — isolate one tenant's failure
                logger.warning(
                    "intel_cycle_tenant_failed", tenant=str(tid), error_type=type(exc).__name__
                )
        summary = {"tenants": len(tenant_ids), "ok": ok, "ingested": ingested, "scored": scored}
        logger.info("intel_cycle_complete", **summary)
        return summary

    async def loop(self, stop: asyncio.Event) -> None:
        """Run a cycle now, then every interval, until ``stop`` is set."""
        logger.info("intel_scheduler_started", interval_hours=self._settings.intel_scheduler_interval_hours)
        while not stop.is_set():
            try:
                await self.run_cycle()
            except Exception as exc:  # noqa: BLE001 — never let the loop die
                logger.warning("intel_cycle_failed", error_type=type(exc).__name__)
            # Sleep until the next interval, or wake immediately when stopping.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
        logger.info("intel_scheduler_stopped")
