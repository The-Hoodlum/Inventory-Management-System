"""Pydantic schemas for internal issuance / handover (out-and-back loan)."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field, model_validator

from app.issuance.domain import status as S


# ------------------------------- create ------------------------------------ #
class IssuePartLineIn(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0)
    returnable: bool = True
    consumable: bool = False  # non-returnable: deducted at handover, not expected back
    remarks: str | None = Field(default=None, max_length=500)


class IssueBikeLineIn(BaseModel):
    unit_id: uuid.UUID
    odometer_out: float | None = Field(default=None, ge=0)
    fuel_out: str | None = Field(default=None, max_length=64)
    accessories: str | None = Field(default=None, max_length=500)
    remarks: str | None = Field(default=None, max_length=500)


class IssuanceCreate(BaseModel):
    warehouse_id: uuid.UUID
    requestor: str | None = Field(default=None, max_length=256)
    department: str | None = Field(default=None, max_length=256)
    purpose: str | None = Field(default=None, max_length=500)
    expected_return_date: dt.date | None = None
    remarks: str | None = Field(default=None, max_length=2000)
    part_lines: list[IssuePartLineIn] = []
    bike_lines: list[IssueBikeLineIn] = []

    @model_validator(mode="after")
    def _at_least_one_line(self) -> IssuanceCreate:
        if not self.part_lines and not self.bike_lines:
            raise ValueError("An issuance needs at least one line (a bike or an item).")
        return self


# ------------------------------- return ------------------------------------ #
class ReturnPartLineIn(BaseModel):
    line_id: uuid.UUID
    returned_qty: float = Field(ge=0)


class ReturnBikeLineIn(BaseModel):
    line_id: uuid.UUID
    condition: str = Field(pattern=f"^({S.GOOD}|{S.FAIR}|{S.NEEDS_ATTENTION})$")
    odometer_in: float | None = Field(default=None, ge=0)
    return_note: str | None = Field(default=None, max_length=500)


class IssuanceReturn(BaseModel):
    """Record a return. Any line omitted is returned in full / clean. A part short of
    its issued qty flags the missing as a loss; a 'needs_attention' bike routes to hold."""
    remarks: str | None = Field(default=None, max_length=2000)
    part_lines: list[ReturnPartLineIn] = []
    bike_lines: list[ReturnBikeLineIn] = []


class CancelBody(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


# ------------------------------- output ------------------------------------ #
class IssuanceLineOut(BaseModel):
    id: uuid.UUID
    line_kind: str
    product_id: uuid.UUID | None = None
    sku: str | None = None
    name: str | None = None
    unit_id: uuid.UUID | None = None
    chassis_number: str | None = None
    engine_number: str | None = None
    model_name: str | None = None
    qty: float
    returnable: bool
    consumable: bool
    odometer_out: float | None = None
    fuel_out: str | None = None
    accessories: str | None = None
    returned_qty: float
    missing_qty: float
    condition: str | None = None
    odometer_in: float | None = None
    return_note: str | None = None
    returned_at: dt.datetime | None = None
    remarks: str | None = None


class IssuanceOut(BaseModel):
    id: uuid.UUID
    issuance_number: str
    status: str
    branch_id: uuid.UUID | None = None
    branch_name: str | None = None
    warehouse_id: uuid.UUID
    warehouse_name: str | None = None
    requestor: str | None = None
    department: str | None = None
    purpose: str | None = None
    expected_return_date: dt.date | None = None
    overdue: bool = False
    remarks: str | None = None
    issued_by: uuid.UUID | None = None
    issued_at: dt.datetime | None = None
    closed_at: dt.datetime | None = None
    created_at: dt.datetime
    lines: list[IssuanceLineOut] = []
