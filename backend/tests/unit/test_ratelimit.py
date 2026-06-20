"""Unit tests for fixed-window rate limiting (pure; controllable clock)."""
from __future__ import annotations

from app.core.ratelimit import InMemoryRateLimiter, RateLimitRule, evaluate_fixed_window

RULE = RateLimitRule(limit=2, window_seconds=60)


def test_fresh_window_allows():
    allowed, count, start = evaluate_fixed_window(count=0, window_start=None, now=100.0, rule=RULE)
    assert allowed is True and count == 1 and start == 100.0


def test_under_limit_increments():
    allowed, count, start = evaluate_fixed_window(count=1, window_start=100.0, now=110.0, rule=RULE)
    assert allowed is True and count == 2 and start == 100.0


def test_at_limit_blocks():
    allowed, count, start = evaluate_fixed_window(count=2, window_start=100.0, now=110.0, rule=RULE)
    assert allowed is False and count == 2 and start == 100.0


def test_expired_window_resets():
    allowed, count, start = evaluate_fixed_window(count=2, window_start=100.0, now=200.0, rule=RULE)
    assert allowed is True and count == 1 and start == 200.0


def test_in_memory_limiter_sequence():
    rl = InMemoryRateLimiter()
    r1 = rl.hit("ip", RULE, now=0.0)
    assert r1.allowed and r1.remaining == 1
    r2 = rl.hit("ip", RULE, now=1.0)
    assert r2.allowed and r2.remaining == 0
    r3 = rl.hit("ip", RULE, now=2.0)
    assert r3.allowed is False and r3.retry_after == 58  # resets at 60
    # new window after expiry
    r4 = rl.hit("ip", RULE, now=61.0)
    assert r4.allowed and r4.remaining == 1


def test_separate_keys_are_independent():
    rl = InMemoryRateLimiter()
    rl.hit("a", RULE, now=0.0)
    rl.hit("a", RULE, now=0.0)
    blocked = rl.hit("a", RULE, now=0.0)
    fresh = rl.hit("b", RULE, now=0.0)
    assert blocked.allowed is False
    assert fresh.allowed is True


def test_prune_removes_expired():
    rl = InMemoryRateLimiter()
    rl.hit("old", RULE, now=0.0)
    rl.hit("new", RULE, now=100.0)
    removed = rl.prune(now=100.0, max_window_seconds=60)
    assert removed == 1  # 'old' window (start 0) expired by now=100
