"""Atomic import contract — for targets that must be all-or-nothing rather than the
default per-row-isolated streaming import.

A serialized registry (e.g. motorcycle units) cannot half-create: the whole batch is
validated up front, new reference values are surfaced for explicit confirmation
(never created silently), and the commit either writes every row or nothing. Targets
opting into this set ``atomic = True`` and implement ``plan`` + ``commit``. The import
service routes such targets through a single-transaction path; the default streaming
path (per-row SAVEPOINT + background runner) is unchanged for every other target.

Kept DB-free: ``session`` is typed loosely (the concrete target builds its own
repository over it).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from app.imports.domain.base import ResourceImporter


@dataclass(frozen=True)
class NewRef:
    """A reference value found in the file that does not yet exist and would be
    created on confirm. ``kind`` is model/variant/colour/supplier; ``value`` is the
    display label (a variant is shown as ``Model / Variant`` since it is model-scoped)."""

    kind: str
    value: str
    count: int = 1


@dataclass
class RowPlan:
    """One source row's outcome after full validation. ``data`` holds the resolved,
    ready-to-persist payload and is set only when ``errors`` is empty."""

    row_number: int
    key: str | None
    errors: list[str] = field(default_factory=list)
    data: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ValueOption:
    """A distinct sheet value (status / model / colour) that did not exactly match a
    system value and needs a map/create decision. ``suggestion`` (+ a model batch
    ``suggested_consignment``) pre-fills the UI; ``can_create`` is False for statuses."""

    kind: str
    value: str
    count: int = 1
    suggestion: str | None = None
    suggested_consignment: str | None = None
    can_create: bool = False


@dataclass
class ImportPlan:
    """The validated batch: per-row outcomes, the distinct new reference values the batch
    would create, and the distinct values that still need a map/create decision."""

    rows: list[RowPlan] = field(default_factory=list)
    new_refs: list[NewRef] = field(default_factory=list)
    value_options: list[ValueOption] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.rows if r.ok)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.rows if not r.ok)

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0


# Input handed to ``plan``: (row_number, coerced field values, field-level errors).
RowInput = tuple[int, dict[str, Any], list[str]]


class AtomicImporter(ResourceImporter):
    """A target imported all-or-nothing with explicit new-reference confirmation."""

    atomic: bool = True

    @abc.abstractmethod
    async def plan(
        self, session: Any, *, tenant_id: Any, rows: list[RowInput], options: Any = None
    ) -> ImportPlan:
        """Validate the whole batch WITHOUT writing: cross-row + cross-DB uniqueness,
        consistency, and reference resolution. ``options`` carries the user's value-map
        decisions (see ImportOptions.value_maps). Return per-row outcomes, the distinct
        NEW reference values the batch would create, and the distinct values still needing
        a map/create decision. A row that only references a new (yet-to-be-created) value
        is NOT an error — the new value is surfaced for confirmation and the row commits
        once it is created; only genuine problems (dupes, unmatched branch, missing
        required, inconsistent sale fields, bad dates, an unmapped status) are row
        errors."""

    @abc.abstractmethod
    async def commit(
        self, session: Any, *, tenant_id: Any, user_id: Any, job_id: Any, plan: ImportPlan
    ) -> int:
        """Persist every row of an error-free plan (creating confirmed new references
        first) and return the number of records created. Called inside a SAVEPOINT the
        service rolls back wholesale on any failure."""
