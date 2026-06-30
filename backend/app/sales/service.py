"""Sales & Distribution orchestration.

quotation -> (convert) -> sales order -> confirm (RESERVE) -> delivery (DEDUCT) ->
invoice -> payment -> receipt. POS runs the same engine in one fast transaction.
Stock moves only via the shared reservation + inventory ledger; money documents never
touch stock. Every transition is audited and linked to its source document.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models import (
    CreditNote,
    CreditNoteLine,
    Customer,
    DeliveryNote,
    DeliveryNoteLine,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    Quotation,
    QuotationLine,
    Receipt,
    Return,
    ReturnLine,
    SalesOrder,
    SalesOrderLine,
)
from app.repositories.audit_repo import AuditRepository
from app.sales.domain import pricing
from app.sales.domain import status as S
from app.sales.repository import SalesRepository
from app.sales.schemas import (
    ConvertToOrder,
    CreditNoteCreate,
    CreditNoteOut,
    DeliveryConfirm,
    DeliveryCreate,
    DeliveryLineOut,
    DeliveryNoteOut,
    InvoiceCreate,
    InvoiceOut,
    PaymentCreate,
    PaymentOut,
    PosCheckout,
    PosResult,
    PricedLineIn,
    PricedLineOut,
    QuotationCreate,
    QuotationOut,
    ReceiptOut,
    ReturnCreate,
    ReturnLineOut,
    ReturnOut,
    SalesOrderCreate,
    SalesOrderLineOut,
    SalesOrderOut,
)


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


class SalesService:
    def __init__(self, repo: SalesRepository, audit: AuditRepository) -> None:
        self.repo = repo
        self.audit = audit

    # ============================== quotation ============================= #
    async def create_quotation(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: QuotationCreate
    ) -> QuotationOut:
        await self._require_customer(payload.customer_id)
        lines, totals = await self._priced_lines(tenant_id, QuotationLine, payload.lines)
        quote = Quotation(
            tenant_id=tenant_id, quote_number=await self.repo.number(tenant_id, "quotation", "QUO"),
            customer_id=payload.customer_id, branch_id=payload.branch_id,
            salesperson_id=payload.salesperson_id or user_id, currency=payload.currency,
            valid_until=payload.valid_until, status=S.Q_DRAFT, notes=payload.notes,
            created_by=user_id, **totals,
        )
        quote.lines = lines
        self.repo.session.add(quote)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "sales_quotation", quote.id, "created", None, S.Q_DRAFT)
        return await self._quote_out(quote)

    async def quote_transition(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, quote_id: uuid.UUID, new: str,
        reason: str | None = None,
    ) -> QuotationOut:
        quote = await self._require(self.repo.get_quote(quote_id, lock=True), "Quotation")
        if not S.quote_can_transition(quote.status, new):
            raise BusinessRuleError(f"Cannot move quotation from {quote.status} to {new}.")
        old, quote.status = quote.status, new
        if reason:
            quote.notes = reason
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "sales_quotation", quote.id, new, old, new)
        return await self._quote_out(quote)

    async def convert_quotation(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, quote_id: uuid.UUID, payload: ConvertToOrder
    ) -> SalesOrderOut:
        quote = await self._require(self.repo.get_quote(quote_id, lock=True), "Quotation")
        if quote.status not in S.QUOTE_CONVERTIBLE:
            raise BusinessRuleError(f"Quotation in status {quote.status} cannot be converted.")
        line_payload = [
            PricedLineIn(product_id=ln.product_id, qty=_f(ln.qty), unit_price=_f(ln.unit_price),
                         discount_pct=_f(ln.discount_pct), tax_pct=_f(ln.tax_pct), description=ln.description)
            for ln in quote.lines
        ]
        so = await self._new_sales_order(
            tenant_id=tenant_id, user_id=user_id, customer_id=quote.customer_id,
            branch_id=quote.branch_id, location_id=payload.location_id,
            salesperson_id=quote.salesperson_id, currency=quote.currency,
            payment_terms=payload.payment_terms, delivery_terms=payload.delivery_terms,
            notes=quote.notes, lines=line_payload, quotation_id=quote.id,
        )
        if quote.status != S.Q_ACCEPTED:
            quote.status = S.Q_ACCEPTED
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "sales_quotation", quote.id, "converted", quote.status, S.Q_ACCEPTED)
        return await self._so_out(so)

    # ============================= sales order =========================== #
    async def create_sales_order(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: SalesOrderCreate
    ) -> SalesOrderOut:
        await self._require_customer(payload.customer_id)
        so = await self._new_sales_order(
            tenant_id=tenant_id, user_id=user_id, customer_id=payload.customer_id,
            branch_id=payload.branch_id, location_id=payload.location_id,
            salesperson_id=payload.salesperson_id or user_id, currency=payload.currency,
            payment_terms=payload.payment_terms, delivery_terms=payload.delivery_terms,
            notes=payload.notes, lines=payload.lines, quotation_id=None,
        )
        return await self._so_out(so)

    async def _new_sales_order(self, *, tenant_id, user_id, customer_id, branch_id, location_id,
                               salesperson_id, currency, payment_terms, delivery_terms, notes,
                               lines, quotation_id) -> SalesOrder:
        so_lines, totals = await self._priced_lines(tenant_id, SalesOrderLine, lines)
        so = SalesOrder(
            tenant_id=tenant_id, so_number=await self.repo.number(tenant_id, "sales_order", "SO"),
            customer_id=customer_id, branch_id=branch_id, location_id=location_id,
            salesperson_id=salesperson_id, quotation_id=quotation_id, currency=currency,
            payment_terms=payment_terms, delivery_terms=delivery_terms, status=S.SO_DRAFT,
            notes=notes, created_by=user_id, **totals,
        )
        so.lines = so_lines
        self.repo.session.add(so)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "sales_order", so.id, "created", None, S.SO_DRAFT)
        return so

    async def confirm_sales_order(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, so_id: uuid.UUID
    ) -> SalesOrderOut:
        so = await self._require(self.repo.get_so(so_id, lock=True), "Sales order")
        if so.status != S.SO_DRAFT:
            raise BusinessRuleError(f"Only a draft sales order can be confirmed (status={so.status}).")
        if so.location_id is None:
            raise BusinessRuleError("A selling location is required to reserve stock.")
        for line in so.lines:
            qty = _d(line.qty)
            err = await self.repo.reserve_line(
                tenant_id=tenant_id, product_id=line.product_id, location_id=so.location_id,
                qty=qty, so_line_id=line.id, user_id=user_id,
            )
            if err:
                raise BusinessRuleError(err)  # rolls back the whole confirmation
            line.reserved_qty = qty
        so.status = S.SO_CONFIRMED
        so.confirmed_at = dt.datetime.now(dt.UTC)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "sales_order", so.id, "confirmed", S.SO_DRAFT, S.SO_CONFIRMED)
        return await self._so_out(so)

    async def cancel_sales_order(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, so_id: uuid.UUID, reason: str | None
    ) -> SalesOrderOut:
        so = await self._require(self.repo.get_so(so_id, lock=True), "Sales order")
        if so.status not in S.SO_CANCELLABLE:
            raise BusinessRuleError(f"Cannot cancel a sales order in status {so.status}.")
        if so.status in S.SO_OPEN_RESERVED:
            for line in so.lines:
                await self.repo.release_reservation(tenant_id=tenant_id, so_line_id=line.id, user_id=user_id)
                line.reserved_qty = Decimal("0")
        old, so.status = so.status, S.SO_CANCELLED
        if reason:
            so.notes = reason
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "sales_order", so.id, "cancelled", old, S.SO_CANCELLED)
        return await self._so_out(so)

    # ============================== delivery ============================= #
    async def create_delivery(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, so_id: uuid.UUID, payload: DeliveryCreate
    ) -> DeliveryNoteOut:
        so = await self._require(self.repo.get_so(so_id, lock=True), "Sales order")
        if so.status not in S.SO_DELIVERABLE:
            raise BusinessRuleError(f"Sales order in status {so.status} cannot be delivered.")
        wanted = {ln.sales_order_line_id: _d(ln.qty) for ln in payload.lines}
        note = DeliveryNote(
            tenant_id=tenant_id, delivery_number=await self.repo.number(tenant_id, "delivery", "DN"),
            sales_order_id=so.id, customer_id=so.customer_id, branch_id=so.branch_id,
            location_id=so.location_id, delivery_address=payload.delivery_address,
            driver=payload.driver, vehicle=payload.vehicle, notes=payload.notes,
            status=S.DN_PENDING, created_by=user_id,
        )
        self.repo.session.add(note)
        await self.repo.session.flush()
        delivered_any = False
        for line in so.lines:
            outstanding = _d(line.qty) - _d(line.delivered_qty)
            qty = wanted.get(line.id, outstanding)
            qty = max(Decimal("0"), min(qty, outstanding))
            if qty <= 0:
                continue
            err = await self.repo.deduct_line(
                tenant_id=tenant_id, product_id=line.product_id, location_id=so.location_id,
                qty=qty, user_id=user_id, reference_id=note.id,
                reason=f"Sales delivery {note.delivery_number}", reservation_ref=line.id,
                demand_source="sale",
            )
            if err:
                raise BusinessRuleError(err)  # rolls back the whole delivery
            line.delivered_qty = _d(line.delivered_qty) + qty
            self.repo.session.add(DeliveryNoteLine(
                tenant_id=tenant_id, delivery_note_id=note.id, sales_order_line_id=line.id,
                product_id=line.product_id, qty=qty,
            ))
            delivered_any = True
        if not delivered_any:
            raise BusinessRuleError("Nothing outstanding to deliver on this sales order.")
        note.status = S.DN_DELIVERED
        note.delivered_at = dt.datetime.now(dt.UTC)
        so.status = S.so_delivery_outcome([(_f(ln.delivered_qty), _f(ln.qty)) for ln in so.lines])
        await self.repo.session.flush()
        await self.repo.session.refresh(note, ["lines"])  # populate the collection for output
        await self._audit(tenant_id, user_id, "sales_delivery", note.id, "delivered", S.DN_PENDING, S.DN_DELIVERED)
        return await self._delivery_out(note)

    async def confirm_delivery_receipt(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, delivery_id: uuid.UUID, payload: DeliveryConfirm
    ) -> DeliveryNoteOut:
        note = await self._require(self.repo.get_delivery(delivery_id, lock=True), "Delivery note")
        note.received_by = payload.received_by
        note.signature = payload.signature
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "sales_delivery", note.id, "receipt_confirmed", note.status, note.status)
        return await self._delivery_out(note)

    # =============================== invoice ============================= #
    async def create_invoice(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: InvoiceCreate
    ) -> InvoiceOut:
        if payload.delivery_note_id is None and payload.sales_order_id is None:
            raise BusinessRuleError("An invoice needs a delivery note or a sales order.")
        delivery = (
            await self._require(self.repo.get_delivery(payload.delivery_note_id), "Delivery note")
            if payload.delivery_note_id else None
        )
        so_id = payload.sales_order_id or (delivery.sales_order_id if delivery else None)
        so = await self._require(self.repo.get_so(so_id), "Sales order") if so_id else None
        if so is None:
            raise BusinessRuleError("Cannot resolve the sales order to invoice.")
        price_by_product = {ln.product_id: ln for ln in so.lines}
        # Bill delivered quantities when invoicing a delivery; otherwise the ordered lines.
        if delivery is not None:
            src = [(dl.product_id, _d(dl.qty)) for dl in delivery.lines]
        else:
            src = [(ln.product_id, _d(ln.qty)) for ln in so.lines]
        inv_lines: list[InvoiceLine] = []
        totals_in = []
        for product_id, qty in src:
            ref = price_by_product.get(product_id)
            unit = _d(ref.unit_price) if ref else Decimal("0")
            disc = _d(ref.discount_pct) if ref else Decimal("0")
            tax = _d(ref.tax_pct) if ref else Decimal("0")
            lt = pricing.line_total(qty, unit, disc, tax)
            inv_lines.append(InvoiceLine(
                tenant_id=tenant_id, product_id=product_id, description=ref.description if ref else None,
                qty=qty, unit_price=unit, discount_pct=disc, tax_pct=tax, line_total=lt,
            ))
            totals_in.append({"qty": _f(qty), "unit_price": _f(unit), "discount_pct": _f(disc), "tax_pct": _f(tax)})
        totals = pricing.document_totals(totals_in)
        invoice = Invoice(
            tenant_id=tenant_id, invoice_number=await self.repo.number(tenant_id, "invoice", "INV"),
            sales_order_id=so.id, delivery_note_id=payload.delivery_note_id, customer_id=so.customer_id,
            branch_id=so.branch_id, currency=so.currency, payment_terms=payload.payment_terms or so.payment_terms,
            due_date=payload.due_date, status=S.INV_SENT, amount_paid=Decimal("0"),
            created_by=user_id, **totals,
        )
        invoice.lines = inv_lines
        self.repo.session.add(invoice)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "sales_invoice", invoice.id, "created", None, S.INV_SENT)
        return await self._invoice_out(invoice)

    # =============================== payment ============================= #
    async def record_payment(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: PaymentCreate,
        branch_id: uuid.UUID | None = None,
    ) -> ReceiptOut:
        invoice = await self._require(self.repo.get_invoice(payload.invoice_id, lock=True), "Invoice")
        if invoice.status not in S.INVOICE_PAYABLE:
            raise BusinessRuleError(f"Invoice in status {invoice.status} cannot take a payment.")
        balance = _d(invoice.grand_total) - _d(invoice.amount_paid)
        total = sum((_d(p.amount) for p in payload.payments), Decimal("0"))
        if total > balance + Decimal("0.0001"):
            raise BusinessRuleError(
                f"Payment {_f(total):g} exceeds the outstanding balance {_f(balance):g}."
            )
        receipt = await self._settle(
            tenant_id=tenant_id, user_id=user_id, invoice=invoice,
            payments=payload.payments, branch_id=branch_id or invoice.branch_id,
        )
        return await self._receipt_out(receipt)

    async def _settle(self, *, tenant_id, user_id, invoice, payments, branch_id) -> Receipt:
        """Create payment rows + a grouping receipt, allocate to the invoice, and advance
        the invoice status. Caller has locked the invoice and validated the total."""
        total = sum((_d(p.amount) for p in payments), Decimal("0"))
        invoice.amount_paid = _d(invoice.amount_paid) + total
        invoice.status = S.invoice_status_after_payment(invoice.grand_total, invoice.amount_paid)
        balance = _d(invoice.grand_total) - _d(invoice.amount_paid)
        receipt = Receipt(
            tenant_id=tenant_id, receipt_number=await self.repo.number(tenant_id, "receipt", "RCP"),
            invoice_id=invoice.id, customer_id=invoice.customer_id, branch_id=branch_id,
            cashier_id=user_id, amount_paid=total, balance=balance,
        )
        self.repo.session.add(receipt)
        await self.repo.session.flush()
        for p in payments:
            payment = Payment(
                tenant_id=tenant_id, payment_number=await self.repo.number(tenant_id, "payment", "PAY"),
                customer_id=invoice.customer_id, branch_id=branch_id, receipt_id=receipt.id,
                method=p.method, amount=_d(p.amount), reference=p.reference, received_by=user_id,
            )
            payment.allocations.append(PaymentAllocation(
                tenant_id=tenant_id, invoice_id=invoice.id, amount=_d(p.amount),
            ))
            self.repo.session.add(payment)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "sales_payment", receipt.id, "recorded", None, invoice.status)
        return receipt

    # ================================ POS =============================== #
    async def pos_checkout(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: PosCheckout
    ) -> PosResult:
        """One fast transaction: confirmed sales order -> immediate delivery (deduct at the
        cashier location, respecting reservations) -> invoice -> payment(s) -> receipt."""
        customer_id = payload.customer_id
        if customer_id:
            await self._require_customer(customer_id)
        else:
            customer_id = await self._walkin_customer(tenant_id, user_id)
        so = await self._new_sales_order(
            tenant_id=tenant_id, user_id=user_id, customer_id=customer_id, branch_id=payload.branch_id,
            location_id=payload.location_id, salesperson_id=user_id, currency=payload.currency,
            payment_terms="pos", delivery_terms=None, notes="POS sale", lines=payload.lines,
            quotation_id=None,
        )
        # Immediate issue at the cashier location (no prior reservation; respects others').
        note = DeliveryNote(
            tenant_id=tenant_id, delivery_number=await self.repo.number(tenant_id, "delivery", "DN"),
            sales_order_id=so.id, customer_id=customer_id, branch_id=payload.branch_id,
            location_id=payload.location_id, status=S.DN_PENDING, created_by=user_id,
        )
        self.repo.session.add(note)
        await self.repo.session.flush()
        for line in so.lines:
            qty = _d(line.qty)
            err = await self.repo.deduct_line(
                tenant_id=tenant_id, product_id=line.product_id, location_id=payload.location_id,
                qty=qty, user_id=user_id, reference_id=note.id,
                reason=f"POS sale {note.delivery_number}", reservation_ref=None, demand_source="pos",
            )
            if err:
                raise BusinessRuleError(err)
            line.delivered_qty = qty
            self.repo.session.add(DeliveryNoteLine(
                tenant_id=tenant_id, delivery_note_id=note.id, sales_order_line_id=line.id,
                product_id=line.product_id, qty=qty,
            ))
        note.status = S.DN_DELIVERED
        note.delivered_at = dt.datetime.now(dt.UTC)
        so.status = S.SO_DELIVERED
        await self.repo.session.flush()  # persist delivery lines before invoicing
        await self.repo.session.refresh(note, ["lines"])
        # Invoice the order, then settle the payment(s) and produce the receipt.
        invoice_out = await self.create_invoice(
            tenant_id=tenant_id, user_id=user_id,
            payload=InvoiceCreate(sales_order_id=so.id, delivery_note_id=note.id),
        )
        invoice = await self.repo.get_invoice(invoice_out.id, lock=True)
        receipt = await self._settle(
            tenant_id=tenant_id, user_id=user_id, invoice=invoice,
            payments=payload.payments, branch_id=payload.branch_id,
        )
        await self.repo.session.flush()
        return PosResult(
            sales_order=await self._so_out(so),
            delivery_note=await self._delivery_out(note),
            invoice=await self._invoice_out(invoice),
            receipt=await self._receipt_out(receipt),
        )

    async def _walkin_customer(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
        """Resolve (or lazily create) the per-tenant 'Walk-in Customer' for cash sales."""
        existing = await self.repo.session.scalar(
            select(Customer).where(Customer.code == "WALK-IN")
        )
        if existing:
            return existing.id
        walkin = Customer(tenant_id=tenant_id, code="WALK-IN", name="Walk-in Customer")
        self.repo.session.add(walkin)
        await self.repo.session.flush()
        return walkin.id

    # =============================== returns ============================= #
    async def create_return(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: ReturnCreate
    ) -> ReturnOut:
        """Receive returned goods back into the chosen branch+location (a stock INFLOW
        through the inventory ledger), against an invoice."""
        invoice = await self._require(self.repo.get_invoice(payload.invoice_id), "Invoice")
        lines = [
            ReturnLine(tenant_id=tenant_id, product_id=ln.product_id, qty=_d(ln.qty),
                       invoice_line_id=ln.invoice_line_id, reason=ln.reason)
            for ln in payload.lines
        ]
        ret = Return(
            tenant_id=tenant_id, return_number=await self.repo.number(tenant_id, "return", "RET"),
            invoice_id=invoice.id, customer_id=invoice.customer_id,
            branch_id=payload.branch_id or invoice.branch_id, location_id=payload.location_id,
            reason=payload.reason, status=S.RET_RECEIVED, notes=payload.notes,
            created_by=user_id, received_at=dt.datetime.now(dt.UTC),
        )
        ret.lines = lines
        self.repo.session.add(ret)
        await self.repo.session.flush()
        for line in ret.lines:
            await self.repo.restock_line(
                tenant_id=tenant_id, product_id=line.product_id, location_id=payload.location_id,
                qty=_d(line.qty), user_id=user_id, reference_id=ret.id,
                reason=f"Customer return {ret.return_number}",
            )
        await self._audit(tenant_id, user_id, "sales_return", ret.id, "received", None, S.RET_RECEIVED)
        return await self._return_out(ret)

    # ============================= credit notes ========================== #
    async def create_credit_note(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: CreditNoteCreate
    ) -> CreditNoteOut:
        ret = await self._require(self.repo.get_return(payload.return_id), "Return")
        if ret.status == S.RET_CANCELLED:
            raise BusinessRuleError("Cannot credit a cancelled return.")
        price_index = await self.repo.invoice_line_index(ret.invoice_id) if ret.invoice_id else {}
        cn_lines: list[CreditNoteLine] = []
        totals_in = []
        for rl in ret.lines:
            ref = price_index.get(rl.product_id)
            unit = _d(ref.unit_price) if ref else Decimal("0")
            disc = _d(ref.discount_pct) if ref else Decimal("0")
            tax = _d(ref.tax_pct) if ref else Decimal("0")
            lt = pricing.line_total(rl.qty, unit, disc, tax)
            cn_lines.append(CreditNoteLine(
                tenant_id=tenant_id, product_id=rl.product_id, description=ref.description if ref else None,
                qty=_d(rl.qty), unit_price=unit, discount_pct=disc, tax_pct=tax, line_total=lt,
            ))
            totals_in.append({"qty": _f(rl.qty), "unit_price": _f(unit), "discount_pct": _f(disc), "tax_pct": _f(tax)})
        totals = pricing.document_totals(totals_in)
        cn = CreditNote(
            tenant_id=tenant_id, credit_note_number=await self.repo.number(tenant_id, "credit_note", "CN"),
            invoice_id=ret.invoice_id, return_id=ret.id, customer_id=ret.customer_id,
            branch_id=ret.branch_id, status=S.CN_DRAFT, created_by=user_id, **totals,
        )
        cn.lines = cn_lines
        self.repo.session.add(cn)
        await self.repo.session.flush()
        ret.status = S.RET_CREDITED
        await self._audit(tenant_id, user_id, "sales_credit_note", cn.id, "created", None, S.CN_DRAFT)
        return await self._credit_note_out(cn)

    async def credit_note_transition(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, cn_id: uuid.UUID, new: str
    ) -> CreditNoteOut:
        cn = await self._require(self.repo.get_credit_note(cn_id, lock=True), "Credit note")
        if not S.cn_can_transition(cn.status, new):
            raise BusinessRuleError(f"Cannot move credit note from {cn.status} to {new}.")
        old, cn.status = cn.status, new
        if new == S.CN_APPLIED:
            cn.applied_at = dt.datetime.now(dt.UTC)
            # Offset the invoice without editing it: bump credit_total + recompute status.
            if cn.invoice_id:
                invoice = await self._require(self.repo.get_invoice(cn.invoice_id, lock=True), "Invoice")
                invoice.credit_total = _d(invoice.credit_total) + _d(cn.grand_total)
                settled = _d(invoice.amount_paid) + _d(invoice.credit_total)
                invoice.status = S.invoice_status_after_payment(invoice.grand_total, settled)
        await self.repo.session.flush()
        await self._audit(tenant_id, user_id, "sales_credit_note", cn.id, new, old, new)
        return await self._credit_note_out(cn)

    async def get_return(self, return_id: uuid.UUID) -> ReturnOut:
        return await self._return_out(await self._require(self.repo.get_return(return_id), "Return"))

    async def get_credit_note(self, cn_id: uuid.UUID) -> CreditNoteOut:
        return await self._credit_note_out(await self._require(self.repo.get_credit_note(cn_id), "Credit note"))

    async def list_returns(self, **f) -> list[ReturnOut]:
        return [await self._return_out(r) for r in await self.repo.list_returns(**f)]

    async def list_credit_notes(self, **f) -> list[CreditNoteOut]:
        return [await self._credit_note_out(c) for c in await self.repo.list_credit_notes(**f)]

    # ================================ reads ============================== #
    async def get_quotation(self, quote_id: uuid.UUID) -> QuotationOut:
        return await self._quote_out(await self._require(self.repo.get_quote(quote_id), "Quotation"))

    async def get_sales_order(self, so_id: uuid.UUID) -> SalesOrderOut:
        return await self._so_out(await self._require(self.repo.get_so(so_id), "Sales order"))

    async def get_delivery(self, delivery_id: uuid.UUID) -> DeliveryNoteOut:
        return await self._delivery_out(await self._require(self.repo.get_delivery(delivery_id), "Delivery note"))

    async def get_invoice(self, invoice_id: uuid.UUID) -> InvoiceOut:
        return await self._invoice_out(await self._require(self.repo.get_invoice(invoice_id), "Invoice"))

    async def list_quotations(self, **f) -> list[QuotationOut]:
        rows = await self.repo.list_quotes(**f)
        return [await self._quote_out(q) for q in rows]

    async def list_sales_orders(self, **f) -> list[SalesOrderOut]:
        rows = await self.repo.list_sos(**f)
        return [await self._so_out(s) for s in rows]

    async def list_invoices(self, **f) -> list[InvoiceOut]:
        rows = await self.repo.list_invoices(**f)
        return [await self._invoice_out(i) for i in rows]

    async def list_deliveries(self, **f) -> list[DeliveryNoteOut]:
        rows = await self.repo.list_deliveries(**f)
        return [await self._delivery_out(d) for d in rows]

    # =============================== helpers ============================ #
    async def _priced_lines(self, tenant_id, line_model, lines: list[PricedLineIn]):
        prices = await self.repo.product_prices([ln.product_id for ln in lines])
        objs, totals_in = [], []
        for ln in lines:
            unit = _d(ln.unit_price) if ln.unit_price is not None else prices.get(ln.product_id, Decimal("0"))
            lt = pricing.line_total(ln.qty, unit, ln.discount_pct, ln.tax_pct)
            objs.append(line_model(
                tenant_id=tenant_id, product_id=ln.product_id, description=ln.description,
                qty=_d(ln.qty), unit_price=unit, discount_pct=_d(ln.discount_pct),
                tax_pct=_d(ln.tax_pct), line_total=lt,
            ))
            totals_in.append({"qty": ln.qty, "unit_price": _f(unit),
                              "discount_pct": ln.discount_pct, "tax_pct": ln.tax_pct})
        return objs, pricing.document_totals(totals_in)

    async def _require_customer(self, customer_id: uuid.UUID) -> None:
        if await self.repo.get_customer(customer_id) is None:
            raise NotFoundError("Customer not found")

    @staticmethod
    async def _require(awaitable, label: str):
        obj = await awaitable
        if obj is None:
            raise NotFoundError(f"{label} not found")
        return obj

    async def _audit(self, tenant_id, user_id, entity_type, entity_id, action, old, new) -> None:
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action=f"{entity_type}.{action}",
            entity_type=entity_type, entity_id=entity_id,
            changes={"old_status": old, "new_status": new},
        )

    # ---- output builders (per-doc enrichment) ---- #
    async def _priced_line_outs(self, lines) -> list[PricedLineOut]:
        prod = await self.repo.product_index([ln.product_id for ln in lines])
        out = []
        for ln in lines:
            sku, name = prod.get(ln.product_id, (None, None))
            out.append(PricedLineOut(
                id=ln.id, product_id=ln.product_id, sku=sku, name=name, description=ln.description,
                qty=_f(ln.qty), unit_price=_f(ln.unit_price), discount_pct=_f(ln.discount_pct),
                tax_pct=_f(ln.tax_pct), line_total=_f(ln.line_total),
            ))
        return out

    async def _quote_out(self, q: Quotation) -> QuotationOut:
        cust = await self.repo.customer_names([q.customer_id])
        br = await self.repo.branch_names([q.branch_id])
        return QuotationOut(
            id=q.id, quote_number=q.quote_number, customer_id=q.customer_id,
            customer_name=cust.get(q.customer_id), branch_id=q.branch_id, branch_name=br.get(q.branch_id),
            salesperson_id=q.salesperson_id, status=q.status, currency=q.currency,
            valid_until=q.valid_until, notes=q.notes, subtotal=_f(q.subtotal),
            discount_total=_f(q.discount_total), tax_total=_f(q.tax_total), grand_total=_f(q.grand_total),
            created_at=q.created_at, lines=await self._priced_line_outs(q.lines),
        )

    async def _so_out(self, so: SalesOrder) -> SalesOrderOut:
        cust = await self.repo.customer_names([so.customer_id])
        br = await self.repo.branch_names([so.branch_id])
        loc = await self.repo.location_names([so.location_id])
        prod = await self.repo.product_index([ln.product_id for ln in so.lines])
        lines = []
        for ln in so.lines:
            sku, name = prod.get(ln.product_id, (None, None))
            outstanding = max(0.0, _f(ln.qty) - _f(ln.delivered_qty))
            lines.append(SalesOrderLineOut(
                id=ln.id, product_id=ln.product_id, sku=sku, name=name, description=ln.description,
                qty=_f(ln.qty), unit_price=_f(ln.unit_price), discount_pct=_f(ln.discount_pct),
                tax_pct=_f(ln.tax_pct), line_total=_f(ln.line_total), reserved_qty=_f(ln.reserved_qty),
                delivered_qty=_f(ln.delivered_qty), outstanding_qty=outstanding,
            ))
        return SalesOrderOut(
            id=so.id, so_number=so.so_number, customer_id=so.customer_id,
            customer_name=cust.get(so.customer_id), branch_id=so.branch_id, branch_name=br.get(so.branch_id),
            location_id=so.location_id, location_name=loc.get(so.location_id),
            salesperson_id=so.salesperson_id, quotation_id=so.quotation_id,
            quote_number=await self.repo.quote_number(so.quotation_id), status=so.status,
            currency=so.currency, payment_terms=so.payment_terms, delivery_terms=so.delivery_terms,
            notes=so.notes, subtotal=_f(so.subtotal), discount_total=_f(so.discount_total),
            tax_total=_f(so.tax_total), grand_total=_f(so.grand_total), created_at=so.created_at, lines=lines,
        )

    async def _delivery_out(self, note: DeliveryNote) -> DeliveryNoteOut:
        cust = await self.repo.customer_names([note.customer_id])
        loc = await self.repo.location_names([note.location_id])
        prod = await self.repo.product_index([ln.product_id for ln in note.lines])
        lines = [
            DeliveryLineOut(id=ln.id, product_id=ln.product_id, sku=prod.get(ln.product_id, (None, None))[0],
                            name=prod.get(ln.product_id, (None, None))[1], qty=_f(ln.qty))
            for ln in note.lines
        ]
        return DeliveryNoteOut(
            id=note.id, delivery_number=note.delivery_number, sales_order_id=note.sales_order_id,
            so_number=await self.repo.so_number(note.sales_order_id), customer_id=note.customer_id,
            customer_name=cust.get(note.customer_id), branch_id=note.branch_id, location_id=note.location_id,
            location_name=loc.get(note.location_id), status=note.status, delivery_address=note.delivery_address,
            driver=note.driver, vehicle=note.vehicle, received_by=note.received_by,
            delivered_at=note.delivered_at, created_at=note.created_at, lines=lines,
        )

    async def _invoice_out(self, inv: Invoice) -> InvoiceOut:
        cust = await self.repo.customer_names([inv.customer_id])
        br = await self.repo.branch_names([inv.branch_id])
        return InvoiceOut(
            id=inv.id, invoice_number=inv.invoice_number, sales_order_id=inv.sales_order_id,
            delivery_note_id=inv.delivery_note_id, customer_id=inv.customer_id,
            customer_name=cust.get(inv.customer_id), branch_id=inv.branch_id, branch_name=br.get(inv.branch_id),
            status=inv.status, currency=inv.currency, invoice_date=inv.invoice_date, due_date=inv.due_date,
            payment_terms=inv.payment_terms, subtotal=_f(inv.subtotal), discount_total=_f(inv.discount_total),
            tax_total=_f(inv.tax_total), grand_total=_f(inv.grand_total), amount_paid=_f(inv.amount_paid),
            credit_total=_f(inv.credit_total),
            balance=_f(inv.grand_total) - _f(inv.amount_paid) - _f(inv.credit_total), created_at=inv.created_at,
            lines=await self._priced_line_outs(inv.lines),
        )

    async def _return_out(self, ret: Return) -> ReturnOut:
        cust = await self.repo.customer_names([ret.customer_id])
        loc = await self.repo.location_names([ret.location_id])
        prod = await self.repo.product_index([ln.product_id for ln in ret.lines])
        inv_no = None
        if ret.invoice_id:
            inv = await self.repo.get_invoice(ret.invoice_id)
            inv_no = inv.invoice_number if inv else None
        lines = [
            ReturnLineOut(id=ln.id, product_id=ln.product_id, sku=prod.get(ln.product_id, (None, None))[0],
                          name=prod.get(ln.product_id, (None, None))[1], qty=_f(ln.qty), reason=ln.reason)
            for ln in ret.lines
        ]
        return ReturnOut(
            id=ret.id, return_number=ret.return_number, invoice_id=ret.invoice_id, invoice_number=inv_no,
            customer_id=ret.customer_id, customer_name=cust.get(ret.customer_id), branch_id=ret.branch_id,
            location_id=ret.location_id, location_name=loc.get(ret.location_id), reason=ret.reason,
            status=ret.status, notes=ret.notes, received_at=ret.received_at, created_at=ret.created_at, lines=lines,
        )

    async def _credit_note_out(self, cn: CreditNote) -> CreditNoteOut:
        cust = await self.repo.customer_names([cn.customer_id])
        inv_no = None
        if cn.invoice_id:
            inv = await self.repo.get_invoice(cn.invoice_id)
            inv_no = inv.invoice_number if inv else None
        return CreditNoteOut(
            id=cn.id, credit_note_number=cn.credit_note_number, invoice_id=cn.invoice_id, invoice_number=inv_no,
            return_id=cn.return_id, customer_id=cn.customer_id, customer_name=cust.get(cn.customer_id),
            branch_id=cn.branch_id, status=cn.status, subtotal=_f(cn.subtotal), discount_total=_f(cn.discount_total),
            tax_total=_f(cn.tax_total), grand_total=_f(cn.grand_total), notes=cn.notes, applied_at=cn.applied_at,
            created_at=cn.created_at, lines=await self._priced_line_outs(cn.lines),
        )

    async def _receipt_out(self, receipt: Receipt) -> ReceiptOut:
        cust = await self.repo.customer_names([receipt.customer_id]) if receipt.customer_id else {}
        inv_no = None
        if receipt.invoice_id:
            inv = await self.repo.get_invoice(receipt.invoice_id)
            inv_no = inv.invoice_number if inv else None
        methods = [
            PaymentOut(id=p.id, payment_number=p.payment_number, method=p.method,
                       amount=_f(p.amount), reference=p.reference, created_at=p.created_at)
            for p in await self.repo.session.scalars(
                select(Payment).where(Payment.receipt_id == receipt.id)
            )
        ]
        return ReceiptOut(
            id=receipt.id, receipt_number=receipt.receipt_number, invoice_id=receipt.invoice_id,
            invoice_number=inv_no, customer_id=receipt.customer_id,
            customer_name=cust.get(receipt.customer_id), cashier_id=receipt.cashier_id,
            amount_paid=_f(receipt.amount_paid), balance=_f(receipt.balance), methods=methods,
            created_at=receipt.created_at,
        )
