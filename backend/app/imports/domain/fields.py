"""Field specifications and the per-row result type — the vocabulary every import
target is described in. Pure (stdlib only)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Template tiers a field can appear in (downloadable starter sheets).
LEVEL_BASIC = "basic"
LEVEL_STANDARD = "standard"
LEVEL_ADVANCED = "advanced"


class FieldKind(str, Enum):
    STRING = "string"
    INTEGER = "integer"      # whole number >= 0
    DECIMAL = "decimal"      # number >= 0 (may be fractional)
    ENUM = "enum"            # must be one of ``choices`` (case-insensitive)
    LIST = "list"            # comma-separated -> list[str]
    BOOL = "bool"            # yes/no/true/false/1/0/y/n -> bool


@dataclass(frozen=True)
class FieldSpec:
    """A single importable field. ``aliases`` drive automatic column detection;
    ``kind``/``choices`` drive validation; ``levels`` controls which downloadable
    template a field appears in."""

    name: str
    label: str
    required: bool = False
    kind: FieldKind = FieldKind.STRING
    aliases: tuple[str, ...] = ()
    choices: tuple[str, ...] = ()
    levels: tuple[str, ...] = (LEVEL_ADVANCED,)


# Per-row outcome statuses.
ROW_IMPORTED = "imported"
ROW_SKIPPED = "skipped"
ROW_ERROR = "error"


@dataclass
class RowResult:
    """Outcome of processing one source row."""

    status: str  # ROW_IMPORTED | ROW_SKIPPED | ROW_ERROR
    errors: list[str] = field(default_factory=list)
    sku: str | None = None

    @classmethod
    def imported(cls, sku: str | None = None) -> "RowResult":
        return cls(ROW_IMPORTED, sku=sku)

    @classmethod
    def skipped(cls, reason: str, sku: str | None = None) -> "RowResult":
        return cls(ROW_SKIPPED, errors=[reason], sku=sku)

    @classmethod
    def error(cls, messages: list[str], sku: str | None = None) -> "RowResult":
        return cls(ROW_ERROR, errors=list(messages), sku=sku)
