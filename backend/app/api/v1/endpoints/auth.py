"""Authentication endpoints: login, token refresh, logout, current-user info."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, get_auth_service, get_current_user, get_db
from app.models import UserWarehouseAccess
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)
from app.services.auth_service import AuthService

router = APIRouter()


def _client(request: Request) -> tuple[str | None, str | None]:
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    return ua, ip


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    user = await auth.authenticate(
        email=payload.email,
        password=payload.password,
        tenant_slug=payload.tenant_slug,
    )
    ua, ip = _client(request)
    tokens = await auth.issue_tokens(user, user_agent=ua, ip=ip)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    ua, ip = _client(request)
    tokens = await auth.refresh(payload.refresh_token, user_agent=ua, ip=ip)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def logout(
    payload: RefreshRequest,
    auth: AuthService = Depends(get_auth_service),
) -> Response:
    # Revokes the presented refresh session; idempotent. 204 = no content.
    await auth.logout(payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
async def me(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    grants = await db.execute(
        select(UserWarehouseAccess.warehouse_id).where(UserWarehouseAccess.user_id == user.id)
    )
    return MeResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        roles=user.roles,
        permissions=sorted(user.permissions),
        accessible_warehouse_ids=[wid for (wid,) in grants.all()],
    )
