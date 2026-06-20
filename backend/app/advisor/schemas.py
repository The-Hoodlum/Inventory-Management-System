"""API schemas for the AI Supply Chain Analyst (Phase 10)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, Field


class FindingOut(BaseModel):
    category: str
    severity: Decimal            # 0..1 priority
    title: str
    detail: str                  # plain-language explanation from real numbers
    refs: dict                   # structured, auditable references
    recommended_action: str | None = None


class AdvisoryBriefingResponse(BaseModel):
    generated_at: dt.datetime
    summary: str                 # deterministic one-line headline
    llm_enabled: bool            # whether an LLM narrator is configured
    narrative: str | None = None # LLM narrative grounded in the findings (None when inert)
    metrics: dict
    findings: list[FindingOut]


class AdvisoryAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AdvisoryAnswerResponse(BaseModel):
    question: str
    generated_at: dt.datetime
    llm_enabled: bool
    answer: str | None = None            # LLM answer grounded in the findings (None when inert)
    relevant_findings: list[FindingOut]  # deterministic, question-relevant evidence
    metrics: dict
