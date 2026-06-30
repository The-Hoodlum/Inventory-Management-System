"""Global-search endpoint (mounted at /api/v1/search).

One endpoint backs the shell's global search box. It searches every registered entity
the user is allowed to see (per-provider permission), tenant-scoped by RLS. Extensible:
a new module registers a provider and it shows up here automatically.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, get_current_user, get_db
from app.search.registry import SearchResponse
from app.search.service import SearchService

router = APIRouter()


@router.get("", response_model=SearchResponse)
async def global_search(
    q: str = Query(default="", description="Search text (min 2 chars)."),
    limit: int = Query(default=5, ge=1, le=20, description="Max hits per entity group."),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    return await SearchService(db).search(
        query=q, permissions=user.permissions, limit_per_entity=limit
    )
