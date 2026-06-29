"""Pydantic models for the Sales & Distribution API: quotation, sales order,
delivery note, invoice, payment, receipt, and POS fast-sale."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


# ------------------------------ shared lines ------------------------------- #
class PricedLineIn(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0)
    unit_price: float | None = Field(default=None, ge=0)  # default = product.selling_price
    discount_pct: float = Field(default=0, ge=0, le=100)
    tax_pct: float = Field(default=0, ge=0)
    description: str | None = Field(default=None, max_length=500)


class PricedLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str | None = None
    name: str | None = None
    description: str | None = None
    qty: float
    unit_price: float
    discount_pct: float
    tax_pct: float
    line_total: float


class SalesOrderLineOut(PricedLineOut):
    reserved_qty: float = 0.0
    delivered_qty: float = 0.0
    outstanding_qty: float = 0.0


class DeliveryLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str | None = None
    name: str | None = None
    qty: float


# ------------------------------- document base ----------------------------- #
class _DocOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str | None = None
    branch_id: uuid.UUID | None = None
    branch_name: str | None = None
    status: str
    currency: str | None = None
    subtotal: float = 0.0
    discount_total: float = 0.0
    tax_total: float = 0.0
    grand_total: float = 0.0
    created_at: dt.datetime


# -------------------------------- quotation -------------------------------- #
class QuotationCreate(BaseModel):
    customer_id: uuid.UUID
    branch_id: uuid.UUID | None = None
    salesperson_id: uuid.UUID | None = None
    currency: str | None = None
    valid_until: dt.date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[PricedLineIn] = Field(min_length=1)


class QuotationOut(_DocOut):
    quote_number: str
    salesperson_id: uuid.UUID | None = None
    valid_until: dt.date | None = None
    notes: str | None = None
    lines: list[PricedLineOut] = []


class ConvertToOrder(BaseModel):
    location_id: uuid.UUID  # selling/source location for the new sales order
    payment_terms: str | None = None
    delivery_terms: str | None = None


# ------------------------------- sales order ------------------------------- #
class SalesOrderCreate(BaseModel):
    customer_id: uuid.UUID
    branch_id: uuid.UUID | None = None
    location_id: uuid.UUID  # selling/source location (required to reserve + deliver)
    salesperson_id: uuid.UUID | None = None
    currency: str | None = None
    payment_terms: str | None = None
    delivery_terms: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[PricedLineIn] = Field(min_length=1)


class SalesOrderOut(_DocOut):
    so_number: str
    location_id: uuid.UUID | None = None
    location_name: str | None = None
    salesperson_id: uuid.UUID | None = None
    quotation_id: uuid.UUID | None = None
    quote_number: str | None = None
    payment_terms: str | None = None
    delivery_terms: str | None = None
    notes: str | None = None
    lines: list[SalesOrderLineOut] = []


# ------------------------------ delivery note ------------------------------ #
class DeliveryLineIn(BaseModel):
    sales_order_line_id: uuid.UUID
    qty: float = Field(gt=0)


class DeliveryCreate(BaseModel):
    """Issue a (possibly partial) delivery against a confirmed sales order. Omitting
    `lines` delivers the full outstanding quantity of every line."""
    delivery_address: str | None = None
    driver: str | None = None
    vehicle: str | None = None
    notes: str | None = None
    lines: list[DeliveryLineIn] = Field(default_factory=list)


class DeliveryConfirm(BaseModel):
    received_by: str | None = Field(default=None, max_length=256)
    signature: str | None = None


class DeliveryNoteOut(BaseModel):
    id: uuid.UUID
    delivery_number: str
    sales_order_id: uuid.UUID | None = None
    so_number: str | None = None
    customer_id: uuid.UUID
    customer_name: str | None = None
    branch_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    location_name: str | None = None
    status: str
    delivery_address: str | None = None
    driver: str | None = None
    vehicle: str | None = None
    received_by: str | None = None
    delivered_at: dt.datetime | None = None
    created_at: dt.datetime
    lines: list[DeliveryLineOut] = []


# --------------------------------- invoice --------------------------------- #
class InvoiceCreate(BaseModel):
    """Invoice a delivery (default) or a sales order. Lines default to the source
    document; money document only — never moves stock."""
    sales_order_id: uuid.UUID | None = None
    delivery_note_id: uuid.UUID | None = None
    due_date: dt.date | None = None
    payment_terms: str | None = None


class InvoiceOut(_DocOut):
    invoice_number: str
    sales_order_id: uuid.UUID | None = None
    delivery_note_id: uuid.UUID | None = None
    invoice_date: dt.date
    due_date: dt.date | None = None
    payment_terms: str | None = None
    amount_paid: float = 0.0
    balance: float = 0.0
    lines: list[PricedLineOut] = []


# --------------------------- payment + receipt ----------------------------- #
class PaymentLineIn(BaseModel):
    method: str = Field(pattern="^(cash|card|mobile_money|bank_transfer|cheque|store_credit)$")
    amount: float = Field(gt=0)
    reference: str | None = Field(default=None, max_length=128)


class PaymentCreate(BaseModel):
    """Record one or more payments (split tender) against an invoice; a receipt is
    generated automatically."""
    invoice_id: uuid.UUID
    payments: list[PaymentLineIn] = Field(min_length=1)


class PaymentOut(BaseModel):
    id: uuid.UUID
    payment_number: str
    method: str
    amount: float
    reference: str | None = None
    created_at: dt.datetime


class ReceiptOut(BaseModel):
    id: uuid.UUID
    receipt_number: str
    invoice_id: uuid.UUID | None = None
    invoice_number: str | None = None
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    cashier_id: uuid.UUID | None = None
    amount_paid: float
    balance: float
    methods: list[PaymentOut] = []
    created_at: dt.datetime


# ----------------------------------- POS ----------------------------------- #
class PosCheckout(BaseModel):
    """One fast-sale transaction: reserve+issue at the cashier location, invoice, pay,
    receipt — atomically. Customer optional (walk-in)."""
    location_id: uuid.UUID
    branch_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    currency: str | None = None
    lines: list[PricedLineIn] = Field(min_length=1)
    payments: list[PaymentLineIn] = Field(min_length=1)


class PosResult(BaseModel):
    sales_order: SalesOrderOut
    delivery_note: DeliveryNoteOut
    invoice: InvoiceOut
    receipt: ReceiptOut


# ------------------------------ status actions ----------------------------- #
class CancelBody(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
