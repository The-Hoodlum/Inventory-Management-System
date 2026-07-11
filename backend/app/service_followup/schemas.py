"""Pydantic schemas for the service follow-up module."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from app.service_followup.domain.schedule import USAGE_PROFILES


# ------------------------------- follow-up list ---------------------------- #
class FollowUpRow(BaseModel):
    """One sold bike on the follow-up list, with its computed next service."""

    unit_id: uuid.UUID
    chassis_number: str
    model_id: uuid.UUID
    model_name: str | None = None
    colour_name: str | None = None
    branch_id: uuid.UUID | None = None
    branch_name: str | None = None
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    date_sold: dt.date | None = None
    service_usage: str
    services_done: int
    last_service_date: dt.date | None = None
    # Next service (None only when the sale has no date to count from).
    next_sequence: int | None = None
    next_label: str | None = None
    next_due_date: dt.date | None = None
    days_until_due: int | None = None
    status: str | None = None  # overdue / due_soon / upcoming / null


class FollowUpKpis(BaseModel):
    overdue: int = 0
    due_soon: int = 0
    upcoming: int = 0
    total: int = 0


class FollowUpPage(BaseModel):
    items: list[FollowUpRow] = []
    page: int
    page_size: int
    total: int
    total_pages: int
    kpis: FollowUpKpis


# ------------------------------- service records --------------------------- #
class ServiceRecordCreate(BaseModel):
    service_date: dt.date
    note: str | None = None
    # Optional override of which service this is; defaults to the next in the schedule.
    sequence: int | None = Field(default=None, ge=1)


class ServiceRecordOut(BaseModel):
    id: uuid.UUID
    unit_id: uuid.UUID
    sequence: int
    label: str | None = None
    service_date: dt.date
    note: str | None = None
    performed_by: uuid.UUID | None = None
    created_at: dt.datetime


class UsageUpdate(BaseModel):
    service_usage: str = Field(description=f"One of {', '.join(USAGE_PROFILES)}.")


# ------------------------------- schedule (plans) -------------------------- #
class StageIn(BaseModel):
    label: str | None = None
    interval_days: int = Field(ge=1, description="Gap in days from the previous service.")


class StageOut(BaseModel):
    sequence: int
    label: str
    interval_days: int


class ServicePlanIn(BaseModel):
    """Set the schedule for a model (model_id omitted = the tenant-wide default)."""

    model_id: uuid.UUID | None = None
    stages: list[StageIn] = Field(min_length=1)


class ServicePlanOut(BaseModel):
    id: uuid.UUID | None = None  # None for the synthesised module default
    model_id: uuid.UUID | None = None
    model_name: str | None = None
    is_default: bool = False       # true for the tenant/module default row
    is_module_default: bool = False  # true when falling back to code (no stored row)
    stages: list[StageOut] = []


class ServicePlansOut(BaseModel):
    plans: list[ServicePlanOut] = []
    module_default: ServicePlanOut
    usage_multipliers: dict[str, float]
