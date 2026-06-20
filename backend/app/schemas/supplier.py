"""Supplier schemas."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SupplierStatus = Literal["active", "inactive"]


class SupplierBase(BaseModel):
    name: str = Field(min_length=1, max_length=512)
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    country: str | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    payment_terms: str | None = None
    default_lead_time_days: int = Field(default=30, ge=0)
    status: SupplierStatus = "active"


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=512)
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    country: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    payment_terms: str | None = None
    default_lead_time_days: int | None = Field(default=None, ge=0)
    status: SupplierStatus | None = None


class SupplierOut(SupplierBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime
