"""Finance API (PR 1): accounts + derived balances.

Reads require ``finance.read`` and are branch-scoped (a Lusaka user never sees Solwezi
accounts); account admin requires ``finance.account.manage``. There is deliberately NO
delete endpoint for any financial record — accounts are DEACTIVATED, never deleted.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.v1.deps import (
    CurrentUser,
    get_finance_service,
    require_permission,
    resolve_branch_scope,
)
from app.core.permissions import P
from app.finance.schemas import (
    AccountBalanceOut,
    AccountCreate,
    AccountOut,
    AccountUpdate,
    PaymentMappingOut,
    PaymentMappingSet,
)
from app.finance.service import FinanceService

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
