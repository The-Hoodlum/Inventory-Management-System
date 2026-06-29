"""Customer master models. See ``sql/customers.sql``."""
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


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    addresses: Mapped[list[CustomerAddress]] = relationship(
        "CustomerAddress", cascade="all, delete-orphan", lazy="selectin", order_by="CustomerAddress.created_at"
    )


class CustomerAddress(Base):
    __tablename__ = "customer_addresses"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    address_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'shipping'"))
    line1: Mapped[str | None] = mapped_column(Text, nullable=True)
    line2: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
