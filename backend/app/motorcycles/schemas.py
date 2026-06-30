"""Request/response schemas for the motorcycle (serialized-unit) registry."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


# ------------------------------- requests --------------------------------- #
class MotorcycleUnitCreate(BaseModel):
    chassis_number: str = Field(min_length=1, max_length=120)
    engine_number: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=200)
    variant: str | None = Field(default=None, max_length=200)
    colour: str | None = Field(default=None, max_length=120)
    year: int | None = Field(default=None, ge=1900, le=2200)
    supplier_id: uuid.UUID | None = None
    container_ref: str | None = Field(default=None, max_length=200)
    date_received: dt.date | None = None
    branch_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None
    internal_location: str | None = Field(default=None, max_length=200)
    selling_price: float = Field(default=0, ge=0)
    assembly_required: bool = False  # sets assembly_status; status still starts at 'received'
    notes: str | None = Field(default=None, max_length=2000)


class MotorcycleUnitUpdate(BaseModel):
    """PATCH semantics — only provided fields change. Excludes lifecycle status,
    reservation/sale linkage (use the dedicated actions). Carries the optimistic
    ``version`` the client last read."""

    engine_number: str | None = None
    model: str | None = None
    variant: str | None = None
    colour: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    supplier_id: uuid.UUID | None = None
    container_ref: str | None = None
    warehouse_id: uuid.UUID | None = None
    internal_location: str | None = None
    selling_price: float | None = Field(default=None, ge=0)
    inspection_status: str | None = Field(default=None, pattern="^(pending|passed|failed)$")
    assembly_status: str | None = Field(default=None, pattern="^(not_required|required|in_progress|done)$")
    registration_status: str | None = Field(default=None, pattern="^(unregistered|pending|registered)$")
    registration_number: str | None = None
    registration_papers_received: bool | None = None
    warranty_start: dt.date | None = None
    warranty_end: dt.date | None = None
    notes: str | None = None
    version: int | None = None


class TransitionIn(BaseModel):
    to_status: str
    note: str | None = Field(default=None, max_length=1000)


class ReserveIn(BaseModel):
    customer_id: uuid.UUID
    sales_order_id: uuid.UUID | None = None  # link to the existing sales order, if any
    note: str | None = Field(default=None, max_length=1000)


class SellIn(BaseModel):
    invoice_id: uuid.UUID  # the existing sales invoice that sold this unit
    customer_id: uuid.UUID | None = None  # defaults to the invoice's customer
    price_charged: float | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=1000)


class TransferIn(BaseModel):
    to_branch_id: uuid.UUID
    to_warehouse_id: uuid.UUID | None = None
    internal_location: str | None = None
    note: str | None = Field(default=None, max_length=1000)


# ------------------------------- responses -------------------------------- #
class UnitEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    from_branch_id: uuid.UUID | None
    from_branch_name: str | None
    to_branch_id: uuid.UUID | None
    to_branch_name: str | None
    reference_type: str | None
    reference_id: uuid.UUID | None
    note: str | None
    user_id: uuid.UUID | None
    created_at: dt.datetime


class MotorcycleUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chassis_number: str
    engine_number: str | None
    model: str | None
    variant: str | None
    colour: str | None
    year: int | None
    supplier_id: uuid.UUID | None
    supplier_name: str | None = None
    container_ref: str | None
    date_received: dt.date | None
    branch_id: uuid.UUID | None
    branch_name: str | None = None
    warehouse_id: uuid.UUID | None
    warehouse_name: str | None = None
    internal_location: str | None
    status: str
    inspection_status: str
    assembly_status: str
    reserved: bool
    reserved_sales_order_id: uuid.UUID | None
    so_number: str | None = None
    sold: bool
    invoice_id: uuid.UUID | None
    invoice_number: str | None = None
    customer_id: uuid.UUID | None
    customer_name: str | None = None
    selling_price: float
    price_charged: float
    payment_status: str
    registration_status: str
    registration_number: str | None
    registration_papers_received: bool
    warranty_start: dt.date | None
    warranty_end: dt.date | None
    notes: str | None
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    allowed_next: list[str] = []
    events: list[UnitEventOut] = []
