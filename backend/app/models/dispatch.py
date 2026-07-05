"""Typed delivery / dispatch note models.

A dispatch note is PAPER that documents a stock movement — it never mutates stock
itself (the movement goes through InventoryService for parts and the serialized
motorcycle registry for bikes). One note may carry MIXED lines. See
``sql/dispatch_notes.sql`` and ``app/dispatch/``.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


class DispatchNote(Base):
    __tablename__ = "dispatch_notes"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    note_number: Mapped[str] = mapped_column(Text, nullable=False)
    dispatch_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'warehouse_branch_transfer'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    from_branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="SET NULL"))
    from_warehouse_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    to_branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="SET NULL"))
    to_warehouse_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatched_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    dispatched_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    received_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_by_user: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    received_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    lines: Mapped[list[DispatchNoteLine]] = relationship(
        "DispatchNoteLine", cascade="all, delete-orphan", lazy="selectin", order_by="DispatchNoteLine.id"
    )


class DispatchNoteLine(Base):
    __tablename__ = "dispatch_note_lines"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    dispatch_note_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("dispatch_notes.id", ondelete="CASCADE"), nullable=False)
    line_kind: Mapped[str] = mapped_column(Text, nullable=False)  # 'motorcycle' | 'part'
    product_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("products.id", ondelete="RESTRICT"))
    unit_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("motorcycle_units.id", ondelete="RESTRICT"))
    chassis_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatched_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    received_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    missing_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    damaged_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------- #
# Internal issuance / handover (out-and-back loan) — delivery-note Type 4
# --------------------------------------------------------------------------- #
class Issuance(Base):
    __tablename__ = "issuances"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    issuance_number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="SET NULL"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    requestor: Mapped[str | None] = mapped_column(Text, nullable=True)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_return_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    issued_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    lines: Mapped[list[IssuanceLine]] = relationship(
        "IssuanceLine", cascade="all, delete-orphan", lazy="selectin", order_by="IssuanceLine.id"
    )


class IssuanceLine(Base):
    __tablename__ = "issuance_lines"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    issuance_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("issuances.id", ondelete="CASCADE"), nullable=False)
    line_kind: Mapped[str] = mapped_column(Text, nullable=False)  # 'motorcycle' | 'part'
    product_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("products.id", ondelete="RESTRICT"))
    unit_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("motorcycle_units.id", ondelete="RESTRICT"))
    chassis_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("1"))
    returnable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    consumable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    odometer_out: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fuel_out: Mapped[str | None] = mapped_column(Text, nullable=True)
    accessories: Mapped[str | None] = mapped_column(Text, nullable=True)
    returned_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    missing_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)  # good | fair | needs_attention
    odometer_in: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    return_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    returned_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
