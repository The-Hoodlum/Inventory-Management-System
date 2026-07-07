"""Pydantic schemas for the Assembly Planner."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


# ------------------------------- targets ----------------------------------- #
class AssemblyTargetIn(BaseModel):
    """Tune, per model (optionally per colour), how many assembled units to keep and how
    thin is 'thin'. Colour omitted = a model-wide default across all colours."""

    model_id: uuid.UUID
    colour_id: uuid.UUID | None = None
    target_assembled: int = Field(ge=1, description="How many assembled units to keep on hand.")
    threshold: int = Field(ge=0, description="Flag the combo as thin when assembled <= this.")


class AssemblyTargetOut(BaseModel):
    id: uuid.UUID
    model_id: uuid.UUID
    model_name: str | None = None
    colour_id: uuid.UUID | None = None
    colour_name: str | None = None
    target_assembled: int
    threshold: int


# ------------------------------- plan -------------------------------------- #
class AssemblyLineOut(BaseModel):
    """One model/colour(/variant) combo in the plan — a recommendation or a gap."""

    model_id: uuid.UUID
    model_name: str | None = None
    variant_id: uuid.UUID | None = None
    variant_name: str | None = None
    colour_id: uuid.UUID | None = None
    colour_name: str | None = None
    current_assembled: int
    unassembled_available: int
    target_assembled: int
    threshold: int
    recommended_qty: int          # units to assemble now; 0 for gap rows
    reason: str


class AssemblyPlanOut(BaseModel):
    generated_at: dt.datetime
    default_target_assembled: int
    default_threshold: int
    # Thin on assembled stock AND buildable now — assemble up to target.
    recommendations: list[AssemblyLineOut] = []
    # Thin on assembled stock but NO unassembled units to build from (purchase/import signal).
    gaps: list[AssemblyLineOut] = []
