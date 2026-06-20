"""Inventory operation schemas (receive / issue / adjust / transfer) and reads."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

PosDecimal = Annotated[Decimal, Field(gt=0)]
NonNegDecimal = Annotated[Decimal, Field(ge=0)]


# --------------------------- requests --------------------------- #
class ReceiptLine(BaseModel):
    product_id: uuid.UUID
    quantity: PosDecimal
    unit_cost: NonNegDecimal | None = None


class ReceiveStockRequest(BaseModel):
    warehouse_id: uuid.UUID
    lines: list[ReceiptLine] = Field(min_length=1)
    reference_type: str | None = None  # e.g. 'purchase_order', 'manual'
    reference_id: uuid.UUID | None = None


class IssueLine(BaseModel):
    product_id: uuid.UUID
    quantity: PosDecimal


class IssueStockRequest(BaseModel):
    warehouse_id: uuid.UUID
    lines: list[IssueLine] = Field(min_length=1)
    reference_type: str | None = None  # e.g. 'sales_order', 'manual'
    reference_id: uuid.UUID | None = None
    reason: str | None = None


class AdjustStockRequest(BaseModel):
    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    # Signed delta applied to qty_on_hand (positive = increase, negative = decrease).
    delta: Decimal = Field(description="Signed change to on-hand quantity; must be non-zero.")
    reason: str = Field(min_length=1, description="Reason is mandatory for adjustments.")

    @model_validator(mode="after")
    def _non_zero(self) -> "AdjustStockRequest":
        if self.delta == 0:
            raise ValueError("delta must be non-zero")
        return self


class TransferStockRequest(BaseModel):
    product_id: uuid.UUID
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    quantity: PosDecimal
    reason: str | None = None

    @model_validator(mode="after")
    def _distinct(self) -> "TransferStockRequest":
        if self.from_warehouse_id == self.to_warehouse_id:
            raise ValueError("from_warehouse_id and to_warehouse_id must differ")
        return self


# --------------------------- responses --------------------------- #
class InventoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID | None = None
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    qty_on_hand: Decimal
    qty_reserved: Decimal
    qty_damaged: Decimal
    qty_available: Decimal
    version: int


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    movement_type: str
    quantity: Decimal
    reference_type: str | None
    reference_id: uuid.UUID | None
    from_warehouse_id: uuid.UUID | None
    to_warehouse_id: uuid.UUID | None
    unit_cost: Decimal | None
    reason: str | None
    user_id: uuid.UUID | None
    created_at: dt.datetime
