"""Pydantic schemas for bike issues (internal repairs that consume spare parts)."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


# ------------------------------- input ------------------------------------- #
class RepairLineIn(BaseModel):
    """One spare part consumed to fix the bike: the fungible product, the source
    location it comes from, and how many. Deducted through InventoryService at resolve."""

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: float = Field(gt=0)
    remarks: str | None = Field(default=None, max_length=500)


class BikeIssueCreate(BaseModel):
    unit_id: uuid.UUID
    problem_description: str = Field(min_length=1, max_length=2000)
    reported_at: dt.datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)
    # Optional parts planned at open time. Nothing is deducted until resolve.
    lines: list[RepairLineIn] = []


class BikeIssueResolve(BaseModel):
    """Resolve the issue: COMMIT the part consumption and release the bike. Any lines
    passed here are appended to the issue before the consumption runs."""

    resolution_note: str | None = Field(default=None, max_length=2000)
    lines: list[RepairLineIn] = []


class BikeIssueStatusIn(BaseModel):
    status: str = Field(pattern="^(open|in_repair)$")


# ------------------------------- output ------------------------------------ #
class RepairLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str | None = None
    name: str | None = None
    warehouse_id: uuid.UUID
    warehouse_name: str | None = None
    quantity: float
    consumed: bool
    consumed_at: dt.datetime | None = None
    remarks: str | None = None


class BikeIssueOut(BaseModel):
    id: uuid.UUID
    issue_number: str
    status: str
    unit_id: uuid.UUID
    chassis_number: str
    engine_number: str | None = None
    model_name: str | None = None
    branch_id: uuid.UUID | None = None
    branch_name: str | None = None
    prior_status: str
    problem_description: str
    reported_at: dt.datetime
    reported_by: uuid.UUID | None = None
    resolved_at: dt.datetime | None = None
    resolved_by: uuid.UUID | None = None
    resolution_note: str | None = None
    notes: str | None = None
    created_at: dt.datetime
    lines: list[RepairLineOut] = []
