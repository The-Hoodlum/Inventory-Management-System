"""Bike-issues models: an internal repair on a bike we own and the spare parts
consumed to fix it. See ``sql/bike_issues.sql``.

Consuming a part goes through ``InventoryService`` (the single stock write path); these
tables only DOCUMENT the repair and which parts were used. Opening an issue holds the
serialized unit (``on_hold``); resolving releases it and commits the consumption."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


class BikeIssue(Base):
    __tablename__ = "bike_issues"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    issue_number: Mapped[str] = mapped_column(Text, nullable=False)
    # open | in_repair | resolved (state machine in app/bike_issues/domain/status.py)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    unit_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("motorcycle_units.id", ondelete="RESTRICT"), nullable=False)
    # Snapshot of the unit's identity at open time (read from the unit, never retyped).
    chassis_number: Mapped[str] = mapped_column(Text, nullable=False)
    engine_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    # The unit's sale status just before it was put on hold, restored on resolve.
    prior_status: Mapped[str] = mapped_column(Text, nullable=False)
    problem_description: Mapped[str] = mapped_column(Text, nullable=False)
    reported_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    reported_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    lines: Mapped[list[BikeIssueLine]] = relationship(
        "BikeIssueLine", cascade="all, delete-orphan", lazy="selectin", order_by="BikeIssueLine.id",
    )


class BikeIssueLine(Base):
    """One spare part consumed to fix a bike issue (product + source warehouse + qty)."""

    __tablename__ = "bike_issue_lines"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    issue_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("bike_issues.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    consumed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
