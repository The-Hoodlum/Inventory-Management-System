"""The search provider registry + result shapes.

A provider declares which entity it searches, the permission required to see it, and
an async ``search(session, query, limit)`` returning hits. Registration is just
appending to a module-level registry, so any module can extend global search at import
time without touching the core endpoint (open/closed).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


class SearchHit(BaseModel):
    """One result row, shaped for the UI's command palette."""

    entity: str  # machine name: 'product', 'customer', 'invoice', …
    id: str
    title: str
    subtitle: str | None = None
    badge: str | None = None  # e.g. status / SKU — rendered as a chip
    href: str  # frontend route to open the record


class SearchGroup(BaseModel):
    entity: str
    label: str  # human label, e.g. 'Products'
    hits: list[SearchHit]


class SearchResponse(BaseModel):
    query: str
    groups: list[SearchGroup]


@runtime_checkable
class SearchProvider(Protocol):
    entity: str
    label: str
    permission: str

    async def search(self, session: AsyncSession, query: str, limit: int) -> list[SearchHit]: ...


# Module-level registry. Providers append themselves (see app/search/providers.py).
_REGISTRY: list[SearchProvider] = []


def register(provider: SearchProvider) -> None:
    """Add a provider to global search. Idempotent per (entity) — re-registering an
    entity replaces the prior provider so module reloads don't duplicate results."""
    global _REGISTRY
    _REGISTRY = [p for p in _REGISTRY if p.entity != provider.entity]
    _REGISTRY.append(provider)


def unregister(entity: str) -> None:
    """Remove a provider by entity name (used in tests; harmless if absent)."""
    global _REGISTRY
    _REGISTRY = [p for p in _REGISTRY if p.entity != entity]


def registry() -> list[SearchProvider]:
    return list(_REGISTRY)
