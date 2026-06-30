"""Unit tests for global-search orchestration (registry + permission gating).

No database and no global state: fake providers are passed straight to the service, so
we can assert it only queries entities the caller may see, enforces the minimum query
length, and drops empty groups. The registry's replace-by-entity rule is tested directly.
"""
from __future__ import annotations

from app.search.registry import SearchHit, register, registry, unregister
from app.search.service import SearchService


class _FakeProvider:
    def __init__(self, entity, permission, hits):
        self.entity = entity
        self.label = entity.title()
        self.permission = permission
        self._hits = hits
        self.calls = 0

    async def search(self, session, query, limit):
        self.calls += 1
        return [
            SearchHit(entity=self.entity, id=f"{self.entity}-{i}", title=f"{query}-{i}", href="/x")
            for i in range(self._hits)
        ]


async def test_only_permitted_entities_are_searched():
    allowed = _FakeProvider("product", "product.read", hits=2)
    denied = _FakeProvider("secret", "secret.read", hits=2)

    res = await SearchService(session=None).search(
        query="oil", permissions={"product.read"}, providers=[allowed, denied]
    )

    assert allowed.calls == 1 and denied.calls == 0
    assert [g.entity for g in res.groups] == ["product"]
    assert res.groups[0].hits[0].title == "oil-0"


async def test_empty_groups_are_dropped_and_short_queries_skipped():
    empty = _FakeProvider("customer", "customer.read", hits=0)

    short = await SearchService(session=None).search(
        query="a", permissions={"customer.read"}, providers=[empty]
    )
    assert short.groups == [] and empty.calls == 0  # below min length: not even called

    full = await SearchService(session=None).search(
        query="acme", permissions={"customer.read"}, providers=[empty]
    )
    assert full.groups == [] and empty.calls == 1  # called, but no hits -> group omitted


def test_register_replaces_same_entity():
    before = len(registry())
    register(_FakeProvider("temp_entity", "temp.read", hits=1))
    register(_FakeProvider("temp_entity", "temp.read", hits=9))  # replaces, not duplicates
    entities = [p.entity for p in registry()]
    assert entities.count("temp_entity") == 1
    unregister("temp_entity")  # cleanup so we don't leak into other tests in this process
    assert len(registry()) == before
