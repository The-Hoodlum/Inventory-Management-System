"""Tenant business-identity settings (industry-agnostic).

``company_name`` maps to the tenant ``name`` column and ``default_currency`` to
``base_currency`` — exposed under the spec's names without duplicating storage.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TenantSettingsOut(BaseModel):
    company_name: str
    brand_name: str | None = None
    industry: str | None = None
    default_currency: str
    country: str | None = None
    timezone: str = "UTC"
    logo_url: str | None = None
    assistant_name: str | None = None
    assistant_prompt: str | None = None
    feature_flags: dict = Field(default_factory=dict)

    @classmethod
    def from_tenant(cls, t) -> TenantSettingsOut:
        return cls(
            company_name=t.name,
            brand_name=t.brand_name,
            industry=t.industry,
            default_currency=t.base_currency,
            country=t.country,
            timezone=t.timezone,
            logo_url=t.logo_url,
            assistant_name=t.assistant_name,
            assistant_prompt=t.assistant_prompt,
            feature_flags=t.feature_flags or {},
        )


class TenantSettingsUpdate(BaseModel):
    """All fields optional — only provided fields are changed (PATCH semantics)."""

    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    brand_name: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    country: str | None = Field(default=None, max_length=100)
    timezone: str | None = Field(default=None, max_length=64)
    logo_url: str | None = Field(default=None, max_length=1000)
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
            out[col] = value.upper() if field == "default_currency" else value
        return out
