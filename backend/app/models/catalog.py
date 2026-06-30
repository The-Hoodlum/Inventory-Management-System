"""Catalog models: categories, brands, suppliers, products, supplier_products."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_person: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'USD'"))
    payment_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    sku: Mapped[str] = mapped_column(Text, nullable=False)
    barcode: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("brands.id", ondelete="SET NULL"), nullable=True)
    primary_supplier_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    selling_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    units_per_carton: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    moq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    weight_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    volume_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    weight_per_carton: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    volume_per_carton: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cartons_per_pallet: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reorder_point: Mapped[int | None] = mapped_column(Integer, nullable=True)
    safety_stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # --- Product Intelligence Profile (migration 0009) ---
    # Consumed by the forecast, risk, procurement, intelligence, and AI engines.
    commodity_tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    country_of_origin: Mapped[str | None] = mapped_column(Text, nullable=True)
    transport_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    criticality: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'medium'"))
    supplier_dependency: Mapped[str | None] = mapped_column(Text, nullable=True)
    demand_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    substitutability: Mapped[str | None] = mapped_column(Text, nullable=True)
    # --- Strategic flags (migration 0013) — consumed by the risk/forecast/AI engines ---
    strategic_item: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    alternate_supplier_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # --- Unit of measure + product-level currency (import framework, migration 0011) ---
    # currency NULL => fall back to the tenant base_currency.
    unit_of_measure: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    # Set when a row created this product via an import; powers rollback. NULL otherwise.
    created_by_import_job_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class SupplierProduct(Base):
    __tablename__ = "supplier_products"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    supplier_sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'USD'"))
    moq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    units_per_carton: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
