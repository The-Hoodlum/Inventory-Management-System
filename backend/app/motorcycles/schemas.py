"""Pydantic schemas for the Motorcycle module (reference catalog + unit registry)."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Layer 1: reference catalog
# --------------------------------------------------------------------------- #
class ModelCreate(BaseModel):
    # Reuse the shared brands table: pass an existing brand_id, or a brand NAME to
    # resolve-or-create (mirrors how products handle brands). Exactly one is required.
    brand_id: uuid.UUID | None = None
    brand: str | None = Field(default=None, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    category_id: uuid.UUID | None = None
    engine_cc: int | None = Field(default=None, ge=0)
    default_selling_price: float | None = Field(default=None, ge=0)
    specs: dict = Field(default_factory=dict)
    is_active: bool = True


class ModelUpdate(BaseModel):
    brand_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: uuid.UUID | None = None
    engine_cc: int | None = Field(default=None, ge=0)
    default_selling_price: float | None = Field(default=None, ge=0)
    specs: dict | None = None
    is_active: bool | None = None


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    brand_id: uuid.UUID
    brand_name: str | None = None
    name: str
    category_id: uuid.UUID | None = None
    engine_cc: int | None = None
    default_selling_price: float | None = None
    specs: dict = {}
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class VariantCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    specs: dict = Field(default_factory=dict)
    is_active: bool = True


class VariantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    specs: dict | None = None
    is_active: bool | None = None


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: uuid.UUID
    tenant_id: uuid.UUID
    model_id: uuid.UUID
    model_name: str | None = None
    name: str
    specs: dict = {}
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class ColourCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    hex_code: str | None = Field(default=None, max_length=16)
    is_active: bool = True


class ColourUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    hex_code: str | None = Field(default=None, max_length=16)
    is_active: bool | None = None


class ColourOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    hex_code: str | None = None
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


# --------------------------------------------------------------------------- #
# Layer 2: unit registry
# --------------------------------------------------------------------------- #
class UnitCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    chassis_number: str = Field(min_length=1, max_length=120)
    engine_number: str | None = Field(default=None, max_length=120)
    model_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    colour_id: uuid.UUID | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    supplier_id: uuid.UUID | None = None
    container_ref: str | None = Field(default=None, max_length=120)
    date_received: dt.date | None = None
    branch_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None
    internal_location: str | None = Field(default=None, max_length=200)
    country_of_origin: str | None = Field(default=None, max_length=120)
    selling_price: float | None = Field(default=None, ge=0)
    assembly_required: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class UnitUpdate(BaseModel):
    """Edit identity / logistics / registration / warranty fields. Lifecycle status is
    NOT edited here — it moves only through the audited transition/reserve/sell/transfer
    actions. ``version`` enables optimistic-lock checks."""
    engine_number: str | None = None
    variant_id: uuid.UUID | None = None
    colour_id: uuid.UUID | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    supplier_id: uuid.UUID | None = None
    container_ref: str | None = None
    date_received: dt.date | None = None
    warehouse_id: uuid.UUID | None = None
    internal_location: str | None = None
    country_of_origin: str | None = Field(default=None, max_length=120)
    selling_price: float | None = Field(default=None, ge=0)
    # Inspection + registration are INDEPENDENT facts, edited here (not via the lifecycle).
    inspected: bool | None = None
    registered: bool | None = None
    registration_number: str | None = None
    registration_papers_received: bool | None = None
    warranty_start: dt.date | None = None
    warranty_end: dt.date | None = None
    notes: str | None = None
    version: int | None = None


class TransitionIn(BaseModel):
    to_status: str
    note: str | None = None
    # Required when moving to on_hold (why it's held).
    hold_reason: str | None = Field(default=None, max_length=500)


class ReserveIn(BaseModel):
    customer_id: uuid.UUID
    sales_order_id: uuid.UUID | None = None
    note: str | None = None


class SellIn(BaseModel):
    invoice_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    price_charged: float | None = Field(default=None, ge=0)
    note: str | None = None
    # Only relevant when the unit is sold BEFORE assembly: True (default) = the dealership
    # must assemble it before delivery (queued + delivery blocked); False = the buyer
    # assembles it (e.g. a reseller), so it ships as-is.
    assembly_required: bool = True


class AssembleIn(BaseModel):
    """Mark a unit assembled — records the assembly (independent of the sale status), so it
    works for a unit sold before assembly as well as one still in stock."""
    note: str | None = None


class TransferIn(BaseModel):
    to_branch_id: uuid.UUID
    to_warehouse_id: uuid.UUID | None = None
    internal_location: str | None = None
    note: str | None = None


class MetricsOut(BaseModel):
    """Dashboard roll-up of the unit registry (tenant-scoped; optionally one branch)."""

    total: int = 0
    in_stock: int = 0
    reserved: int = 0
    sold: int = 0
    cancelled: int = 0
    by_status: dict[str, int] = {}
    # Assembly axis (independent of sale status).
    waiting_for_assembly: int = 0     # sold before assembly, assembly still owed
    unassembled_in_stock: int = 0     # on hand, not yet assembled
    avg_assembly_days: float | None = None   # avg receipt -> assembly lead time


class UnitEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    from_branch_id: uuid.UUID | None = None
    from_branch_name: str | None = None
    to_branch_id: uuid.UUID | None = None
    to_branch_name: str | None = None
    reference_type: str | None = None
    reference_id: uuid.UUID | None = None
    note: str | None = None
    user_id: uuid.UUID | None = None
    created_at: dt.datetime


class UnitOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    id: uuid.UUID
    chassis_number: str
    engine_number: str | None = None
    model_id: uuid.UUID
    model_name: str | None = None
    variant_id: uuid.UUID | None = None
    variant_name: str | None = None
    colour_id: uuid.UUID | None = None
    colour_name: str | None = None
    year: int | None = None
    supplier_id: uuid.UUID | None = None
    supplier_name: str | None = None
    container_ref: str | None = None
    date_received: dt.date | None = None
    branch_id: uuid.UUID | None = None
    branch_name: str | None = None
    warehouse_id: uuid.UUID | None = None
    warehouse_name: str | None = None
    internal_location: str | None = None
    country_of_origin: str | None = None
    status: str                      # one of the five sale statuses
    inspected: bool                  # independent of status
    hold_reason: str | None = None   # set while on_hold; kept for history after
    reserved_ref: uuid.UUID | None = None
    reserved_so_number: str | None = None
    sold_ref: uuid.UUID | None = None
    sold_invoice_number: str | None = None
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    selling_price: float | None = None
    price_charged: float | None = None
    payment_status: str
    registered: bool                 # independent of status
    registration_number: str | None = None
    registration_papers_received: bool
    warranty_start: dt.date | None = None
    warranty_end: dt.date | None = None
    assembled_date: dt.date | None = None
    # Assembly is independent of the sale status: assembled_date is when it was assembled;
    # assembly_pending = sold before assembly, dealership owes assembly before delivery.
    assembly_pending: bool = False
    date_sold: dt.date | None = None
    imported_historical: bool = False
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    allowed_next: list[str] = []
    events: list[UnitEventOut] = []


# ----------------------- stock reorder points (per model/colour) ------------ #
class ReorderPointIn(BaseModel):
    model_id: uuid.UUID
    colour_id: uuid.UUID | None = None      # None = the model-wide default
    reorder_point: int = Field(ge=0)


class ReorderPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    model_id: uuid.UUID
    model_name: str | None = None
    colour_id: uuid.UUID | None
    colour_name: str | None = None
    reorder_point: int


class LowStockBikeOut(BaseModel):
    model_id: uuid.UUID
    model: str | None = None
    colour_id: uuid.UUID | None = None
    colour: str | None = None
    branch_id: uuid.UUID | None = None
    branch: str | None = None
    available: int
    reorder_point: int
