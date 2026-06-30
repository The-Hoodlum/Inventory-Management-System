"""Global-search orchestration: fan a query across the registered providers the caller
is permitted to see, and return non-empty groups. Tenant isolation is enforced by RLS
on the request session; provider-level permissions gate WHICH entities are searched.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

# Import for its registration side effect (providers append themselves to the registry).
from app.search import providers as _providers  # noqa: F401
from app.search.registry import SearchGroup, SearchProvider, SearchResponse, registry

MIN_QUERY_LEN = 2


class SearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        *,
        query: str,
        permissions: set[str],
        limit_per_entity: int = 5,
        providers: list[SearchProvider] | None = None,
    ) -> SearchResponse:
        """Fan ``query`` across the permitted providers. ``providers`` defaults to the
        global registry; tests pass an explicit list so they never mutate global state."""
        q = (query or "").strip()
        if len(q) < MIN_QUERY_LEN:
            return SearchResponse(query=q, groups=[])
        groups: list[SearchGroup] = []
        for provider in providers if providers is not None else registry():
            if provider.permission not in permissions:
                continue
            hits = await provider.search(self.session, q, limit_per_entity)
            if hits:
                groups.append(SearchGroup(entity=provider.entity, label=provider.label, hits=hits))
        return SearchResponse(query=q, groups=groups)
