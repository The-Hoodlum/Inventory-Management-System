"""Sales-document models: quotation -> sales order -> delivery note -> invoice ->
payment -> receipt. See ``sql/sales_documents.sql``. All tenant-scoped + RLS.

Stock is reserved when a sales order is confirmed and deducted at delivery (or
immediately at POS) via the shared inventory engine; money documents never touch stock.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


def _num(default: str = "0", nullable: bool = False) -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 4), nullable=nullable, server_default=text(default))


def _rate() -> Mapped[Decimal]:
    """A VAT/rate fraction column (0.16 = 16%), frozen on a document/line."""
    return mapped_column(Numeric(9, 6), nullable=False, server_default=text("0"))


def _treatment() -> Mapped[str]:
    return mapped_column(Text, nullable=False, server_default=text("'exclusive'"))


# ------------------------------- Quotation --------------------------------- #
class Quotation(Base):
    __tablename__ = "quotations"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    quote_number: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="RESTRICT"))
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_until: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtotal: Mapped[Decimal] = _num()
    discount_total: Mapped[Decimal] = _num()
    net_total: Mapped[Decimal] = _num()   # sum of line net (VAT-exclusive), frozen
    tax_total: Mapped[Decimal] = _num()   # sum of line VAT, frozen
    grand_total: Mapped[Decimal] = _num()  # sum of line payable (VAT-inclusive gross)
    # VAT rate applied, frozen at creation (fraction: 0.16 = 16%). See migration 0048.
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False, server_default=text("0"))
    # USD -> billing-currency (ZMW) rate frozen when the quote is created, and the billed
    # ZMW grand total derived from it (never recomputed at view time). See migration 0033.
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, server_default=text("1"))
    grand_total_zmw: Mapped[Decimal] = _num()
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    lines: Mapped[list[QuotationLine]] = relationship(
        "QuotationLine", cascade="all, delete-orphan", lazy="selectin", order_by="QuotationLine.id"
    )


class QuotationLine(Base):
    __tablename__ = "quotation_lines"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    quotation_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    qty: Mapped[Decimal] = _num()
    unit_price: Mapped[Decimal] = _num()
    discount_pct: Mapped[Decimal] = _num()
    tax_pct: Mapped[Decimal] = _num()
    line_total: Mapped[Decimal] = _num()      # payable (VAT-inclusive gross)
    line_total_zmw: Mapped[Decimal] = _num()  # line_total * document fx_rate, frozen
    net_amount: Mapped[Decimal] = _num()      # VAT-exclusive net, frozen
    vat_amount: Mapped[Decimal] = _num()      # VAT component, frozen
    vat_treatment: Mapped[str] = _treatment()
    vat_rate: Mapped[Decimal] = _rate()


# ------------------------------ Sales order -------------------------------- #
class SalesOrder(Base):
    __tablename__ = "sales_orders"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    so_number: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="RESTRICT"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="RESTRICT"))
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("quotations.id", ondelete="SET NULL"))
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtotal: Mapped[Decimal] = _num()
    discount_total: Mapped[Decimal] = _num()
    tax_total: Mapped[Decimal] = _num()
    grand_total: Mapped[Decimal] = _num()
    net_total: Mapped[Decimal] = _num()
    vat_rate: Mapped[Decimal] = _rate()
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    lines: Mapped[list[SalesOrderLine]] = relationship(
        "SalesOrderLine", cascade="all, delete-orphan", lazy="selectin", order_by="SalesOrderLine.id"
    )


class SalesOrderLine(Base):
    __tablename__ = "sales_order_lines"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    sales_order_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    qty: Mapped[Decimal] = _num()
    unit_price: Mapped[Decimal] = _num()
    discount_pct: Mapped[Decimal] = _num()
    tax_pct: Mapped[Decimal] = _num()
    line_total: Mapped[Decimal] = _num()
    net_amount: Mapped[Decimal] = _num()
    vat_amount: Mapped[Decimal] = _num()
    vat_treatment: Mapped[str] = _treatment()
    vat_rate: Mapped[Decimal] = _rate()
    reserved_qty: Mapped[Decimal] = _num()
    delivered_qty: Mapped[Decimal] = _num()


# ----------------------------- Delivery note ------------------------------- #
class DeliveryNote(Base):
    __tablename__ = "delivery_notes"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    delivery_number: Mapped[str] = mapped_column(Text, nullable=False)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("sales_orders.id", ondelete="SET NULL"))
    customer_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="RESTRICT"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="RESTRICT"))
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    driver: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    received_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    delivered_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    lines: Mapped[list[DeliveryNoteLine]] = relationship(
        "DeliveryNoteLine", cascade="all, delete-orphan", lazy="selectin", order_by="DeliveryNoteLine.id"
    )


class DeliveryNoteLine(Base):
    __tablename__ = "delivery_note_lines"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    delivery_note_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("delivery_notes.id", ondelete="CASCADE"), nullable=False)
    sales_order_line_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("sales_order_lines.id", ondelete="SET NULL"))
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    qty: Mapped[Decimal] = _num()


# -------------------------------- Invoice ---------------------------------- #
class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    invoice_number: Mapped[str] = mapped_column(Text, nullable=False)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("sales_orders.id", ondelete="SET NULL"))
    delivery_note_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("delivery_notes.id", ondelete="SET NULL"))
    customer_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="RESTRICT"))
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_date: Mapped[dt.date] = mapped_column(Date, server_default=text("CURRENT_DATE"))
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    subtotal: Mapped[Decimal] = _num()
    discount_total: Mapped[Decimal] = _num()
    tax_total: Mapped[Decimal] = _num()
    grand_total: Mapped[Decimal] = _num()
    net_total: Mapped[Decimal] = _num()
    vat_rate: Mapped[Decimal] = _rate()
    # USD -> ZMW rate frozen when the invoice is issued; ZMW grand total is the PAYABLE
    # (payments settle against it, in ZMW). ``amount_paid``/``credit_total`` reconcile in
    # ZMW at this frozen rate. See migration 0033.
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, server_default=text("1"))
    grand_total_zmw: Mapped[Decimal] = _num()
    amount_paid: Mapped[Decimal] = _num()   # in ZMW (the billing currency)
    credit_total: Mapped[Decimal] = _num()  # applied credit notes, in USD (converted at fx_rate)
    # Void / reverse (admin correction; the invoice is kept for audit, excluded from active
    # totals). See migration 0049.
    voided_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    voided_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    lines: Mapped[list[InvoiceLine]] = relationship(
        "InvoiceLine", cascade="all, delete-orphan", lazy="selectin", order_by="InvoiceLine.id"
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    qty: Mapped[Decimal] = _num()
    unit_price: Mapped[Decimal] = _num()
    discount_pct: Mapped[Decimal] = _num()
    tax_pct: Mapped[Decimal] = _num()
    line_total: Mapped[Decimal] = _num()      # payable (VAT-inclusive gross)
    line_total_zmw: Mapped[Decimal] = _num()  # line_total * invoice fx_rate, frozen (billed)
    net_amount: Mapped[Decimal] = _num()      # VAT-exclusive net, frozen
    vat_amount: Mapped[Decimal] = _num()      # VAT component, frozen
    vat_treatment: Mapped[str] = _treatment()
    vat_rate: Mapped[Decimal] = _rate()


# --------------------------- Payment + Receipt ----------------------------- #
class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    receipt_number: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("invoices.id", ondelete="SET NULL"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("customers.id", ondelete="RESTRICT"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="RESTRICT"))
    cashier_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    amount_paid: Mapped[Decimal] = _num()
    balance: Mapped[Decimal] = _num()
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    payment_number: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("customers.id", ondelete="RESTRICT"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="RESTRICT"))
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("receipts.id", ondelete="SET NULL"))
    method: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = _num()
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    allocations: Mapped[list[PaymentAllocation]] = relationship(
        "PaymentAllocation", cascade="all, delete-orphan", lazy="selectin", order_by="PaymentAllocation.id"
    )


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    payment_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = _num()


# --------------------------- Returns + Credit notes ------------------------ #
class Return(Base):
    __tablename__ = "returns"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    return_number: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("invoices.id", ondelete="SET NULL"))
    customer_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="RESTRICT"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("warehouses.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'other'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'received'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    received_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    lines: Mapped[list[ReturnLine]] = relationship(
        "ReturnLine", cascade="all, delete-orphan", lazy="selectin", order_by="ReturnLine.id"
    )


class ReturnLine(Base):
    __tablename__ = "return_lines"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    return_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("returns.id", ondelete="CASCADE"), nullable=False)
    invoice_line_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("invoice_lines.id", ondelete="SET NULL"))
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    qty: Mapped[Decimal] = _num()
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CreditNote(Base):
    __tablename__ = "credit_notes"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    credit_note_number: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("invoices.id", ondelete="SET NULL"))
    return_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("returns.id", ondelete="SET NULL"))
    customer_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    subtotal: Mapped[Decimal] = _num()
    discount_total: Mapped[Decimal] = _num()
    tax_total: Mapped[Decimal] = _num()
    grand_total: Mapped[Decimal] = _num()
    net_total: Mapped[Decimal] = _num()
    vat_rate: Mapped[Decimal] = _rate()
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"))
    applied_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    lines: Mapped[list[CreditNoteLine]] = relationship(
        "CreditNoteLine", cascade="all, delete-orphan", lazy="selectin", order_by="CreditNoteLine.id"
    )


class CreditNoteLine(Base):
    __tablename__ = "credit_note_lines"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    credit_note_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("credit_notes.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    qty: Mapped[Decimal] = _num()
    unit_price: Mapped[Decimal] = _num()
    discount_pct: Mapped[Decimal] = _num()
    tax_pct: Mapped[Decimal] = _num()
    line_total: Mapped[Decimal] = _num()      # payable (VAT-inclusive gross)
    net_amount: Mapped[Decimal] = _num()
    vat_amount: Mapped[Decimal] = _num()
    vat_treatment: Mapped[str] = _treatment()
    vat_rate: Mapped[Decimal] = _rate()
