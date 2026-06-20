"""The target contract. A ``ResourceImporter`` describes an importable entity
(fields + templates) and knows how to persist one validated row through a context.

The context is a ``Protocol`` typed loosely so this module stays DB-free: the
concrete implementation (with repositories) lives in the service layer and is passed
in at runtime. Targets (e.g. inventory) subclass ``ResourceImporter``.
"""
from __future__ import annotations

import abc
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from app.imports.domain.fields import LEVEL_BASIC, LEVEL_STANDARD, FieldSpec, RowResult


@runtime_checkable
class ImportRowContext(Protocol):
    """What a target may call while persisting a row. Implemented in the service
    layer over the real repositories (with per-run caches)."""

    async def resolve_warehouse(self, name: str | None) -> Any: ...
    async def resolve_supplier(self, name: str | None) -> Any: ...
    async def get_or_create_category(self, name: str | None) -> Any: ...
    async def get_or_create_brand(self, name: str | None) -> Any: ...
    async def upsert_product(self, sku: str, fields: dict[str, Any], **links: Any) -> Any: ...
    async def set_initial_stock(self, product: Any, warehouse: Any, qty: Any, unit_cost: Any) -> None: ...


class ResourceImporter(abc.ABC):
    """Base class for an import target. ``key`` is the URL/registry key; ``fields``
    declares the columns; ``process_row`` validates+persists one row."""

    key: str
    label: str

    @property
    @abc.abstractmethod
    def fields(self) -> Sequence[FieldSpec]: ...

    def field(self, name: str) -> FieldSpec:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)

    def template_columns(self, level: str) -> list[str]:
        """Header labels for a downloadable template tier (basic/standard/advanced)."""
        order = {LEVEL_BASIC: 0, LEVEL_STANDARD: 1}
        wanted = order.get(level, 2)
        cols = []
        for f in self.fields:
            ranks = {order.get(lv, 2) for lv in f.levels}
            if ranks and min(ranks) <= wanted:
                cols.append(f.label)
        return cols

    @abc.abstractmethod
    async def process_row(self, ctx: ImportRowContext, clean: dict[str, Any]) -> RowResult:
        """Persist one already-validated row (``clean`` keyed by field name)."""
