"""API schemas for container load optimization (Phase 9)."""
from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


# --------------------------------- requests --------------------------------- #
class PlanLineInput(BaseModel):
    """One line to ship. Give ``cartons`` directly, or ``units`` (converted to whole
    cartons via the product's units-per-carton). Exactly one of the two is required."""

    product_id: uuid.UUID
    cartons: int | None = Field(default=None, ge=1)
    units: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _exactly_one_quantity(self) -> "PlanLineInput":
        if (self.cartons is None) == (self.units is None):
            raise ValueError("provide exactly one of 'cartons' or 'units'")
        return self


class ContainerPlanRequest(BaseModel):
    lines: list[PlanLineInput] = Field(min_length=1)
    container_code: str | None = Field(
        default=None, description="Container code (e.g. 20GP/40GP/40HC); recommends the best if omitted"
    )
    usable_fraction: Decimal = Field(
        default=Decimal("0.90"), gt=0, le=1, description="Realistic usable fraction of internal volume"
    )


class RecommendationPlanRequest(BaseModel):
    """Plan a shipment straight from reorder recommendations (closes the loop from
    forecast-driven reordering to container loading)."""

    recommendation_ids: list[uuid.UUID] = Field(min_length=1)
    container_code: str | None = Field(default=None)
    usable_fraction: Decimal = Field(default=Decimal("0.90"), gt=0, le=1)


# --------------------------------- responses -------------------------------- #
class ContainerOption(BaseModel):
    code: str
    label: str
    internal_volume_m3: Decimal
    max_payload_kg: Decimal


class PlanLineOut(BaseModel):
    product_id: uuid.UUID
    sku: str
    cartons: int
    volume_m3: Decimal
    weight_kg: Decimal


class TopOffSuggestion(BaseModel):
    """Extra cartons that fit the already-provisioned containers at no extra box."""

    product_id: uuid.UUID
    sku: str
    additional_cartons: int
    additional_units: int
    moq_shortfall: int = 0          # units still short of the product's MOQ, if any
    note: str


class ContainerPlanResponse(BaseModel):
    container_code: str
    container_label: str
    containers_needed: int
    total_cartons: int
    total_volume_m3: Decimal
    total_weight_kg: Decimal
    volume_utilization: Decimal     # 0..1
    weight_utilization: Decimal     # 0..1
    binding_constraint: str         # volume | weight | none
    spare_volume_m3: Decimal
    spare_weight_kg: Decimal
    lines: list[PlanLineOut]
    top_off: TopOffSuggestion | None = None
    drivers: list[str]
    skipped_product_ids: list[uuid.UUID] = []   # missing/zero carton dimensions
