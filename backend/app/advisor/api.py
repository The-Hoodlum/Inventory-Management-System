"""AI Supply Chain Analyst endpoints.

Mounted at /api/v1/advisor. The briefing reads across reorder, intelligence, and
forecast data, so it requires ``reorder.read``. It is always available and
deterministic; an LLM narrative is added only when one is configured.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.advisor.schemas import (
    AdvisoryAnswerResponse,
    AdvisoryAskRequest,
    AdvisoryBriefingResponse,
)
from app.advisor.service import AdvisorService
from app.api.v1.deps import CurrentUser, get_advisor_service, require_permission
from app.core.permissions import P

router = APIRouter()


@router.get("/briefing", response_model=AdvisoryBriefingResponse)
async def briefing(
    question: str | None = Query(default=None, description="Optional question for the LLM narrator"),
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: AdvisorService = Depends(get_advisor_service),
) -> AdvisoryBriefingResponse:
    return await svc.briefing(question=question)


@router.post("/ask", response_model=AdvisoryAnswerResponse)
async def ask(
    payload: AdvisoryAskRequest,
    _: CurrentUser = Depends(require_permission(P.REORDER_READ)),
    svc: AdvisorService = Depends(get_advisor_service),
) -> AdvisoryAnswerResponse:
    return await svc.ask(question=payload.question)
