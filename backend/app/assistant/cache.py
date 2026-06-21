"""Tiny in-process TTL cache for repeated, read-only assistant queries.

A chat user often asks the same stock question several times in a short window
(directly, or because the model re-calls a tool). Caching the result for a few
seconds removes those duplicate DB round-trips. Process-local and best-effort:
acceptable for a conversational read path where a few seconds of staleness is fine.
Keys must already be tenant-scoped (warehouse UUIDs are unique per tenant).
"""
from __future__ import annotations

import threading
import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any | None:
        with self._lock:
            hit = self._store.get(key)
            if hit is None:
                return None
            expires_at, value = hit
            if expires_at < time.monotonic():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Module-level singleton so the cache survives across requests in one process.
_stock_cache: TTLCache | None = None


def stock_cache() -> TTLCache:
    global _stock_cache
    if _stock_cache is None:
        from app.core.config import settings

        _stock_cache = TTLCache(settings.assistant_cache_ttl_seconds)
    return _stock_cache
