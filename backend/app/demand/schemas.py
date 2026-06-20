"""API schemas for the demand pipeline."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field, model_validator


class RebuildDemandRequest(BaseModel):
    """Trigger a daily-demand rollup from outbound stock movements.

    With no dates, rebuilds the last ``window_days`` ending today. Provide an
    explicit ``start_date``/``end_date`` to backfill or recompute a range.
    """

    start_date: dt.date | None = None
    end_date: dt.date | None = None
    window_days: int = Field(default=90, ge=1, le=1830, description="Used only when dates are omitted")
    warehouse_id: uuid.UUID | None = Field(default=None, description="Limit the rollup to one warehouse")

    @model_validator(mode="after")
    def _check_range(self) -> RebuildDemandRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class RebuildDemandResponse(BaseModel):
    start_date: dt.date
    end_date: dt.date
    rows_written: int
    warehouse_id: uuid.UUID | None = None
