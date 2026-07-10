"""Sales & Distribution endpoints (mounted at /api/v1/sales). Gated on the sales module."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query, Response

from app.api.v1.deps import (
    CurrentUser,
    get_motorcycle_service,
    get_sales_service,
    require_feature,
    require_permission,
    resolve_branch_scope,
)
from app.core.exceptions import BusinessRuleError
from app.core.permissions import P
from app.motorcycles.service import MotorcycleService
from app.sales.schemas import (
    BikeSaleIn,
    BikeSaleResult,
    CancelBody,
    ConvertToOrder,
    CreditNoteCreate,
    CreditNoteOut,
    DeliveryConfirm,
    DeliveryCreate,
    DeliveryNoteOut,
    InvoiceCreate,
    InvoiceOut,
    PartsSaleLineOut,
    PaymentCreate,
    PosCheckout,
    PosResult,
    QuotationCreate,
    QuotationOut,
    ReceiptOut,
    RejectBody,
    ReturnCreate,
    ReturnOut,
    SalesOrderCreate,
    SalesOrderOut,
)
from app.sales.service import SalesService

router = APIRouter(dependencies=[Depends(require_feature("sales_orders"))])


# -------------------------------- quotations ------------------------------- #
@router.post("/quotations", response_model=QuotationOut, status_code=201)
async def create_quotation(
    payload: QuotationCreate,
    user: CurrentUser = Depends(require_permission(P.SALES_QUOTE)),
    svc: SalesService = Depends(get_sales_service),
) -> QuotationOut:
    return await svc.create_quotation(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("/quotations", response_model=list[QuotationOut])
async def list_quotations(
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> list[QuotationOut]:
    return await svc.list_quotations(status=status_filter, customer_id=customer_id, limit=limit)


@router.get("/quotations/{quote_id}", response_model=QuotationOut)
async def get_quotation(
    quote_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> QuotationOut:
    return await svc.get_quotation(quote_id)


@router.post("/quotations/{quote_id}/send", response_model=QuotationOut)
async def send_quotation(
    quote_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.SALES_QUOTE)),
    svc: SalesService = Depends(get_sales_service),
) -> QuotationOut:
    return await svc.quote_transition(tenant_id=user.tenant_id, user_id=user.id, quote_id=quote_id, new="sent")


@router.post("/quotations/{quote_id}/accept", response_model=QuotationOut)
async def accept_quotation(
    quote_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.SALES_QUOTE)),
    svc: SalesService = Depends(get_sales_service),
) -> QuotationOut:
    return await svc.quote_transition(tenant_id=user.tenant_id, user_id=user.id, quote_id=quote_id, new="accepted")


@router.post("/quotations/{quote_id}/reject", response_model=QuotationOut)
async def reject_quotation(
    quote_id: uuid.UUID,
    payload: RejectBody,
    user: CurrentUser = Depends(require_permission(P.SALES_QUOTE)),
    svc: SalesService = Depends(get_sales_service),
) -> QuotationOut:
    return await svc.quote_transition(
        tenant_id=user.tenant_id, user_id=user.id, quote_id=quote_id, new="rejected", reason=payload.reason
    )


@router.post("/quotations/{quote_id}/cancel", response_model=QuotationOut)
async def cancel_quotation(
    quote_id: uuid.UUID,
    payload: CancelBody,
    user: CurrentUser = Depends(require_permission(P.SALES_QUOTE)),
    svc: SalesService = Depends(get_sales_service),
) -> QuotationOut:
    return await svc.quote_transition(
        tenant_id=user.tenant_id, user_id=user.id, quote_id=quote_id, new="cancelled", reason=payload.reason
    )


@router.post("/quotations/{quote_id}/convert", response_model=SalesOrderOut, status_code=201)
async def convert_quotation(
    quote_id: uuid.UUID,
    payload: ConvertToOrder,
    user: CurrentUser = Depends(require_permission(P.SALES_ORDER)),
    svc: SalesService = Depends(get_sales_service),
) -> SalesOrderOut:
    return await svc.convert_quotation(tenant_id=user.tenant_id, user_id=user.id, quote_id=quote_id, payload=payload)


# ------------------------------- sales orders ------------------------------ #
@router.post("/orders", response_model=SalesOrderOut, status_code=201)
async def create_sales_order(
    payload: SalesOrderCreate,
    user: CurrentUser = Depends(require_permission(P.SALES_ORDER)),
    svc: SalesService = Depends(get_sales_service),
) -> SalesOrderOut:
    return await svc.create_sales_order(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("/orders", response_model=list[SalesOrderOut])
async def list_sales_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> list[SalesOrderOut]:
    return await svc.list_sales_orders(status=status_filter, customer_id=customer_id, limit=limit)


@router.get("/orders/{so_id}", response_model=SalesOrderOut)
async def get_sales_order(
    so_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> SalesOrderOut:
    return await svc.get_sales_order(so_id)


@router.post("/orders/{so_id}/confirm", response_model=SalesOrderOut)
async def confirm_sales_order(
    so_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.SALES_ORDER)),
    svc: SalesService = Depends(get_sales_service),
) -> SalesOrderOut:
    return await svc.confirm_sales_order(tenant_id=user.tenant_id, user_id=user.id, so_id=so_id)


@router.post("/orders/{so_id}/cancel", response_model=SalesOrderOut)
async def cancel_sales_order(
    so_id: uuid.UUID,
    payload: CancelBody,
    user: CurrentUser = Depends(require_permission(P.SALES_ORDER)),
    svc: SalesService = Depends(get_sales_service),
) -> SalesOrderOut:
    return await svc.cancel_sales_order(
        tenant_id=user.tenant_id, user_id=user.id, so_id=so_id, reason=payload.reason
    )


@router.post("/orders/{so_id}/deliver", response_model=DeliveryNoteOut, status_code=201)
async def deliver_sales_order(
    so_id: uuid.UUID,
    payload: DeliveryCreate,
    user: CurrentUser = Depends(require_permission(P.SALES_DELIVER)),
    svc: SalesService = Depends(get_sales_service),
) -> DeliveryNoteOut:
    return await svc.create_delivery(tenant_id=user.tenant_id, user_id=user.id, so_id=so_id, payload=payload)


# -------------------------------- deliveries ------------------------------- #
@router.get("/deliveries", response_model=list[DeliveryNoteOut])
async def list_deliveries(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> list[DeliveryNoteOut]:
    return await svc.list_deliveries(status=status_filter, limit=limit)


@router.get("/deliveries/{delivery_id}", response_model=DeliveryNoteOut)
async def get_delivery(
    delivery_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> DeliveryNoteOut:
    return await svc.get_delivery(delivery_id)


@router.post("/deliveries/{delivery_id}/confirm", response_model=DeliveryNoteOut)
async def confirm_delivery(
    delivery_id: uuid.UUID,
    payload: DeliveryConfirm,
    user: CurrentUser = Depends(require_permission(P.SALES_DELIVER)),
    svc: SalesService = Depends(get_sales_service),
) -> DeliveryNoteOut:
    return await svc.confirm_delivery_receipt(
        tenant_id=user.tenant_id, user_id=user.id, delivery_id=delivery_id, payload=payload
    )


# --------------------------------- invoices -------------------------------- #
@router.post("/invoices", response_model=InvoiceOut, status_code=201)
async def create_invoice(
    payload: InvoiceCreate,
    user: CurrentUser = Depends(require_permission(P.SALES_INVOICE)),
    svc: SalesService = Depends(get_sales_service),
) -> InvoiceOut:
    return await svc.create_invoice(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("/invoices", response_model=list[InvoiceOut])
async def list_invoices(
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> list[InvoiceOut]:
    return await svc.list_invoices(status=status_filter, customer_id=customer_id, limit=limit)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
async def get_invoice(
    invoice_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> InvoiceOut:
    return await svc.get_invoice(invoice_id)


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(
    invoice_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> Response:
    pdf, number = await svc.invoice_pdf(tenant_id=user.tenant_id, invoice_id=invoice_id)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{number}.pdf"'},
    )


# ------------------------------- parts sales ------------------------------- #
@router.get("/parts-sales", response_model=list[PartsSaleLineOut])
async def list_parts_sales(
    branch_id: uuid.UUID | None = Query(default=None),
    product_id: uuid.UUID | None = Query(default=None),
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    user: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> list[PartsSaleLineOut]:
    # Line-grain spare-part sales (fungible products), newest first; excludes
    # motorcycle-linked invoices so a serialized-unit sale never appears here.
    return await svc.list_parts_sales(
        branch_ids=resolve_branch_scope(user, branch_id), product_id=product_id,
        date_from=date_from, date_to=date_to, limit=limit,
    )


# --------------------------- payments + receipts --------------------------- #
@router.post("/payments", response_model=ReceiptOut, status_code=201)
async def record_payment(
    payload: PaymentCreate,
    user: CurrentUser = Depends(require_permission(P.SALES_PAYMENT)),
    svc: SalesService = Depends(get_sales_service),
) -> ReceiptOut:
    return await svc.record_payment(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


# ----------------------------------- POS ----------------------------------- #
@router.post("/pos/checkout", response_model=PosResult, status_code=201)
async def pos_checkout(
    payload: PosCheckout,
    user: CurrentUser = Depends(require_permission(P.POS_USE)),
    svc: SalesService = Depends(get_sales_service),
) -> PosResult:
    return await svc.pos_checkout(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.post("/bike-sale", response_model=BikeSaleResult, status_code=201)
async def sell_bike(
    payload: BikeSaleIn,
    user: CurrentUser = Depends(require_permission(P.MOTORCYCLE_MANAGE)),
    svc: SalesService = Depends(get_sales_service),
    motorcycles: MotorcycleService = Depends(get_motorcycle_service),
) -> BikeSaleResult:
    """Sell a serialized bike from POS or Sales: bike invoice + mark sold + optional
    payment/receipt, in one transaction. Shares the request session with the motorcycle
    service, so the invoice + the unit's sold-state commit or roll back together."""
    return await svc.sell_bike(
        tenant_id=user.tenant_id, user_id=user.id, payload=payload, motorcycles=motorcycles,
    )


# --------------------------- returns + credit notes ------------------------ #
@router.post("/returns", response_model=ReturnOut, status_code=201)
async def create_return(
    payload: ReturnCreate,
    user: CurrentUser = Depends(require_permission(P.SALES_RETURN)),
    svc: SalesService = Depends(get_sales_service),
) -> ReturnOut:
    return await svc.create_return(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("/returns", response_model=list[ReturnOut])
async def list_returns(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> list[ReturnOut]:
    return await svc.list_returns(status=status_filter, limit=limit)


@router.get("/returns/{return_id}", response_model=ReturnOut)
async def get_return(
    return_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> ReturnOut:
    return await svc.get_return(return_id)


@router.post("/credit-notes", response_model=CreditNoteOut, status_code=201)
async def create_credit_note(
    payload: CreditNoteCreate,
    user: CurrentUser = Depends(require_permission(P.SALES_RETURN)),
    svc: SalesService = Depends(get_sales_service),
) -> CreditNoteOut:
    return await svc.create_credit_note(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("/credit-notes", response_model=list[CreditNoteOut])
async def list_credit_notes(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> list[CreditNoteOut]:
    return await svc.list_credit_notes(status=status_filter, limit=limit)


@router.get("/credit-notes/{cn_id}", response_model=CreditNoteOut)
async def get_credit_note(
    cn_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.SALES_READ)),
    svc: SalesService = Depends(get_sales_service),
) -> CreditNoteOut:
    return await svc.get_credit_note(cn_id)


@router.post("/credit-notes/{cn_id}/{action}", response_model=CreditNoteOut)
async def credit_note_action(
    cn_id: uuid.UUID,
    action: str,
    user: CurrentUser = Depends(require_permission(P.SALES_RETURN)),
    svc: SalesService = Depends(get_sales_service),
) -> CreditNoteOut:
    # action in approve | apply | cancel
    mapping = {"approve": "approved", "apply": "applied", "cancel": "cancelled"}
    if action not in mapping:
        raise BusinessRuleError(f"Unknown credit-note action '{action}'.")
    return await svc.credit_note_transition(
        tenant_id=user.tenant_id, user_id=user.id, cn_id=cn_id, new=mapping[action]
    )
