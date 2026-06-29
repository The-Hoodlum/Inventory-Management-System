"""Sales & Distribution endpoints (mounted at /api/v1/sales). Gated on the sales module."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import (
    CurrentUser,
    get_sales_service,
    require_feature,
    require_permission,
)
from app.core.permissions import P
from app.sales.schemas import (
    CancelBody,
    ConvertToOrder,
    DeliveryConfirm,
    DeliveryCreate,
    DeliveryNoteOut,
    InvoiceCreate,
    InvoiceOut,
    PaymentCreate,
    PosCheckout,
    PosResult,
    QuotationCreate,
    QuotationOut,
    ReceiptOut,
    RejectBody,
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
