"""Supply-chain intelligence model — normalised observations feeding the
forecast signal pipeline and the intelligence dashboard."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


class IntelligenceSignal(Base):
    __tablename__ = "intelligence_signals"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default=text("0"))
    demand_factor: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, server_default=text("1"))
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default=text("0.5"))
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    trend: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    expires_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class SupplierScore(Base):
    """Persisted supplier scorecard — internal delivery performance blended with
    active intelligence signals. Provisioned by ``database/sql/supplier_scores.sql``
    (and Alembic migration 0010). Rows are kept per recompute so a score trend
    can be drawn."""

    __tablename__ = "supplier_scores"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False)
    on_time_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    avg_lead_time_days: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    lead_time_stdev_days: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    lead_time_accuracy: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    fill_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    delivery_performance: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    reliability: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default=text("1"))
    performance_risk: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default=text("0"))
    intelligence_risk: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default=text("0"))
    risk_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default=text("0"))
    grade: Mapped[str] = mapped_column(Text, nullable=False)
    po_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    received_po_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_spend: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    last_order_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    drivers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
