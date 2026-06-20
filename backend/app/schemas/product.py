"""Product schemas."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ProductStatus = Literal["active", "inactive", "discontinued"]

# --- Product Intelligence Profile value domains ---
TransportMode = Literal["sea", "air", "road", "rail", "multimodal"]
Criticality = Literal["low", "medium", "high", "critical"]
SupplierDependency = Literal["single", "dual", "multi"]
DemandType = Literal["smooth", "erratic", "intermittent", "lumpy", "seasonal"]
Substitutability = Literal["none", "low", "medium", "high"]

NonNegDecimal = Annotated[Decimal, Field(ge=0)]


class ProductBase(BaseModel):
    barcode: str | None = None
    name: str = Field(min_length=1, max_length=512)
    description: str | None = None
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    primary_supplier_id: uuid.UUID | None = None
    cost_price: NonNegDecimal = Decimal("0")
    selling_price: NonNegDecimal = Decimal("0")
    units_per_carton: int = Field(default=1, ge=1)
    moq: int = Field(default=0, ge=0)
    lead_time_days: int = Field(default=30, ge=0)
    weight_per_unit: NonNegDecimal | None = None
    volume_per_unit: NonNegDecimal | None = None
    weight_per_carton: NonNegDecimal | None = None
    volume_per_carton: NonNegDecimal | None = None
    cartons_per_pallet: int | None = Field(default=None, gt=0)
    reorder_point: int | None = Field(default=None, ge=0)
    safety_stock: int | None = Field(default=None, ge=0)
    # --- Product Intelligence Profile ---
    commodity_tags: list[str] = Field(default_factory=list)
    country_of_origin: str | None = Field(default=None, max_length=64)
    transport_mode: TransportMode | None = None
    criticality: Criticality = "medium"
    supplier_dependency: SupplierDependency | None = None
    demand_type: DemandType | None = None
    substitutability: Substitutability | None = None
    # Unit of measure, product-level currency (NULL => tenant base), and strategic flags.
    unit_of_measure: str | None = Field(default=None, max_length=32)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    strategic_item: bool = False
    alternate_supplier_available: bool = False
    status: ProductStatus = "active"


class ProductCreate(ProductBase):
    sku: str = Field(min_length=1, max_length=128)
    # Category/Brand by NAME (get-or-created, matching the import flow). Takes
    # precedence over category_id/brand_id when provided.
    category: str | None = Field(default=None, max_length=120)
    brand: str | None = Field(default=None, max_length=120)


class ProductUpdate(BaseModel):
    # All optional; only provided fields are changed.
    sku: str | None = Field(default=None, min_length=1, max_length=128)
    barcode: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = None
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    primary_supplier_id: uuid.UUID | None = None
    cost_price: NonNegDecimal | None = None
    selling_price: NonNegDecimal | None = None
    units_per_carton: int | None = Field(default=None, ge=1)
    moq: int | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0)
    weight_per_unit: NonNegDecimal | None = None
    volume_per_unit: NonNegDecimal | None = None
    weight_per_carton: NonNegDecimal | None = None
    volume_per_carton: NonNegDecimal | None = None
    cartons_per_pallet: int | None = Field(default=None, gt=0)
    reorder_point: int | None = Field(default=None, ge=0)
    safety_stock: int | None = Field(default=None, ge=0)
    commodity_tags: list[str] | None = None
    country_of_origin: str | None = Field(default=None, max_length=64)
    transport_mode: TransportMode | None = None
    criticality: Criticality | None = None
    supplier_dependency: SupplierDependency | None = None
    demand_type: DemandType | None = None
    substitutability: Substitutability | None = None
    unit_of_measure: str | None = Field(default=None, max_length=32)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    strategic_item: bool | None = None
    alternate_supplier_available: bool | None = None
    category: str | None = Field(default=None, max_length=120)
    brand: str | None = Field(default=None, max_length=120)
    status: ProductStatus | None = None


class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    sku: str
    # Resolved reference-data names (populated by the service), for display/edit pre-fill.
    category_name: str | None = None
    brand_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
