"""Motorcycle module models: the serialized-asset reference catalog (models,
variants, colours) and the per-unit registry (units + their immutable event
ledger). See ``sql/motorcycle_units.sql``."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


# --------------------------------------------------------------------------- #
# Layer 1: reference catalog
# --------------------------------------------------------------------------- #
class MotorcycleModel(Base):
    __tablename__ = "motorcycle_models"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    brand_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    engine_cc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_selling_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    specs: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class MotorcycleVariant(Base):
    __tablename__ = "motorcycle_variants"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    model_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("motorcycle_models.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    specs: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class MotorcycleColour(Base):
    __tablename__ = "motorcycle_colours"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    hex_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


# --------------------------------------------------------------------------- #
# Layer 2: per-unit registry
# --------------------------------------------------------------------------- #
class MotorcycleUnit(Base):
    __tablename__ = "motorcycle_units"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    chassis_number: Mapped[str] = mapped_column(Text, nullable=False)
    engine_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("motorcycle_models.id", ondelete="RESTRICT"), nullable=False)
    variant_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("motorcycle_variants.id", ondelete="SET NULL"), nullable=True)
    colour_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("motorcycle_colours.id", ondelete="SET NULL"), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    container_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_received: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    internal_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Country this specific unit was sourced from (e.g. India / Congo / Kenya). Lets one
    # model cover units of different origin without duplicating the catalog entry.
    country_of_origin: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Sale status: ONE of five (unassembled/assembled/reserved/on_hold/sold). State
    # machine in app/motorcycles/domain/lifecycle.py.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unassembled'"))
    # Inspection — an INDEPENDENT fact (moves on its own, not part of the sale status).
    inspected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Reason the unit is on hold; required while status='on_hold', kept for history after.
    hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Serialized hold + sale linkage into the EXISTING sales documents.
    reserved_ref: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True)
    sold_ref: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    price_charged: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    payment_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unpaid'"))
    # Registration — INDEPENDENT of the sale status: a yes/no + the plate when yes.
    registered: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    registration_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_papers_received: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    warranty_start: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    warranty_end: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Provenance + historical lifecycle dates for bulk-imported units (migration 0031).
    imported_historical: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("import_jobs.id", ondelete="SET NULL"), nullable=True)
    assembled_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    date_sold: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class MotorcycleUnitEvent(Base):
    """One row per lifecycle event for a unit — the unit's immutable ledger."""

    __tablename__ = "motorcycle_unit_events"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    unit_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("motorcycle_units.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    to_branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    reference_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
