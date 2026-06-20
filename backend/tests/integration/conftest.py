"""Shared fixtures for the HTTP integration tests.

These tests drive the real ASGI app through httpx, so they all share the
module-level async engine in ``app.db.session``. pytest-asyncio (auto mode) runs
each test in its **own** event loop, and an asyncpg connection is bound to the loop
it was created on. A connection left in the engine's pool by one test and then
reused by the next (on a fresh loop) raises::

    RuntimeError: ... got Future ... attached to a different loop

Disposing the engine's pool after every test removes that cross-loop reuse: each
test opens fresh connections on its own loop. Scoped to the integration suite only
(unit tests use in-memory fakes and never touch the engine).
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.core.ratelimit import InMemoryRateLimiter, RateLimitResult
from app.db.session import engine


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    # Drop all pooled connections so the next test (new event loop) reconnects
    # cleanly instead of reusing a connection bound to the previous test's loop.
    await engine.dispose()


@pytest.fixture(autouse=True)
def _bypass_rate_limiter(monkeypatch):
    # The suite makes many logins in well under a minute; the in-memory auth
    # limiter (10/min per IP, all tests share one client IP) would otherwise 429
    # later tests. The limiter's logic has its own unit tests, and no integration
    # test asserts rate limiting, so bypass it here to keep the suite deterministic.
    monkeypatch.setattr(
        InMemoryRateLimiter,
        "hit",
        lambda self, key, rule, now: RateLimitResult(
            allowed=True, remaining=rule.limit, retry_after=0
        ),
    )
