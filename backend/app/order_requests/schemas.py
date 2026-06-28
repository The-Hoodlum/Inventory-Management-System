"""Pydantic models for the order-request / stock-transfer API.

Naming note: the DB columns ``branch_id`` and ``destination_branch_id`` historically
hold LOCATION (warehouse) ids. They are kept for back-compat; the response also
exposes explicit ``source_*`` / ``dest_*`` branch + location fields (the branch is
each location's ``warehouses.branch_id``).
"""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field, field_validator, model_validator

from app.order_requests.domain.status import PURPOSES


class OrderRequestLineCreate(BaseModel):
    product_id: uuid.UUID
    requested_qty: float = Field(gt=0)
    remarks: str | None = Field(default=None, max_length=500)


class OrderRequestCreate(BaseModel):
    branch_id: uuid.UUID  # SOURCE location (warehouse)
    destination_branch_id: uuid.UUID | None = None  # DESTINATION location (warehouse); required for transfers
    purpose: str  # transfer type
    comments: str | None = Field(default=None, max_length=1000)  # reason
    submit: bool = True  # False => save as draft (not yet submitted for approval)
    lines: list[OrderRequestLineCreate] = Field(min_length=1)

    @field_validator("purpose")
    @classmethod
    def _purpose_in_set(cls, v: str) -> str:
        if v not in PURPOSES:
            raise ValueError(f"purpose must be one of {sorted(PURPOSES)}")
        return v

    @model_validator(mode="after")
    def _transfer_needs_reason(self) -> OrderRequestCreate:
        # A transfer (has a destination location) must record a reason and cannot be
        # a no-op move onto itself.
        if self.destination_branch_id is not None:
            if self.destination_branch_id == self.branch_id:
                raise ValueError("Source and destination locations must differ.")
            if not (self.comments and self.comments.strip()):
                raise ValueError("A reason is required for a transfer.")
        return self


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


class LineIssue(BaseModel):
    """Optional per-line issue quantity for a partial issue (defaults to the full
    approved quantity when omitted)."""
    line_id: uuid.UUID
    issue_qty: float = Field(ge=0)


class IssueRequest(BaseModel):
    lines: list[LineIssue] = Field(default_factory=list)


class LineReceipt(BaseModel):
    line_id: uuid.UUID
    received_qty: float | None = Field(default=None, ge=0)
    missing_qty: float | None = Field(default=None, ge=0)
    damaged_qty: float | None = Field(default=None, ge=0)
    extra_qty: float | None = Field(default=None, ge=0)


class ReceiveRequest(BaseModel):
    """Capture a receipt for an issued transfer: per-line received/missing/damaged/extra.
    The reconciliation invariant (received + missing + damaged = issued + extra) is
    enforced in the service (it needs each line's issued qty) and by a DB CHECK."""
    remarks: str | None = Field(default=None, max_length=1000)
    lines: list[LineReceipt] = Field(min_length=1)


class CompleteRequest(BaseModel):
    """Confirm receipt and close a transfer. Accepts optional per-line receipt (so a
    simple requisition can receive + close in one step); always explicit — issuing
    never auto-completes."""
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
    extra_qty: float | None = None
    # Receipt reconciliation: variance = (issued + extra) - (received + missing + damaged).
    variance: float = 0.0
    balanced: bool = True
    remarks: str | None = None


class OrderRequestOut(BaseModel):
    id: uuid.UUID
    request_number: str
    transfer_type: str  # == purpose
    purpose: str
    status: str
    reason: str | None = None  # == comments
    # Legacy location fields (kept for back-compat; values are LOCATION ids).
    branch_id: uuid.UUID
    branch_name: str | None = None
    destination_branch_id: uuid.UUID | None = None
    destination_branch_name: str | None = None
    # Explicit source / destination branch + location.
    source_location_id: uuid.UUID | None = None
    source_location_name: str | None = None
    source_branch_id: uuid.UUID | None = None
    source_branch_name: str | None = None
    dest_location_id: uuid.UUID | None = None
    dest_location_name: str | None = None
    dest_branch_id: uuid.UUID | None = None
    dest_branch_name: str | None = None
    requested_by: uuid.UUID | None = None
    requester_name: str | None = None
    requested_date: dt.datetime
    approved_by: uuid.UUID | None = None
    approved_date: dt.datetime | None = None
    issued_by: uuid.UUID | None = None
    issued_date: dt.datetime | None = None
    received_by: uuid.UUID | None = None
    receiver_name: str | None = None
    received_date: dt.datetime | None = None
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


class TransferLedgerEntryOut(BaseModel):
    id: uuid.UUID
    event: str
    request_number: str
    product_id: uuid.UUID
    sku: str | None = None
    name: str | None = None
    qty_requested: float | None = None
    qty_approved: float | None = None
    qty_issued: float | None = None
    qty_received: float | None = None
    qty_missing: float | None = None
    qty_damaged: float | None = None
    qty_extra: float | None = None
    source_branch_name: str | None = None
    source_location_name: str | None = None
    dest_branch_name: str | None = None
    dest_location_name: str | None = None
    transfer_type: str | None = None
    reason: str | None = None
    created_at: dt.datetime
