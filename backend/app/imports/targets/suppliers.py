"""The "suppliers" import target: load a supplier master list from a spreadsheet.

Each row creates or updates a Supplier, matched by name (the key field). Column
aliases drive auto-detection (e.g. Name ← "Vendor", Phone ← "Telephone").
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
_ADV = (LEVEL_ADVANCED,)

_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("name", "Supplier Name", required=True, kind=FieldKind.STRING, levels=_ALL,
              aliases=("supplier", "supplier name", "vendor", "vendor name", "company", "name")),
    FieldSpec("code", "Supplier Code", kind=FieldKind.STRING, levels=_ALL,
              aliases=("code", "supplier code", "vendor code", "supplier id", "vendor id")),
    FieldSpec("contact_person", "Contact Person", kind=FieldKind.STRING, levels=_STD,
              aliases=("contact", "contact name", "attention", "rep", "salesperson")),
    FieldSpec("phone", "Phone", kind=FieldKind.STRING, levels=_STD,
              aliases=("telephone", "tel", "mobile", "phone number", "contact number")),
    FieldSpec("email", "Email", kind=FieldKind.STRING, levels=_STD,
              aliases=("e-mail", "email address", "mail")),
    FieldSpec("address", "Address", kind=FieldKind.STRING, levels=_STD,
              aliases=("street", "location", "postal address", "physical address")),
    FieldSpec("country", "Country", kind=FieldKind.STRING, levels=_STD,
              aliases=("nation", "country name")),
    FieldSpec("currency", "Currency", kind=FieldKind.STRING, levels=_ADV,
              aliases=("ccy", "currency code")),
    FieldSpec("payment_terms", "Payment Terms", kind=FieldKind.STRING, levels=_ADV,
              aliases=("terms", "payment", "credit terms", "payment term")),
    FieldSpec("lead_time_days", "Lead Time (Days)", kind=FieldKind.INTEGER, levels=_ADV,
              aliases=("lead time", "leadtime", "lt days", "lead time days", "default lead time")),
    FieldSpec("status", "Status", kind=FieldKind.ENUM, levels=_ADV,
              choices=("active", "inactive"), aliases=("state",)),
)

# clean-field -> Supplier column. ``name`` is the key (passed separately); ``currency``
# is validated below. Only keys present in the validated row are applied.
_SUPPLIER_ATTRS = {
    "code": "code",
    "contact_person": "contact_person",
    "phone": "phone",
    "email": "email",
    "address": "address",
    "country": "country",
    "payment_terms": "payment_terms",
    "lead_time_days": "default_lead_time_days",
    "status": "status",
}


def _currency(raw: Any) -> str | None:
    s = str(raw or "").strip().upper()
    return s if len(s) == 3 and s.isalpha() else None


class SupplierImporter(ResourceImporter):
    key = "suppliers"
    label = "Suppliers"
    key_field = "name"

    @property
    def fields(self) -> Sequence[FieldSpec]:
        return _FIELDS

    async def process_row(self, ctx: ImportRowContext, clean: dict[str, Any]) -> RowResult:
        name = clean["name"]
        attrs: dict[str, Any] = {
            col: clean[fld] for fld, col in _SUPPLIER_ATTRS.items() if fld in clean
        }
        cur = _currency(clean.get("currency"))
        if cur is not None:
            attrs["currency"] = cur
        await ctx.upsert_supplier(key=name, attrs=attrs)
        return RowResult.imported(sku=name)


register(SupplierImporter())
