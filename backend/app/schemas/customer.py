"""Customer schemas."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class CustomerAddressBase(BaseModel):
    address_type: str = Field(default="shipping", pattern="^(billing|shipping|other)$")
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    is_default: bool = False


class CustomerAddressOut(CustomerAddressBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    customer_id: uuid.UUID
    created_at: dt.datetime


class CustomerBase(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    contact_name: str | None = Field(default=None, max_length=256)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=256)
    tax_number: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, max_length=8)
    payment_terms: str | None = Field(default=None, max_length=64)
    credit_limit: float = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool = True


class CustomerCreate(CustomerBase):
    code: str | None = Field(default=None, max_length=64)  # auto-generated when omitted
    addresses: list[CustomerAddressBase] = Field(default_factory=list)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    tax_number: str | None = None
    currency: str | None = None
    payment_terms: str | None = None
    credit_limit: float | None = Field(default=None, ge=0)
    notes: str | None = None
    is_active: bool | None = None


class CustomerOut(CustomerBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    created_at: dt.datetime
    updated_at: dt.datetime
    addresses: list[CustomerAddressOut] = []


class CustomerSummaryOut(CustomerOut):
    """Customer + derived balances (outstanding from unpaid invoices)."""
    outstanding_balance: float = 0.0
    available_credit: float | None = None
