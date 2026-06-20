"""Pure authentication policy — standard library only (no JWT / DB / pydantic).

Isolated so the security-critical decisions are unit-testable without any
infrastructure:
  * ``secret_problems``    — flag weak/default JWT secrets at startup.
  * lockout state machine  — accumulate failures in a rolling window and lock.
  * ``evaluate_refresh``   — decide rotate / reject / reuse for refresh tokens.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

# Refresh-token outcomes.
REJECT = "reject"
REUSE = "reuse"
ROTATE = "rotate"


@dataclass(frozen=True)
class LockoutConfig:
    max_attempts: int = 5
    window_seconds: int = 900    # rolling window in which failures accumulate
    lockout_seconds: int = 900   # how long the account stays locked


def secret_problems(
    secret: str, *, environment: str, known_default: str, min_length: int = 32
) -> list[str]:
    """Return reasons a JWT secret is unsuitable (empty == fine). ``environment``
    is accepted for callers that want to vary messaging; the checks themselves
    are environment-independent so they can be surfaced everywhere."""
    problems: list[str] = []
    if secret == known_default:
        problems.append("uses the built-in default value")
    if len(secret) < min_length:
        problems.append(f"is shorter than {min_length} characters")
    return problems


def is_locked(locked_until: dt.datetime | None, now: dt.datetime) -> bool:
    return locked_until is not None and locked_until > now


def seconds_until(locked_until: dt.datetime | None, now: dt.datetime) -> int:
    if locked_until is None:
        return 0
    return max(0, math.ceil((locked_until - now).total_seconds()))


def register_failure(
    *,
    failed_count: int,
    last_failed_at: dt.datetime | None,
    now: dt.datetime,
    config: LockoutConfig,
) -> tuple[int, dt.datetime | None]:
    """Given the current failure state, compute the new ``(failed_count,
    locked_until)`` after one more failed attempt. Failures older than the
    window reset the counter; reaching ``max_attempts`` sets a lock."""
    if last_failed_at is None or (now - last_failed_at).total_seconds() > config.window_seconds:
        new_count = 1
    else:
        new_count = failed_count + 1
    locked_until = (
        now + dt.timedelta(seconds=config.lockout_seconds)
        if new_count >= config.max_attempts
        else None
    )
    return new_count, locked_until


def evaluate_refresh(*, found: bool, revoked: bool, expired: bool) -> str:
    """Decide what to do with a presented refresh token given its stored
    session state. A revoked-but-presented token means the token was already
    rotated — i.e. replay/theft — so the whole family should be revoked."""
    if not found:
        return REJECT
    if revoked:
        return REUSE
    if expired:
        return REJECT
    return ROTATE
