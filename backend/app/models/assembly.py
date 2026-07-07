"""Assembly-planner model: per model/colour tuning for how many assembled units to keep
and how thin is "thin". See ``sql/assembly_targets.sql``.

The planner itself computes deterministically from CURRENT unit counts and stores nothing;
this table only holds the (optional) tenant overrides. No demand/velocity data lives here.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)


class AssemblyTarget(Base):
    __tablename__ = "assembly_targets"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    model_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("motorcycle_models.id", ondelete="CASCADE"), nullable=False)
    # NULL colour = a model-wide default across all colours.
    colour_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("motorcycle_colours.id", ondelete="CASCADE"), nullable=True)
    target_assembled: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
