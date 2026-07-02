"""Pydantic request/response models for the import API."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field


class FieldOut(BaseModel):
    name: str
    label: str
    required: bool
    kind: str
    choices: list[str] = []
    aliases: list[str] = []


class TargetOut(BaseModel):
    key: str
    label: str
    fields: list[FieldOut]
    template_levels: list[str] = ["basic", "standard", "advanced"]


class ImportOptions(BaseModel):
    """How to handle reference data while importing."""

    warehouse_mode: Literal["create", "skip"] = "create"
    default_warehouse: str = Field(default="MAIN", max_length=120)
    supplier_mode: Literal["create", "link_only"] = "create"
    # Atomic targets (e.g. motorcycle units): authorize creating the NEW reference
    # values the preview surfaced. Left False, an unmatched reference blocks its rows
    # (guards typos — nothing is created silently).
    create_missing_references: bool = False


class NewReferenceOut(BaseModel):
    """A reference value in the file that does not yet exist and would be created on
    confirm (surfaced by an atomic target's preview so the user can confirm/fix)."""

    kind: str  # model | variant | colour | supplier
    value: str
    count: int = 1


class UploadResponse(BaseModel):
    job_id: uuid.UUID
    target_key: str
    filename: str
    status: str
    total_rows: int
    headers: list[str]
    detected_mapping: dict[str, int | None]
    mapping_source: str = "detected"  # "detected" | "saved" (a remembered mapping was applied)
    sample_rows: list[list[str]]  # first N data rows, as strings


class RowErrorOut(BaseModel):
    row_number: int
    sku: str | None = None
    errors: list[str]


class PreviewRequest(BaseModel):
    mapping: dict[str, int | None]
    options: ImportOptions = ImportOptions()


class PreviewResponse(BaseModel):
    total_rows: int
    valid_count: int
    invalid_count: int
    missing_required: list[str] = []
    sample_errors: list[RowErrorOut] = []
    sample_rows: list[list[str]] = []
    headers: list[str] = []
    # Atomic targets: NEW reference values awaiting confirmation, and whether the batch
    # is committable (all rows valid). ``atomic`` marks the confirm-then-commit flow.
    atomic: bool = False
    new_references: list[NewReferenceOut] = []
    can_commit: bool = True


class ConfirmRequest(BaseModel):
    mapping: dict[str, int | None]
    options: ImportOptions = ImportOptions()


class ImportJobOut(BaseModel):
    id: uuid.UUID
    target_key: str
    filename: str
    status: str
    total_rows: int
    processed_rows: int
    imported_rows: int
    skipped_rows: int
    error_count: int
    created_by: uuid.UUID | None = None
    created_at: dt.datetime
    started_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None

    model_config = {"from_attributes": True}


class ImportJobListResponse(BaseModel):
    items: list[ImportJobOut]
    total: int
    page: int
    page_size: int
