"""Pydantic models for the order-request API."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field, field_validator

from app.order_requests.domain.status import PURPOSES


class OrderRequestLineCreate(BaseModel):
    product_id: uuid.UUID
    requested_qty: float = Field(gt=0)
    remarks: str | None = Field(default=None, max_length=500)


class OrderRequestCreate(BaseModel):
    branch_id: uuid.UUID
    destination_branch_id: uuid.UUID | None = None  # required for branch_transfer
    purpose: str
    comments: str | None = Field(default=None, max_length=1000)
    lines: list[OrderRequestLineCreate] = Field(min_length=1)

    @field_validator("purpose")
    @classmethod
    def _purpose_in_set(cls, v: str) -> str:
        if v not in PURPOSES:
            raise ValueError(f"purpose must be one of {sorted(PURPOSES)}")
        return v


class LineApproval(BaseModel):
    line_id: uuid.UUID
    approved_qty: float = Field(ge=0)


class ApproveRequest(BaseModel):
    lines: list[LineApproval] = Field(min_length=1)
    comments: str | None = Field(default=None, max_length=1000)


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class CancelRequest(BaseModel):
    """Cancel a request before issuance (by its requester or an admin). Reason optional."""
    reason: str | None = Field(default=None, max_length=1000)


class LineReceipt(BaseModel):
    line_id: uuid.UUID
    received_qty: float | None = Field(default=None, ge=0)
    missing_qty: float | None = Field(default=None, ge=0)
    damaged_qty: float | None = Field(default=None, ge=0)


class CompleteRequest(BaseModel):
    """Receipt confirmation that closes an ISSUED request. The receiving user supplies
    remarks (required) and, optionally, per-line discrepancy quantities. Completion is
    always explicit — a request is never auto-completed just because it was issued."""
    remarks: str = Field(min_length=1, max_length=1000)
    lines: list[LineReceipt] = Field(default_factory=list)


class OrderRequestLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str | None = None
    name: str | None = None
    requested_qty: float
    approved_qty: float
    issued_qty: float
    outstanding_qty: float
    received_qty: float | None = None
    missing_qty: float | None = None
    damaged_qty: float | None = None
    remarks: str | None = None


class OrderRequestOut(BaseModel):
    id: uuid.UUID
    request_number: str
    branch_id: uuid.UUID
    branch_name: str | None = None
    destination_branch_id: uuid.UUID | None = None
    destination_branch_name: str | None = None
    requested_by: uuid.UUID | None = None
    requester_name: str | None = None
    purpose: str
    status: str
    requested_date: dt.datetime
    approved_by: uuid.UUID | None = None
    approved_date: dt.datetime | None = None
    issued_by: uuid.UUID | None = None
    issued_date: dt.datetime | None = None
    completed_by: uuid.UUID | None = None
    completer_name: str | None = None
    completed_date: dt.datetime | None = None
    completion_remarks: str | None = None
    comments: str | None = None
    lines: list[OrderRequestLineOut] = []


class AuditEntryOut(BaseModel):
    action: str
    old_status: str | None = None
    new_status: str | None = None
    user_id: uuid.UUID | None = None
    created_at: dt.datetime
