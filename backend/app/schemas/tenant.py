"""Tenant business-identity settings (industry-agnostic).

``company_name`` maps to the tenant ``name`` column and ``default_currency`` to
``base_currency`` — exposed under the spec's names without duplicating storage.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.feature_flags import merged_flags, sanitize


class TenantSettingsOut(BaseModel):
    company_name: str
    brand_name: str | None = None
    industry: str | None = None
    default_currency: str
    # Current USD -> billing-currency (e.g. ZMW) rate. Editable; represents the rate in
    # effect NOW. Snapshotted onto each sales document when issued (never retroactive).
    fx_rate: Decimal
    # Current VAT rate as a fraction (0.16 = 16%). Editable; snapshotted onto each sales
    # document when created (never retroactive).
    vat_rate: Decimal
    country: str | None = None
    timezone: str = "UTC"
    logo_url: str | None = None
    branding_colors: dict = Field(default_factory=dict)
    assistant_name: str | None = None
    assistant_prompt: str | None = None
    feature_flags: dict = Field(default_factory=dict)  # all known flags, defaults applied

    @classmethod
    def from_tenant(cls, t) -> TenantSettingsOut:
        return cls(
            company_name=t.name,
            brand_name=t.brand_name,
            industry=t.industry,
            default_currency=t.base_currency,
            fx_rate=t.fx_rate,
            vat_rate=getattr(t, "vat_rate", Decimal("0")),
            country=t.country,
            timezone=t.timezone,
            logo_url=t.logo_url,
            branding_colors=getattr(t, "branding_colors", None) or {},
            assistant_name=t.assistant_name,
            assistant_prompt=t.assistant_prompt,
            feature_flags=merged_flags(t.feature_flags),
        )


class TenantSettingsUpdate(BaseModel):
    """All fields optional — only provided fields are changed (PATCH semantics)."""

    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    brand_name: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    # Must be positive; stored at numeric(18,6). Editing affects only FUTURE documents.
    fx_rate: Decimal | None = Field(default=None, gt=0)
    # VAT rate as a fraction 0..1 (0.16 = 16%). Editing affects only FUTURE documents.
    vat_rate: Decimal | None = Field(default=None, ge=0, le=1)
    country: str | None = Field(default=None, max_length=100)
    timezone: str | None = Field(default=None, max_length=64)
    logo_url: str | None = Field(default=None, max_length=1000)
    branding_colors: dict | None = None
    assistant_name: str | None = Field(default=None, max_length=120)
    assistant_prompt: str | None = Field(default=None, max_length=4000)
    feature_flags: dict | None = None

    # column name on the Tenant model for each settings field (others match 1:1).
    _COLUMN = {"company_name": "name", "default_currency": "base_currency"}

    def to_columns(self) -> dict:
        """Map provided settings to Tenant column names (only set fields)."""
        out: dict = {}
        for field, value in self.model_dump(exclude_unset=True).items():
            col = self._COLUMN.get(field, field)
            if field == "default_currency":
                out[col] = value.upper()
            elif field == "feature_flags":
                out[col] = sanitize(value)  # keep only known flags, coerced to bool
            else:
                out[col] = value
        return out
