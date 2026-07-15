"""Schemas for branch -> customer/reseller delivery (sale | consignment)."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field, model_validator

from app.customer_delivery.domain import status as S


class DeliverPartLineIn(BaseModel):
    product_id: uuid.UUID
    qty: float = Field(gt=0)


class DeliverBikeLineIn(BaseModel):
    unit_id: uuid.UUID


class CustomerDeliveryCreate(BaseModel):
    delivery_mode: str = Field(pattern=f"^({S.SALE}|{S.CONSIGNMENT})$")
    from_warehouse_id: uuid.UUID
    customer_id: uuid.UUID | None = None   # required for consignment; derived for sale
    invoice_id: uuid.UUID | None = None    # required for sale
    remarks: str | None = Field(default=None, max_length=2000)
    part_lines: list[DeliverPartLineIn] = []   # consignment only
    bike_lines: list[DeliverBikeLineIn] = []   # consignment only

    @model_validator(mode="after")
    def _mode_rules(self) -> CustomerDeliveryCreate:
        if self.delivery_mode == S.SALE:
            if self.invoice_id is None:
                raise ValueError("A sale delivery must reference an invoice_id.")
        else:  # consignment
            if self.customer_id is None:
                raise ValueError("A consignment delivery needs a customer_id.")
            if not self.part_lines and not self.bike_lines:
                raise ValueError("A consignment delivery needs at least one line.")
        return self


class DeliverBody(BaseModel):
    received_by: str | None = Field(default=None, max_length=256)
    # A SALE handover of a bike SOLD before assembly is blocked (it isn't built yet) unless a
    # manager (sales.manage) explicitly overrides. Consignment is exempt — the reseller
    # assembles it. See CustomerDeliveryService.deliver.
    override_unassembled: bool = False


class SettlePartLineIn(BaseModel):
    line_id: uuid.UUID
    settled_qty: float = Field(default=0, ge=0)   # sold -> deducted
    returned_qty: float = Field(default=0, ge=0)  # unsold -> released


class SettleBikeLineIn(BaseModel):
    line_id: uuid.UUID
    outcome: str = Field(pattern="^(sold|returned)$")
    invoice_id: uuid.UUID | None = None  # required when sold


class CustomerDeliverySettle(BaseModel):
    remarks: str | None = Field(default=None, max_length=2000)
    part_lines: list[SettlePartLineIn] = []
    bike_lines: list[SettleBikeLineIn] = []


class CancelBody(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class CustomerDeliveryLineOut(BaseModel):
    id: uuid.UUID
    line_kind: str
    product_id: uuid.UUID | None = None
    sku: str | None = None
    name: str | None = None
    unit_id: uuid.UUID | None = None
    chassis_number: str | None = None
    engine_number: str | None = None
    model_name: str | None = None
    assembly_pending: bool = False   # bike sold before assembly, assembly still owed
    qty: float
    settled_qty: float
    returned_qty: float
    sold_invoice_id: uuid.UUID | None = None
    remarks: str | None = None


class CustomerDeliveryOut(BaseModel):
    id: uuid.UUID
    delivery_number: str
    delivery_mode: str
    status: str
    branch_id: uuid.UUID | None = None
    branch_name: str | None = None
    from_warehouse_id: uuid.UUID
    from_warehouse_name: str | None = None
    customer_id: uuid.UUID
    customer_name: str | None = None
    invoice_id: uuid.UUID | None = None
    invoice_number: str | None = None
    remarks: str | None = None
    dispatched_at: dt.datetime | None = None
    received_by: str | None = None
    received_at: dt.datetime | None = None
    created_at: dt.datetime
    lines: list[CustomerDeliveryLineOut] = []
