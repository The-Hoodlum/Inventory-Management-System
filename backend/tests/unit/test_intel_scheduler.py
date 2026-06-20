"""Unit tests for the intelligence scheduler orchestration (no DB).

The per-tenant DB work (``list_tenant_ids`` / ``run_for_tenant``) is integration-
verified in Docker; here we test that a cycle iterates every tenant, isolates a
failing one, aggregates correctly, and that the loop runs a cycle then stops.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.intelligence.scheduler import IntelligenceScheduler


def _settings(interval=24):
    return SimpleNamespace(intel_scheduler_interval_hours=interval)


class _FakeScheduler(IntelligenceScheduler):
    """Overrides the two DB methods so the orchestration can be tested without a DB."""

    def __init__(self, tenant_ids, behavior):
        super().__init__(session_factory=None, settings=_settings())
        self._tids = tenant_ids
        self._behavior = behavior  # tid -> (ingested, scored) or an Exception to raise
        self.calls: list = []

    async def list_tenant_ids(self):
        return list(self._tids)

    async def run_for_tenant(self, tenant_id):
        self.calls.append(tenant_id)
        result = self._behavior[tenant_id]
        if isinstance(result, Exception):
            raise result
        return result


async def test_run_cycle_iterates_all_tenants_and_aggregates():
    s = _FakeScheduler(["t1", "t2"], {"t1": (3, 2), "t2": (1, 5)})
    summary = await s.run_cycle()
    assert s.calls == ["t1", "t2"]
    assert summary == {"tenants": 2, "ok": 2, "ingested": 4, "scored": 7}


async def test_run_cycle_isolates_a_failing_tenant():
    s = _FakeScheduler(["t1", "t2", "t3"], {"t1": (2, 1), "t2": RuntimeError("boom"), "t3": (1, 1)})
    summary = await s.run_cycle()
    assert s.calls == ["t1", "t2", "t3"]          # t2's failure didn't stop t3
    assert summary == {"tenants": 3, "ok": 2, "ingested": 3, "scored": 2}


async def test_loop_runs_a_cycle_then_stops():
    s = _FakeScheduler(["t1"], {"t1": (1, 1)})
    stop = asyncio.Event()
    cycles = 0
    base_run = s.run_cycle

    async def _run_once():
        nonlocal cycles
        cycles += 1
        result = await base_run()
        stop.set()  # ask the loop to stop after the first cycle
        return result

    s.run_cycle = _run_once
    await asyncio.wait_for(s.loop(stop), timeout=5)
    assert cycles == 1


def test_interval_seconds_from_settings():
    s = IntelligenceScheduler(session_factory=None, settings=_settings(interval=6))
    assert s.interval_seconds == 6 * 3600
