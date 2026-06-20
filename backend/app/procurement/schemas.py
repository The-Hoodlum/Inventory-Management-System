"""API schemas for purchase-order management and goods receiving."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --------------------------------- requests --------------------------------- #
class POLineCreate(BaseModel):
    product_id: uuid.UUID
    ordered_qty: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    units_per_carton: int | None = Field(default=None, ge=1)
    ordered_cartons: int | None = Field(default=None, ge=0)


class POCreate(BaseModel):
    supplier_id: uuid.UUID
    warehouse_id: uuid.UUID
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    fx_rate: Decimal | None = Field(default=None, gt=0)
    expected_date: dt.date | None = None
    notes: str | None = None
    lines: list[POLineCreate] = Field(min_length=1)


class POUpdate(BaseModel):
    """Edit a draft PO. Any provided field replaces the current value; passing
    ``lines`` replaces the entire set of lines."""

    currency: str | None = Field(default=None, min_length=3, max_length=3)
    fx_rate: Decimal | None = Field(default=None, gt=0)
    expected_date: dt.date | None = None
    notes: str | None = None
    lines: list[POLineCreate] | None = Field(default=None, min_length=1)


class POActionRequest(BaseModel):
    """Body for submit / approve / reject / cancel / send."""

    comment: str | None = None


class ReceiptLineIn(BaseModel):
    line_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class ReceiveRequest(BaseModel):
    lines: list[ReceiptLineIn] = Field(min_length=1)
    note: str | None = None


class EmailPORequest(BaseModel):
    to: EmailStr | None = Field(default=None, description="Override the supplier email")
    cc: list[EmailStr] = []


# --------------------------------- responses -------------------------------- #
class POLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    ordered_qty: Decimal
    ordered_cartons: int | None
    unit_cost: Decimal
    line_total: Decimal
    received_qty: Decimal
    remaining_qty: Decimal


class POOut(BaseModel):
    id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    warehouse_id: uuid.UUID
    status: str
    currency: str
    fx_rate: Decimal
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    notes: str | None
    order_date: dt.datetime
    expected_date: dt.date | None
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    approved_at: dt.datetime | None
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    lines: list[POLineOut] = []


class POEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    po_id: uuid.UUID
    action: str
    from_status: str | None
    to_status: str | None
    comment: str | None
    detail: dict | None
    actor_id: uuid.UUID | None
    created_at: dt.datetime


class ReceiptResult(BaseModel):
    purchase_order: POOut
    received_now: Decimal
    fully_received: bool
    movements_created: int


class EmailResult(BaseModel):
    sent: bool
    detail: str
