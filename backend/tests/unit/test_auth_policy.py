"""Unit tests for the pure auth policy (no JWT/DB)."""
from __future__ import annotations

import datetime as dt

from app.core import auth_policy as ap

NOW = dt.datetime(2025, 6, 1, 12, 0, tzinfo=dt.timezone.utc)
DEFAULT = "CHANGE_ME_use_a_long_random_secret"


def test_secret_problems_flags_default():
    problems = ap.secret_problems(DEFAULT, environment="production", known_default=DEFAULT)
    assert any("default" in p for p in problems)


def test_secret_problems_flags_short():
    problems = ap.secret_problems("short", environment="production", known_default=DEFAULT)
    assert any("shorter than" in p for p in problems)


def test_secret_problems_accepts_strong_secret():
    strong = "x" * 48
    assert ap.secret_problems(strong, environment="production", known_default=DEFAULT) == []


def test_is_locked():
    assert ap.is_locked(None, NOW) is False
    assert ap.is_locked(NOW + dt.timedelta(seconds=60), NOW) is True
    assert ap.is_locked(NOW - dt.timedelta(seconds=1), NOW) is False


def test_seconds_until():
    assert ap.seconds_until(None, NOW) == 0
    assert ap.seconds_until(NOW + dt.timedelta(seconds=90), NOW) == 90
    assert ap.seconds_until(NOW - dt.timedelta(seconds=5), NOW) == 0


def test_register_failure_first_attempt():
    cfg = ap.LockoutConfig(max_attempts=5, window_seconds=900, lockout_seconds=900)
    count, locked = ap.register_failure(failed_count=0, last_failed_at=None, now=NOW, config=cfg)
    assert count == 1 and locked is None


def test_register_failure_increments_within_window():
    cfg = ap.LockoutConfig()
    count, locked = ap.register_failure(
        failed_count=2, last_failed_at=NOW - dt.timedelta(seconds=10), now=NOW, config=cfg
    )
    assert count == 3 and locked is None


def test_register_failure_locks_at_threshold():
    cfg = ap.LockoutConfig(max_attempts=5, lockout_seconds=900)
    count, locked = ap.register_failure(
        failed_count=4, last_failed_at=NOW - dt.timedelta(seconds=10), now=NOW, config=cfg
    )
    assert count == 5
    assert locked == NOW + dt.timedelta(seconds=900)


def test_register_failure_resets_after_window():
    cfg = ap.LockoutConfig(window_seconds=900)
    count, locked = ap.register_failure(
        failed_count=4, last_failed_at=NOW - dt.timedelta(seconds=1000), now=NOW, config=cfg
    )
    assert count == 1 and locked is None


def test_evaluate_refresh_outcomes():
    assert ap.evaluate_refresh(found=False, revoked=False, expired=False) == ap.REJECT
    assert ap.evaluate_refresh(found=True, revoked=True, expired=False) == ap.REUSE
    assert ap.evaluate_refresh(found=True, revoked=False, expired=True) == ap.REJECT
    assert ap.evaluate_refresh(found=True, revoked=False, expired=False) == ap.ROTATE
