"""Motorcycle service follow-up models: the per-model service schedule (an editable
override table that falls back to module defaults) and the append-only log of services
performed on a sold unit. See ``sql/motorcycle_service.sql``.

Neither table writes stock — they are customer-care records, not inventory documents.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


class MotorcycleServicePlan(Base):
    """A tenant's service schedule. ``model_id`` NULL is the tenant-wide default used
    when a model has no override; ``stages`` is an ordered list of
    ``{"sequence", "label", "interval_days"}`` where each interval is the gap from the
    previous service (the first from the sale). The last stage repeats beyond the list."""

    __tablename__ = "motorcycle_service_plans"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    model_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("motorcycle_models.id", ondelete="CASCADE"), nullable=True)
    stages: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class MotorcycleServiceRecord(Base):
    """One row per service performed on a unit — the unit's service history."""

    __tablename__ = "motorcycle_service_records"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    unit_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("motorcycle_units.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
