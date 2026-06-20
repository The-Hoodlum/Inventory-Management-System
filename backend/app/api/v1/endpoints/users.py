"""User-management endpoints: list / create / get / update / deactivate, plus
assignable roles. All require the ``user.manage`` permission."""
from __future__ import annotations

import math
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.v1.deps import CurrentUser, get_user_admin_service, require_permission
from app.core.permissions import P
from app.schemas.common import Page
from app.schemas.user import RoleOut, UserCreate, UserOut, UserUpdate
from app.services.user_service import UserAdminService

router = APIRouter()

UserStatus = Literal["active", "inactive"]


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=Page[UserOut])
async def list_users(
    search: str | None = Query(default=None, description="Match email or name"),
    status_: UserStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    user: CurrentUser = Depends(require_permission(P.USER_MANAGE)),
    svc: UserAdminService = Depends(get_user_admin_service),
) -> Page[UserOut]:
    items, total = await svc.list(
        tenant_id=user.tenant_id, search=search, status=status_, page=page, page_size=page_size
    )
    return Page[UserOut](
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.USER_MANAGE)),
    svc: UserAdminService = Depends(get_user_admin_service),
) -> UserOut:
    return await svc.create(
        tenant_id=user.tenant_id, actor_id=user.id, data=payload, ip=_ip(request)
    )


# Declared before "/{user_id}" so the static path wins.
@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    user: CurrentUser = Depends(require_permission(P.USER_MANAGE)),
    svc: UserAdminService = Depends(get_user_admin_service),
) -> list[RoleOut]:
    return await svc.list_roles(tenant_id=user.tenant_id)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.USER_MANAGE)),
    svc: UserAdminService = Depends(get_user_admin_service),
) -> UserOut:
    return await svc.get(tenant_id=user.tenant_id, user_id=user_id)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.USER_MANAGE)),
    svc: UserAdminService = Depends(get_user_admin_service),
) -> UserOut:
    return await svc.update(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        user_id=user_id,
        data=payload,
        ip=_ip(request),
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_permission(P.USER_MANAGE)),
    svc: UserAdminService = Depends(get_user_admin_service),
) -> Response:
    await svc.deactivate(
        tenant_id=user.tenant_id, actor_id=user.id, user_id=user_id, ip=_ip(request)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
