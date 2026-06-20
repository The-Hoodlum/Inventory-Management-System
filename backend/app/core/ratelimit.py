"""Fixed-window rate limiting.

The window decision is a pure function (``evaluate_fixed_window``) so it is
fully unit-testable with a controllable clock. ``InMemoryRateLimiter`` keeps
per-key counters for a single process — fine for one app instance or as a
sensible default; a multi-instance deployment should back this with Redis
(swap the limiter, keep the policy).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitRule:
    limit: int           # max requests allowed per window
    window_seconds: int  # window length


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int  # seconds until the window resets (0 when allowed)


def evaluate_fixed_window(
    *, count: int, window_start: float | None, now: float, rule: RateLimitRule
) -> tuple[bool, int, float]:
    """Decide whether a request is allowed under a fixed window.

    Returns ``(allowed, new_count, new_window_start)``. A fresh or expired
    window resets the counter; otherwise the request is allowed only while the
    count is below the limit.
    """
    if window_start is None or (now - window_start) >= rule.window_seconds:
        return True, 1, now
    if count < rule.limit:
        return True, count + 1, window_start
    return False, count, window_start


class InMemoryRateLimiter:
    def __init__(self) -> None:
        # key -> (count, window_start)
        self._buckets: dict[str, tuple[int, float]] = {}

    def hit(self, key: str, rule: RateLimitRule, now: float) -> RateLimitResult:
        count, window_start = self._buckets.get(key, (0, None))
        allowed, new_count, new_start = evaluate_fixed_window(
            count=count, window_start=window_start, now=now, rule=rule
        )
        self._buckets[key] = (new_count, new_start)
        reset_at = new_start + rule.window_seconds
        remaining = max(0, rule.limit - new_count)
        retry_after = 0 if allowed else max(0, math.ceil(reset_at - now))
        return RateLimitResult(allowed=allowed, remaining=remaining, retry_after=retry_after)

    def prune(self, now: float, *, max_window_seconds: int) -> int:
        """Drop entries whose window has fully expired. Returns how many were
        removed. Call opportunistically to bound memory."""
        cutoff = now - max_window_seconds
        stale = [k for k, (_c, ws) in self._buckets.items() if ws <= cutoff]
        for k in stale:
            del self._buckets[k]
        return len(stale)
