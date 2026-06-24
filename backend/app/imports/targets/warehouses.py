"""The "warehouses" import target: load branches / warehouses from a spreadsheet.

Each row creates or updates a Warehouse, matched by name (the key field). The
spreadsheet "Status" maps to the model's ``is_active`` flag (active -> true).
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.imports.domain.base import ImportRowContext, ResourceImporter
from app.imports.domain.fields import (
    LEVEL_ADVANCED,
    LEVEL_BASIC,
    LEVEL_STANDARD,
    FieldKind,
    FieldSpec,
    RowResult,
)
from app.imports.domain.registry import register

_ALL = (LEVEL_BASIC, LEVEL_STANDARD, LEVEL_ADVANCED)
_STD = (LEVEL_STANDARD, LEVEL_ADVANCED)

_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("name", "Warehouse Name", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("warehouse", "warehouse name", "location name", "store name", "site name", "name")),
    FieldSpec("code", "Warehouse Code", kind=FieldKind.STRING, levels=_ALL,
              aliases=("code", "warehouse code", "location code", "store code", "site code")),
    FieldSpec("branch", "Branch", kind=FieldKind.STRING, levels=_STD,
              aliases=("branch name", "region", "division", "area")),
    FieldSpec("address", "Address", kind=FieldKind.STRING, levels=_STD,
              aliases=("street", "location", "postal address", "physical address")),
    FieldSpec("warehouse_type", "Warehouse Type", kind=FieldKind.ENUM, levels=_STD,
              choices=("main", "depot", "store", "counter"),
              aliases=("type", "kind", "warehouse kind", "category")),
    FieldSpec("status", "Status", kind=FieldKind.ENUM, levels=_STD,
              choices=("active", "inactive"), aliases=("state", "active")),
)

# clean-field -> Warehouse column (name/code/status handled in process_row).
_WAREHOUSE_ATTRS = {
    "branch": "branch",
    "address": "address",
    "warehouse_type": "warehouse_type",
}


class WarehouseImporter(ResourceImporter):
    key = "warehouses"
    label = "Warehouses / Branches"
    key_field = "name"

    @property
    def fields(self) -> Sequence[FieldSpec]:
        return _FIELDS

    async def process_row(self, ctx: ImportRowContext, clean: dict[str, Any]) -> RowResult:
        name = clean["name"]
        code = (clean.get("code") or name)[:64]
        attrs: dict[str, Any] = {
            col: clean[fld] for fld, col in _WAREHOUSE_ATTRS.items() if fld in clean
        }
        if "status" in clean:
            attrs["is_active"] = clean["status"] != "inactive"
        await ctx.upsert_warehouse(key=name, code=code, attrs=attrs)
        return RowResult.imported(sku=name)


register(WarehouseImporter())
