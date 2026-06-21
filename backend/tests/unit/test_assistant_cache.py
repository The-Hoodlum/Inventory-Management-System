"""The assistant's tiny TTL cache."""
from __future__ import annotations

import time

from app.assistant.cache import TTLCache


def test_set_then_get_returns_value():
    c = TTLCache(ttl_seconds=10)
    c.set(("stock", "hlx", ()), {"items": [1, 2]})
    assert c.get(("stock", "hlx", ())) == {"items": [1, 2]}


def test_miss_returns_none():
    c = TTLCache(ttl_seconds=10)
    assert c.get(("nope",)) is None


def test_entry_expires():
    c = TTLCache(ttl_seconds=0.05)
    c.set("k", "v")
    assert c.get("k") == "v"
    time.sleep(0.06)
    assert c.get("k") is None


def test_clear_empties_cache():
    c = TTLCache(ttl_seconds=10)
    c.set("k", "v")
    c.clear()
    assert c.get("k") is None
