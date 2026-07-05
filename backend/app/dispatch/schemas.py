"""Pydantic schemas for typed delivery / dispatch notes (Type 1: warehouse->branch)."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field, model_validator


# ------------------------------- create ------------------------------------ #
class DispatchPartLineIn(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0)
    remarks: str | None = Field(default=None, max_length=500)


class DispatchBikeLineIn(BaseModel):
    unit_id: uuid.UUID
    remarks: str | None = Field(default=None, max_length=500)


class DispatchNoteCreate(BaseModel):
    dispatch_type: str = Field(default="warehouse_branch_transfer")
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    remarks: str | None = Field(default=None, max_length=2000)
    part_lines: list[DispatchPartLineIn] = []
    bike_lines: list[DispatchBikeLineIn] = []

    @model_validator(mode="after")
    def _at_least_one_line(self) -> DispatchNoteCreate:
        if not self.part_lines and not self.bike_lines:
            raise ValueError("A delivery note needs at least one line (a bike or a part).")
        return self


# ------------------------------- receive ----------------------------------- #
class ReceivePartLineIn(BaseModel):
    line_id: uuid.UUID
    received_qty: float = Field(ge=0)
    damaged_qty: float = Field(default=0, ge=0)


class ReceiveBikeLineIn(BaseModel):
    line_id: uuid.UUID
    received: bool  # True = this chassis arrived; False = missing


class DispatchReceive(BaseModel):
    """Confirm receipt. Any line omitted is received in full. Part lines may report a
    short/damaged quantity; bike lines confirm per chassis."""
    received_by: str | None = Field(default=None, max_length=256)
    remarks: str | None = Field(default=None, max_length=2000)
    part_lines: list[ReceivePartLineIn] = []
    bike_lines: list[ReceiveBikeLineIn] = []


class CancelBody(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


# ------------------------------- output ------------------------------------ #
class DispatchLineOut(BaseModel):
    id: uuid.UUID
    line_kind: str
    product_id: uuid.UUID | None = None
    sku: str | None = None
    name: str | None = None
    unit_id: uuid.UUID | None = None
    chassis_number: str | None = None
    engine_number: str | None = None
    model_name: str | None = None
    dispatched_qty: float
    received_qty: float
    missing_qty: float
    damaged_qty: float
    remarks: str | None = None


class DispatchNoteOut(BaseModel):
    id: uuid.UUID
    note_number: str
    dispatch_type: str
    status: str
    from_branch_id: uuid.UUID | None = None
    from_branch_name: str | None = None
    from_warehouse_id: uuid.UUID
    from_warehouse_name: str | None = None
    to_branch_id: uuid.UUID | None = None
    to_branch_name: str | None = None
    to_warehouse_id: uuid.UUID
    to_warehouse_name: str | None = None
    remarks: str | None = None
    dispatched_by: uuid.UUID | None = None
    dispatched_at: dt.datetime | None = None
    received_by: str | None = None
    received_at: dt.datetime | None = None
    created_at: dt.datetime
    lines: list[DispatchLineOut] = []
