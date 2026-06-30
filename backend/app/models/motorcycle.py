"""Motorcycle (serialized-unit) registry models. See ``sql/motorcycle_units.sql``.

A serialized asset: one permanent record per physical unit, tracked by chassis number
through its lifecycle, with its own immutable event ledger. Distinct from fungible
inventory; linked to the existing sales documents when reserved/sold. Tenant- & branch-
aware, RLS-isolated, optimistic-locked (``version``).
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


class MotorcycleUnit(Base):
    __tablename__ = "motorcycle_units"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    chassis_number: Mapped[str] = mapped_column(Text, nullable=False)
    engine_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    variant: Mapped[str | None] = mapped_column(Text, nullable=True)
    colour: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("suppliers.id", ondelete="SET NULL"))
    container_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_received: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="RESTRICT"))
    internal_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'received'"))
    inspection_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    assembly_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'not_required'"))
    reserved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    reserved_sales_order_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("sales_orders.id", ondelete="SET NULL"))
    sold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("invoices.id", ondelete="SET NULL"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("customers.id", ondelete="SET NULL"))
    selling_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    price_charged: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    payment_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unpaid'"))
    registration_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unregistered'"))
    registration_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_papers_received: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    warranty_start: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    warranty_end: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    events: Mapped[list[MotorcycleUnitEvent]] = relationship(
        "MotorcycleUnitEvent", cascade="all, delete-orphan", lazy="selectin",
        order_by="MotorcycleUnitEvent.created_at",
    )


class MotorcycleUnitEvent(Base):
    """Append-only lifecycle ledger for one unit (status changes, reserve/sell, transfers)."""

    __tablename__ = "motorcycle_unit_events"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    unit_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("motorcycle_units.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="SET NULL"))
    to_branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="SET NULL"))
    reference_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
