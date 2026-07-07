"""Bike-issues endpoints (mounted at /api/v1/bike-issues).

Open an internal repair on a bike we own, list/add the spare parts used, and resolve it —
which consumes those parts through the single inventory write path and releases the bike.
Permission-gated (bike_issue.read / bike_issue.manage); tenant/branch scoping via RLS +
resolve_branch_scope.
"""
from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import (
    CurrentUser,
    get_bike_issue_service,
    require_permission,
    resolve_branch_scope,
)
from app.bike_issues.schemas import (
    BikeIssueCreate,
    BikeIssueOut,
    BikeIssueResolve,
    BikeIssueStatusIn,
    RepairLineIn,
)
from app.bike_issues.service import BikeIssueService
from app.core.permissions import P
from app.schemas.common import Page

router = APIRouter()


def _page(items, total, page, page_size):
    return {
        "items": items, "page": page, "page_size": page_size, "total": total,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }


@router.post("", response_model=BikeIssueOut, status_code=status.HTTP_201_CREATED)
async def open_issue(
    payload: BikeIssueCreate,
    user: CurrentUser = Depends(require_permission(P.BIKE_ISSUE_MANAGE)),
    svc: BikeIssueService = Depends(get_bike_issue_service),
) -> BikeIssueOut:
    return await svc.open(tenant_id=user.tenant_id, user_id=user.id, payload=payload)


@router.get("", response_model=Page[BikeIssueOut])
async def list_issues(
    status_filter: str | None = Query(default=None, alias="status"),
    branch_id: uuid.UUID | None = Query(default=None),
    unit_id: uuid.UUID | None = Query(default=None),
    model_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_permission(P.BIKE_ISSUE_READ)),
    svc: BikeIssueService = Depends(get_bike_issue_service),
) -> Page[BikeIssueOut]:
    items, total = await svc.list_issues(
        status=status_filter, branch_ids=resolve_branch_scope(user, branch_id),
        unit_id=unit_id, model_id=model_id, search=search, page=page, page_size=page_size,
    )
    return Page[BikeIssueOut](**_page(items, total, page, page_size))


@router.get("/{issue_id}", response_model=BikeIssueOut)
async def get_issue(
    issue_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission(P.BIKE_ISSUE_READ)),
    svc: BikeIssueService = Depends(get_bike_issue_service),
) -> BikeIssueOut:
    return await svc.get(issue_id)


@router.post("/{issue_id}/lines", response_model=BikeIssueOut, status_code=status.HTTP_201_CREATED)
async def add_line(
    issue_id: uuid.UUID,
    payload: RepairLineIn,
    user: CurrentUser = Depends(require_permission(P.BIKE_ISSUE_MANAGE)),
    svc: BikeIssueService = Depends(get_bike_issue_service),
) -> BikeIssueOut:
    return await svc.add_line(tenant_id=user.tenant_id, user_id=user.id, issue_id=issue_id, payload=payload)


@router.delete("/{issue_id}/lines/{line_id}", response_model=BikeIssueOut)
async def remove_line(
    issue_id: uuid.UUID,
    line_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission(P.BIKE_ISSUE_MANAGE)),
    svc: BikeIssueService = Depends(get_bike_issue_service),
) -> BikeIssueOut:
    return await svc.remove_line(tenant_id=user.tenant_id, user_id=user.id, issue_id=issue_id, line_id=line_id)


@router.post("/{issue_id}/status", response_model=BikeIssueOut)
async def set_status(
    issue_id: uuid.UUID,
    payload: BikeIssueStatusIn,
    user: CurrentUser = Depends(require_permission(P.BIKE_ISSUE_MANAGE)),
    svc: BikeIssueService = Depends(get_bike_issue_service),
) -> BikeIssueOut:
    return await svc.set_status(tenant_id=user.tenant_id, user_id=user.id, issue_id=issue_id, new_status=payload.status)


@router.post("/{issue_id}/resolve", response_model=BikeIssueOut)
async def resolve_issue(
    issue_id: uuid.UUID,
    payload: BikeIssueResolve,
    user: CurrentUser = Depends(require_permission(P.BIKE_ISSUE_MANAGE)),
    svc: BikeIssueService = Depends(get_bike_issue_service),
) -> BikeIssueOut:
    return await svc.resolve(tenant_id=user.tenant_id, user_id=user.id, issue_id=issue_id, payload=payload)
