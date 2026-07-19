"""Proactive-alert scheduler.

Every ``ASSISTANT_ALERTS_INTERVAL_MINUTES`` it processes each tenant in its own
RLS-scoped transaction (``app.current_tenant`` set exactly as a request would) and
delivers any due alerts via the configured WhatsApp adapter. Off by default
(``ASSISTANT_ALERTS_ENABLED``). Per-tenant and per-cycle errors are isolated and logged
(type only) so one failure never stops the rest or crashes the loop. Mirrors
``app/intelligence/scheduler.py``.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt

from sqlalchemy import text

from app.assistant.alerts import AlertService, due_alert_kinds
from app.assistant.repository import AssistantRepository
from app.assistant.whatsapp import build_whatsapp_adapter
from app.core.logging import get_logger

logger = get_logger(__name__)


class AlertScheduler:
    def __init__(self, session_factory, settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    @property
    def interval_seconds(self) -> float:
        return max(1, int(self._settings.assistant_alerts_interval_minutes)) * 60

    async def list_tenant_ids(self) -> list:
        async with self._session_factory() as session:
            rows = await session.execute(text("SELECT id FROM tenants"))
            return [r[0] for r in rows.all()]

    async def run_for_tenant(self, tenant_id, kinds: set[str], today: dt.date) -> dict[str, int]:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :t, true)"),
                    {"t": str(tenant_id)},
                )
                repo = AssistantRepository(session)
                currency = await repo.tenant_currency()
                # Bike model/colour thresholds live in the Motorcycle module — reuse that
                # service rather than reimplementing the resolution here.
                low_bikes: list[dict] = []
                if "bike_stock" in kinds:
                    from app.motorcycles.repository import MotorcycleRepository
                    from app.motorcycles.service import MotorcycleService
                    from app.repositories.audit_repo import AuditRepository

                    moto = MotorcycleService(MotorcycleRepository(session), AuditRepository(session))
                    low_bikes = await moto.low_stock_bikes()
                adapter = build_whatsapp_adapter(self._settings)
                svc = AlertService(repo, adapter)
                sent = await svc.run_due(
                    kinds, currency=currency, today=today, low_bikes=low_bikes)
                if "daily" in kinds:
                    sent["branch_daily"] = await self._send_branch_digests(
                        session, adapter, today=today, currency=currency)
                return sent

    async def _send_branch_digests(self, session, adapter, *, today, currency: str) -> int:
        """One digest per branch, delivered to THAT branch's managers only.

        The broadcast alerts go to every registered number in the tenant, which for a
        per-branch report would send Lusaka's takings to the Solwezi manager. Recipients are
        resolved by role within the branch, then filtered to those who registered a WhatsApp
        number and have not opted out. Best-effort: a delivery failure never breaks the cycle.
        """
        from app.assistant.alerts import build_branch_daily_report
        from app.notifications.repository import NotificationRepository
        from app.reports.digest import DailyDigestService
        from app.reports.repository import ReportsRepository
        from app.reports.service import ReportsService

        sent = 0
        try:
            digests = await DailyDigestService(
                ReportsService(ReportsRepository(session)), session
            ).branch_digests(today)
            notif = NotificationRepository(session)
            for d in digests:
                recipients = await notif.recipients_with_role(
                    "Branch Manager", branch_id=d["branch_id"])
                phones = await notif.phones_for_push(recipients)
                if not phones:
                    continue
                message = build_branch_daily_report(d, currency=currency)
                for phone in set(phones.values()):
                    await adapter.send(to=phone, text=message)
                    sent += 1
        except Exception:  # noqa: BLE001 — a digest must never break the alert cycle
            logger.warning("branch_digest_failed")
        return sent

    async def run_cycle(self) -> dict:
        now = dt.datetime.now()
        kinds = due_alert_kinds(now, self._settings)
        tenant_ids = await self.list_tenant_ids()
        ok = 0
        for tid in tenant_ids:
            try:
                await self.run_for_tenant(tid, kinds, now.date())
                ok += 1
            except Exception as exc:  # noqa: BLE001 — isolate one tenant's failure
                logger.warning("alert_cycle_tenant_failed", tenant=str(tid), error_type=type(exc).__name__)
        summary = {"tenants": len(tenant_ids), "ok": ok, "kinds": sorted(kinds)}
        logger.info("alert_cycle_complete", **summary)
        return summary

    async def loop(self, stop: asyncio.Event) -> None:
        logger.info("alert_scheduler_started", interval_minutes=self._settings.assistant_alerts_interval_minutes)
        while not stop.is_set():
            try:
                await self.run_cycle()
            except Exception as exc:  # noqa: BLE001 — never let the loop die
                logger.warning("alert_cycle_failed", error_type=type(exc).__name__)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
        logger.info("alert_scheduler_stopped")
