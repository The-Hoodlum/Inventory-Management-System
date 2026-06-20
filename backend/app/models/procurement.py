"""ORM models for the demand + procurement tables.

These map onto tables already created by the database layer
(``database/sql/schema.sql`` sections 6 and 7): sales_daily, purchase_orders,
purchase_order_lines, and reorder_recommendations. PO numbering is handled by the
``next_po_number(tenant)`` SQL function, so ``po_counters`` needs no ORM mapping.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import CHAR, Boolean, Date, ForeignKey, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


class SalesDaily(Base):
    __tablename__ = "sales_daily"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False)
    sale_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    qty_sold: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    # Demand channel: issue|import|pos|manual. Demand reads SUM across sources per day.
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    po_number: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'USD'"))
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, server_default=text("1"))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    po_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    ordered_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    ordered_cartons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    received_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))


class ReorderRecommendation(Base):
    __tablename__ = "reorder_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    available_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    on_order_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    avg_daily_demand: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    reorder_point: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    safety_stock: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    recommended_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    recommended_cartons: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    # Risk overlay (provisioned by database/sql/reorder_risk.sql / migration 0008).
    risk_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default=text("0"))
    lead_time_extra_days: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    risk_cost_impact: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    expedite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    risk_drivers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class PurchaseOrderEvent(Base):
    """Append-only timeline of purchase-order lifecycle actions.

    Complements the generic ``audit_logs`` table with a queryable, PO-specific
    history that captures approval/rejection comments and receipt details.
    Provisioned by ``database/sql/po_events.sql`` (and Alembic migration 0003).
    """

    __tablename__ = "purchase_order_events"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    po_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class DemandForecast(Base):
    """A stored demand forecast for a (product, warehouse).

    Records both the base (pre-signal) and adjusted (post-signal) daily demand
    plus a supply-risk score, so the future intelligence layer can write here
    without a schema change. Accuracy is computed by comparing ``daily_demand``
    against realised sales_daily demand over [forecast_date, +horizon_days).
    Provisioned by ``database/sql/demand_forecasts.sql`` (and Alembic 0006).
    """

    __tablename__ = "demand_forecasts"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    daily_demand: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    adjusted_daily_demand: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    std_dev_daily: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default=text("0"))
    risk_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default=text("0"))
    observations: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    days_with_demand: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_demand: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    generated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
