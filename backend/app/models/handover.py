"""Customer Handover model — the signed record that a customer physically received
their motorcycle (paper form: Customer Copy + Internal Copy). See
``sql/customer_handovers.sql`` and ``app/customer_handovers/``.

One flat row per handover (it is a single signed document, not a multi-line record):
source-document links, a frozen customer snapshot, the pre-delivery checklist, customer
training, accessories, payment, a 5-role verification grid, and signatures. Tenant-scoped
+ RLS. Never touches inventory — completing it marks the unit delivered + stamps warranty.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


def _flag() -> Mapped[bool]:
    return mapped_column(Boolean, nullable=False, server_default=text("false"))


class CustomerHandover(Base):
    __tablename__ = "customer_handovers"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    handover_no: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'DRAFT'"))

    # Source documents (data pulled FROM these; never re-typed).
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("motorcycle_units.id", ondelete="RESTRICT"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Handover facts.
    delivery_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    warranty_start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    odometer_reading_km: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    fuel_level_at_delivery: Mapped[str | None] = mapped_column(Text, nullable=True)  # E,1,2,3,4,F

    # Customer snapshot (frozen at handover time).
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    nrc_passport_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    physical_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pre-delivery inspection checklist.
    motorcycle_washed: Mapped[bool] = _flag()
    battery_connected: Mapped[bool] = _flag()
    engine_tested: Mapped[bool] = _flag()
    brakes_tested: Mapped[bool] = _flag()
    lights_working: Mapped[bool] = _flag()
    indicators_working: Mapped[bool] = _flag()
    horn_working: Mapped[bool] = _flag()
    mirrors_fitted: Mapped[bool] = _flag()
    tyre_pressure_checked: Mapped[bool] = _flag()
    chain_adjusted: Mapped[bool] = _flag()
    oil_level_checked: Mapped[bool] = _flag()
    throttle_operation_checked: Mapped[bool] = _flag()
    toolkit_supplied: Mapped[bool] = _flag()
    owners_manual_supplied: Mapped[bool] = _flag()
    warranty_book_supplied: Mapped[bool] = _flag()
    spare_key_supplied: Mapped[bool] = _flag()
    checklist_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Customer training.
    controls_explained: Mapped[bool] = _flag()
    break_in_period_explained: Mapped[bool] = _flag()
    service_schedule_explained: Mapped[bool] = _flag()
    warranty_terms_explained: Mapped[bool] = _flag()
    safe_riding_explained: Mapped[bool] = _flag()
    maintenance_tips_explained: Mapped[bool] = _flag()
    training_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Items / accessories delivered.
    helmet: Mapped[bool] = _flag()
    reflector_jacket: Mapped[bool] = _flag()
    spare_key: Mapped[bool] = _flag()
    other_items: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Payment (reference from invoice; overridable).
    payment_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_paid_zmw: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    balance_zmw: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    invoice_amount_zmw: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    internal_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Verification & approval grid (5 roles; each name / signed / signed_at).
    mechanic_inspector_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    mechanic_inspector_signed: Mapped[bool] = _flag()
    mechanic_inspector_signed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    assembly_technician_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    assembly_technician_signed: Mapped[bool] = _flag()
    assembly_technician_signed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    quality_control_officer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_control_officer_signed: Mapped[bool] = _flag()
    quality_control_officer_signed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    salesperson_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    salesperson_signed: Mapped[bool] = _flag()
    salesperson_signed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    branch_manager_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_manager_signed: Mapped[bool] = _flag()
    branch_manager_signed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Signatures (name + date always; image optional — base64 / file ref).
    # The salesperson's signature time is the approval-grid ``salesperson_signed_at`` above
    # (same signing act), so it is not duplicated in this block.
    customer_signature_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_signed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    customer_signature_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    salesperson_signature_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    salesperson_signature_image: Mapped[str | None] = mapped_column(Text, nullable=True)

    completed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
