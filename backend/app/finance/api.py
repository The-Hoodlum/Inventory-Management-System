"""Finance API (PR 1): accounts + derived balances.

Reads require ``finance.read`` and are branch-scoped (a Lusaka user never sees Solwezi
accounts); account admin requires ``finance.account.manage``. There is deliberately NO
delete endpoint for any financial record — accounts are DEACTIVATED, never deleted.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status

from app.api.v1.deps import (
    CurrentUser,
    get_finance_service,
    require_permission,
    resolve_branch_scope,
)
from app.core.exceptions import BusinessRuleError
from app.core.permissions import P
from app.finance.schemas import (
    AccountBalanceOut,
    AccountCreate,
    AccountOut,
    AccountStatementOut,
    AccountUpdate,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    DayBookOut,
    ExpenseCreate,
    ExpenseOut,
    ExpenseUpdate,
    ExpenseVoid,
    FinanceDashboardOut,
    HandoverConfirm,
    HandoverCreate,
    HandoverOut,
    PaymentMappingOut,
    PaymentMappingSet,
    ReverseRequest,
    TransferCreate,
    TransferOut,
)
from app.finance.service import FinanceService

_MAX_RANGE_DAYS = 400

router = APIRouter()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _allowed(user: CurrentUser) -> frozenset[uuid.UUID] | None:
    """The user's branch boundary as the service expects it: ``None`` = unrestricted."""
    return None if user.all_branches else user.branch_ids


@router.post("/accounts", response_model=AccountOut, status_code=201)
async def create_account(
    payload: AccountCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_ACCOUNT_MANAGE)),
    svc: FinanceService = Depends(get_finance_service),
) -> AccountOut:
    return await svc.create_account(
        tenant_id=user.tenant_id, user_id=user.id, data=payload,
        allowed_branch_ids=_allowed(user), ip=_ip(request),
    )


@router.get("/accounts", response_model=list[AccountBalanceOut])
async def list_accounts(
    branch_id: uuid.UUID | None = Query(default=None),
    active_only: bool = Query(default=False),
    type: str | None = Query(default=None),
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> list[AccountBalanceOut]:
    # resolve_branch_scope: unrestricted -> the requested branch or all; scoped -> the
    # requested (403 if not theirs) or ALL of theirs.
    scope = resolve_branch_scope(user, branch_id)
    allowed = None if scope is None else frozenset(scope)
    return await svc.list_accounts(allowed_branch_ids=allowed, active_only=active_only, type=type)


@router.get("/accounts/{account_id}", response_model=AccountBalanceOut)
async def get_account(
    account_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> AccountBalanceOut:
    return await svc.get_account(account_id=account_id, allowed_branch_ids=_allowed(user))


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: uuid.UUID,
    payload: AccountUpdate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_ACCOUNT_MANAGE)),
    svc: FinanceService = Depends(get_finance_service),
) -> AccountOut:
    return await svc.update_account(
        tenant_id=user.tenant_id, user_id=user.id, account_id=account_id, data=payload,
        allowed_branch_ids=_allowed(user), ip=_ip(request),
    )


# --------------------------------------------------------------------------- #
# Money-in: per-branch payment-method -> account mapping
# --------------------------------------------------------------------------- #
@router.get("/payment-mappings", response_model=list[PaymentMappingOut])
async def list_payment_mappings(
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> list[PaymentMappingOut]:
    return await svc.list_mappings(allowed_branch_ids=_allowed(user))


@router.put("/payment-mappings", response_model=PaymentMappingOut)
async def set_payment_mapping(
    payload: PaymentMappingSet,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_ACCOUNT_MANAGE)),
    svc: FinanceService = Depends(get_finance_service),
) -> PaymentMappingOut:
    return await svc.set_mapping(
        tenant_id=user.tenant_id, user_id=user.id, branch_id=payload.branch_id,
        method=payload.method, account_id=payload.account_id,
        allowed_branch_ids=_allowed(user), ip=_ip(request),
    )


@router.delete(
    "/payment-mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_payment_mapping(
    mapping_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_ACCOUNT_MANAGE)),
    svc: FinanceService = Depends(get_finance_service),
) -> Response:
    await svc.delete_mapping(
        tenant_id=user.tenant_id, user_id=user.id, mapping_id=mapping_id,
        allowed_branch_ids=_allowed(user), ip=_ip(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Expense categories (configurable tenant list)
# --------------------------------------------------------------------------- #
@router.get("/expense-categories", response_model=list[CategoryOut])
async def list_categories(
    active_only: bool = Query(default=False),
    _: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> list[CategoryOut]:
    return await svc.list_categories(active_only=active_only)


@router.post("/expense-categories", response_model=CategoryOut, status_code=201)
async def create_category(
    payload: CategoryCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_EXPENSE_MANAGE)),
    svc: FinanceService = Depends(get_finance_service),
) -> CategoryOut:
    return await svc.create_category(
        tenant_id=user.tenant_id, user_id=user.id, name=payload.name, ip=_ip(request))


@router.patch("/expense-categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_EXPENSE_MANAGE)),
    svc: FinanceService = Depends(get_finance_service),
) -> CategoryOut:
    return await svc.update_category(
        tenant_id=user.tenant_id, user_id=user.id, category_id=category_id,
        name=payload.name, is_active=payload.is_active, ip=_ip(request))


# --------------------------------------------------------------------------- #
# Expenses (money out) — manager-recorded, view within branch scope
# --------------------------------------------------------------------------- #
@router.get("/expenses", response_model=list[ExpenseOut])
async def list_expenses(
    branch_id: uuid.UUID | None = Query(default=None),
    category_id: uuid.UUID | None = Query(default=None),
    account_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> list[ExpenseOut]:
    scope = resolve_branch_scope(user, branch_id)
    allowed = None if scope is None else frozenset(scope)
    return await svc.list_expenses(
        allowed_branch_ids=allowed, category_id=category_id, account_id=account_id,
        status=status_filter, date_from=date_from, date_to=date_to)


@router.get("/expenses/{expense_id}", response_model=ExpenseOut)
async def get_expense(
    expense_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> ExpenseOut:
    return await svc.get_expense(expense_id=expense_id, allowed_branch_ids=_allowed(user))


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
async def create_expense(
    payload: ExpenseCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_EXPENSE_MANAGE)),
    svc: FinanceService = Depends(get_finance_service),
) -> ExpenseOut:
    return await svc.create_expense(
        tenant_id=user.tenant_id, user_id=user.id, data=payload,
        allowed_branch_ids=_allowed(user), ip=_ip(request))


@router.patch("/expenses/{expense_id}", response_model=ExpenseOut)
async def update_expense(
    expense_id: uuid.UUID,
    payload: ExpenseUpdate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_EXPENSE_MANAGE)),
    svc: FinanceService = Depends(get_finance_service),
) -> ExpenseOut:
    return await svc.update_expense(
        tenant_id=user.tenant_id, user_id=user.id, expense_id=expense_id, data=payload,
        allowed_branch_ids=_allowed(user), ip=_ip(request))


@router.post("/expenses/{expense_id}/void", response_model=ExpenseOut)
async def void_expense(
    expense_id: uuid.UUID,
    payload: ExpenseVoid,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_EXPENSE_MANAGE)),
    svc: FinanceService = Depends(get_finance_service),
) -> ExpenseOut:
    return await svc.void_expense(
        tenant_id=user.tenant_id, user_id=user.id, expense_id=expense_id,
        reason=payload.reason, allowed_branch_ids=_allowed(user), ip=_ip(request))


@router.post("/expenses/{expense_id}/attachment", status_code=204, response_class=Response)
async def upload_expense_attachment(
    expense_id: uuid.UUID,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission(P.FINANCE_EXPENSE_MANAGE)),
    svc: FinanceService = Depends(get_finance_service),
) -> Response:
    data = await file.read()
    await svc.set_attachment(
        tenant_id=user.tenant_id, user_id=user.id, expense_id=expense_id,
        filename=file.filename or "receipt", content_type=file.content_type, data=data,
        allowed_branch_ids=_allowed(user))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/expenses/{expense_id}/attachment")
async def download_expense_attachment(
    expense_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> Response:
    data, filename, content_type = await svc.get_attachment(
        expense_id=expense_id, allowed_branch_ids=_allowed(user))
    return Response(
        content=data, media_type=content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{filename}"'})


# --------------------------------------------------------------------------- #
# Account transfers (paired OUT + IN)
# --------------------------------------------------------------------------- #
@router.get("/transfers", response_model=list[TransferOut])
async def list_transfers(
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> list[TransferOut]:
    return await svc.list_transfers(allowed_branch_ids=_allowed(user))


@router.post("/transfers", response_model=TransferOut, status_code=201)
async def create_transfer(
    payload: TransferCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_TRANSFER)),
    svc: FinanceService = Depends(get_finance_service),
) -> TransferOut:
    return await svc.create_transfer(
        tenant_id=user.tenant_id, user_id=user.id, data=payload,
        allowed_branch_ids=_allowed(user), ip=_ip(request))


@router.post("/transfers/{transfer_id}/reverse", response_model=TransferOut)
async def reverse_transfer(
    transfer_id: uuid.UUID,
    payload: ReverseRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_TRANSFER)),
    svc: FinanceService = Depends(get_finance_service),
) -> TransferOut:
    return await svc.reverse_transfer(
        tenant_id=user.tenant_id, user_id=user.id, transfer_id=transfer_id,
        reason=payload.reason, allowed_branch_ids=_allowed(user), ip=_ip(request))


# --------------------------------------------------------------------------- #
# Cash handovers (two-sided: OUT on record, IN on confirm)
# --------------------------------------------------------------------------- #
@router.get("/handovers", response_model=list[HandoverOut])
async def list_handovers(
    branch_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    person: str | None = Query(default=None),
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> list[HandoverOut]:
    scope = resolve_branch_scope(user, branch_id)
    allowed = None if scope is None else frozenset(scope)
    return await svc.list_handovers(
        allowed_branch_ids=allowed, status=status_filter, person=person,
        date_from=date_from, date_to=date_to)


@router.get("/handovers/{handover_id}", response_model=HandoverOut)
async def get_handover(
    handover_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> HandoverOut:
    return await svc.get_handover(handover_id=handover_id, allowed_branch_ids=_allowed(user))


@router.post("/handovers", response_model=HandoverOut, status_code=201)
async def create_handover(
    payload: HandoverCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_HANDOVER)),
    svc: FinanceService = Depends(get_finance_service),
) -> HandoverOut:
    return await svc.create_handover(
        tenant_id=user.tenant_id, user_id=user.id, data=payload,
        allowed_branch_ids=_allowed(user), ip=_ip(request))


@router.post("/handovers/{handover_id}/confirm", response_model=HandoverOut)
async def confirm_handover(
    handover_id: uuid.UUID,
    payload: HandoverConfirm,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_HANDOVER)),
    svc: FinanceService = Depends(get_finance_service),
) -> HandoverOut:
    return await svc.confirm_handover(
        tenant_id=user.tenant_id, user_id=user.id, handover_id=handover_id,
        confirmed_amount=payload.confirmed_amount, discrepancy_reason=payload.discrepancy_reason,
        allowed_branch_ids=_allowed(user), ip=_ip(request))


@router.post("/handovers/{handover_id}/reverse", response_model=HandoverOut)
async def reverse_handover(
    handover_id: uuid.UUID,
    payload: ReverseRequest,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.FINANCE_HANDOVER)),
    svc: FinanceService = Depends(get_finance_service),
) -> HandoverOut:
    return await svc.reverse_handover(
        tenant_id=user.tenant_id, user_id=user.id, handover_id=handover_id,
        reason=payload.reason, allowed_branch_ids=_allowed(user), ip=_ip(request))


@router.post("/handovers/{handover_id}/attachment", status_code=204, response_class=Response)
async def upload_handover_attachment(
    handover_id: uuid.UUID,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission(P.FINANCE_HANDOVER)),
    svc: FinanceService = Depends(get_finance_service),
) -> Response:
    data = await file.read()
    await svc.set_handover_attachment(
        tenant_id=user.tenant_id, user_id=user.id, handover_id=handover_id,
        filename=file.filename or "slip", content_type=file.content_type, data=data,
        allowed_branch_ids=_allowed(user))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/handovers/{handover_id}/attachment")
async def download_handover_attachment(
    handover_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> Response:
    data, filename, content_type = await svc.get_handover_attachment(
        handover_id=handover_id, allowed_branch_ids=_allowed(user))
    return Response(
        content=data, media_type=content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{filename}"'})


@router.get("/handovers/{handover_id}/slip")
async def handover_slip_pdf(
    handover_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> Response:
    pdf, name = await svc.handover_slip_pdf(handover_id=handover_id, allowed_branch_ids=_allowed(user))
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


# --------------------------------------------------------------------------- #
# Dashboard, account statement, day book / cash position
# --------------------------------------------------------------------------- #
def _range(date_from: dt.date | None, date_to: dt.date | None) -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    date_to = date_to or today
    date_from = date_from or (date_to - dt.timedelta(days=30))
    if date_from > date_to:
        raise BusinessRuleError("date_from must not be after date_to.")
    if (date_to - date_from).days > _MAX_RANGE_DAYS:
        raise BusinessRuleError("The date range is too large.")
    return date_from, date_to


@router.get("/dashboard", response_model=FinanceDashboardOut)
async def dashboard(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    branch_id: uuid.UUID | None = Query(default=None),
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> FinanceDashboardOut:
    df, dto = _range(date_from, date_to)
    scope = resolve_branch_scope(user, branch_id)
    allowed = None if scope is None else frozenset(scope)
    return await svc.dashboard(allowed_branch_ids=allowed, date_from=df, date_to=dto)


@router.get("/accounts/{account_id}/statement", response_model=AccountStatementOut)
async def account_statement(
    account_id: uuid.UUID,
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> AccountStatementOut:
    df, dto = _range(date_from, date_to)
    return await svc.account_statement(
        account_id=account_id, date_from=df, date_to=dto, allowed_branch_ids=_allowed(user))


@router.get("/accounts/{account_id}/statement.pdf")
async def account_statement_pdf(
    account_id: uuid.UUID,
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> Response:
    df, dto = _range(date_from, date_to)
    pdf, name = await svc.account_statement_pdf(
        account_id=account_id, date_from=df, date_to=dto, allowed_branch_ids=_allowed(user))
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@router.get("/day-book", response_model=DayBookOut)
async def day_book(
    period: str = Query(default="daily"),
    date: dt.date | None = Query(default=None),
    branch_id: uuid.UUID | None = Query(default=None),
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> DayBookOut:
    if period not in ("daily", "monthly"):
        raise BusinessRuleError("period must be daily or monthly.")
    scope = resolve_branch_scope(user, branch_id)
    allowed = None if scope is None else frozenset(scope)
    return await svc.day_book(allowed_branch_ids=allowed, period=period, on=date or dt.date.today())


@router.get("/day-book.pdf")
async def day_book_pdf(
    period: str = Query(default="daily"),
    date: dt.date | None = Query(default=None),
    branch_id: uuid.UUID | None = Query(default=None),
    user: CurrentUser = Depends(require_permission(P.FINANCE_READ)),
    svc: FinanceService = Depends(get_finance_service),
) -> Response:
    if period not in ("daily", "monthly"):
        raise BusinessRuleError("period must be daily or monthly.")
    scope = resolve_branch_scope(user, branch_id)
    allowed = None if scope is None else frozenset(scope)
    pdf, name = await svc.day_book_pdf(allowed_branch_ids=allowed, period=period, on=date or dt.date.today())
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})
