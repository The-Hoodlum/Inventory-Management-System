"""Imported parts-sales history model (the "Sales Log" spreadsheet). Record-only — it
never writes stock; the Sales Log report unions it into parts revenue alongside live
``invoice_lines``. See ``sql/parts_sales.sql``."""
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


class PartsSale(Base):
    __tablename__ = "parts_sales"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    item_code: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sale_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    # Ex-VAT line total in ZMW — the basis the Sales Log uses for parts revenue.
    revenue_zmw: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    vat_zmw: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_historical: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("import_jobs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
