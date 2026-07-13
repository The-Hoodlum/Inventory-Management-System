"""Warehouse schemas."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class WarehouseBase(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    address: str | None = None
    branch_id: uuid.UUID | None = None
    is_active: bool = True


class WarehouseCreate(WarehouseBase):
    # A location (warehouse/room/showroom/depot) lives INSIDE a branch — the parent branch
    # is required at creation so a location can never be created as, or mistaken for, a
    # branch. (Bulk imports build Warehouse rows directly and are unaffected.)
    branch_id: uuid.UUID


class WarehouseUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=256)
    address: str | None = None
    branch_id: uuid.UUID | None = None
    is_active: bool | None = None


class WarehouseOut(WarehouseBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: dt.datetime
