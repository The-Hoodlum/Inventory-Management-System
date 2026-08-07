"""Schemas for the Customer Handover (create draft / patch / complete / read).

The editable fields live once on ``_HandoverEditable`` and are shared by create and
update; both are applied with ``model_dump(exclude_unset=True)`` so a PATCH only touches
the fields the caller actually sent (booleans included). ``HandoverOut`` adds the resolved
motorcycle / customer / branch context so the frontend never re-fetches those.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FuelLevel = Literal["E", "1", "2", "3", "4", "F"]
PaymentMethod = Literal["Cash", "Bank Transfer", "Airtel Money", "Other"]

# The five verification-grid roles, in display order. Reused by the service + PDF.
APPROVAL_ROLES: tuple[str, ...] = (
    "mechanic_inspector",
    "assembly_technician",
    "quality_control_officer",
    "salesperson",
    "branch_manager",
)


class _HandoverEditable(BaseModel):
    """Every field a user may fill on the form. All optional so it serves both the
    create-with-initial-values and the partial-PATCH cases."""

    model_config = ConfigDict(extra="forbid")

    # Handover facts.
    delivery_date: dt.date | None = None
    warranty_start_date: dt.date | None = None
    odometer_reading_km: Decimal | None = Field(default=None, ge=0)
    fuel_level_at_delivery: FuelLevel | None = None
    salesperson_id: uuid.UUID | None = None

    # Customer snapshot (overrides the auto-filled snapshot if provided).
    full_name: str | None = Field(default=None, max_length=256)
    nrc_passport_no: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=64)
    whatsapp: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=256)
    physical_address: str | None = Field(default=None, max_length=1000)

    # Pre-delivery checklist.
    motorcycle_washed: bool | None = None
    battery_connected: bool | None = None
    engine_tested: bool | None = None
    brakes_tested: bool | None = None
    lights_working: bool | None = None
    indicators_working: bool | None = None
    horn_working: bool | None = None
    mirrors_fitted: bool | None = None
    tyre_pressure_checked: bool | None = None
    chain_adjusted: bool | None = None
    oil_level_checked: bool | None = None
    throttle_operation_checked: bool | None = None
    toolkit_supplied: bool | None = None
    owners_manual_supplied: bool | None = None
    warranty_book_supplied: bool | None = None
    spare_key_supplied: bool | None = None
    checklist_remarks: str | None = Field(default=None, max_length=2000)

    # Customer training.
    controls_explained: bool | None = None
    break_in_period_explained: bool | None = None
    service_schedule_explained: bool | None = None
    warranty_terms_explained: bool | None = None
    safe_riding_explained: bool | None = None
    maintenance_tips_explained: bool | None = None
    training_remarks: str | None = Field(default=None, max_length=2000)

    # Items / accessories.
    helmet: bool | None = None
    reflector_jacket: bool | None = None
    spare_key: bool | None = None
    other_items: str | None = Field(default=None, max_length=1000)

    # Payment (reference from invoice; overridable).
    payment_method: PaymentMethod | None = None
    amount_paid_zmw: Decimal | None = Field(default=None, ge=0)
    balance_zmw: Decimal | None = Field(default=None)
    invoice_amount_zmw: Decimal | None = Field(default=None, ge=0)
    internal_remarks: str | None = Field(default=None, max_length=2000)

    # Verification & approval grid (name / signed for each role; signed_at is stamped
    # server-side when signed flips true).
    mechanic_inspector_name: str | None = Field(default=None, max_length=256)
    mechanic_inspector_signed: bool | None = None
    assembly_technician_name: str | None = Field(default=None, max_length=256)
    assembly_technician_signed: bool | None = None
    quality_control_officer_name: str | None = Field(default=None, max_length=256)
    quality_control_officer_signed: bool | None = None
    salesperson_name: str | None = Field(default=None, max_length=256)
    salesperson_signed: bool | None = None
    branch_manager_name: str | None = Field(default=None, max_length=256)
    branch_manager_signed: bool | None = None

    # Signatures.
    customer_signature_name: str | None = Field(default=None, max_length=256)
    customer_signature_image: str | None = None
    salesperson_signature_name: str | None = Field(default=None, max_length=256)
    salesperson_signature_image: str | None = None


class HandoverCreate(_HandoverEditable):
    """Create a DRAFT. Requires the two source references; everything else is either
    auto-filled from the invoice / unit / customer or supplied here."""

    invoice_id: uuid.UUID
    unit_id: uuid.UUID


class HandoverUpdate(_HandoverEditable):
    """Partial update of a DRAFT (a COMPLETED handover is locked)."""


class HandoverComplete(BaseModel):
    """Optionally apply a final batch of edits, then complete. Stamps the customer /
    salesperson signature timestamps if names are present and not yet stamped."""

    model_config = ConfigDict(extra="forbid")

    fields: HandoverUpdate | None = None


class HandoverLookupOut(BaseModel):
    """Result of the 'scan / enter chassis' entry point: the auto-fill preview the New
    Handover form shows before a draft is created. ``existing_handover_id`` is set when the
    unit already has a handover (the form should open that instead of creating a second)."""

    unit_id: uuid.UUID
    invoice_id: uuid.UUID | None = None
    invoice_number: str | None = None
    chassis_number: str | None = None
    engine_number: str | None = None
    model_name: str | None = None
    colour_name: str | None = None
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    phone: str | None = None
    email: str | None = None
    branch_id: uuid.UUID | None = None
    branch_name: str | None = None
    salesperson_display: str | None = None
    invoice_amount_zmw: Decimal = Decimal("0")
    amount_paid_zmw: Decimal = Decimal("0")
    balance_zmw: Decimal = Decimal("0")
    existing_handover_id: uuid.UUID | None = None


class ApprovalOut(BaseModel):
    role: str
    name: str | None = None
    signed: bool = False
    signed_at: dt.datetime | None = None


class HandoverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    handover_no: str
    status: str

    invoice_id: uuid.UUID | None = None
    invoice_number: str | None = None
    sales_order_id: uuid.UUID | None = None
    unit_id: uuid.UUID
    branch_id: uuid.UUID | None = None
    branch_name: str | None = None
    salesperson_id: uuid.UUID | None = None
    salesperson_display: str | None = None

    # Resolved motorcycle context (pulled from the unit + catalog; not stored twice).
    chassis_number: str | None = None
    engine_number: str | None = None
    model_name: str | None = None
    colour_name: str | None = None

    delivery_date: dt.date | None = None
    warranty_start_date: dt.date | None = None
    odometer_reading_km: Decimal | None = None
    fuel_level_at_delivery: str | None = None

    # Customer snapshot.
    full_name: str | None = None
    nrc_passport_no: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    email: str | None = None
    physical_address: str | None = None

    # Checklist.
    motorcycle_washed: bool = False
    battery_connected: bool = False
    engine_tested: bool = False
    brakes_tested: bool = False
    lights_working: bool = False
    indicators_working: bool = False
    horn_working: bool = False
    mirrors_fitted: bool = False
    tyre_pressure_checked: bool = False
    chain_adjusted: bool = False
    oil_level_checked: bool = False
    throttle_operation_checked: bool = False
    toolkit_supplied: bool = False
    owners_manual_supplied: bool = False
    warranty_book_supplied: bool = False
    spare_key_supplied: bool = False
    checklist_remarks: str | None = None

    # Training.
    controls_explained: bool = False
    break_in_period_explained: bool = False
    service_schedule_explained: bool = False
    warranty_terms_explained: bool = False
    safe_riding_explained: bool = False
    maintenance_tips_explained: bool = False
    training_remarks: str | None = None

    # Accessories.
    helmet: bool = False
    reflector_jacket: bool = False
    spare_key: bool = False
    other_items: str | None = None

    # Payment.
    payment_method: str | None = None
    amount_paid_zmw: Decimal = Decimal("0")
    balance_zmw: Decimal = Decimal("0")
    invoice_amount_zmw: Decimal = Decimal("0")
    internal_remarks: str | None = None

    # Verification & approval grid, as a list (built by the service).
    approvals: list[ApprovalOut] = []

    # Signatures.
    customer_signature_name: str | None = None
    customer_signed_at: dt.datetime | None = None
    customer_signature_image: str | None = None
    salesperson_signature_name: str | None = None
    salesperson_signed_at: dt.datetime | None = None
    salesperson_signature_image: str | None = None

    completed_at: dt.datetime | None = None
    created_at: dt.datetime
