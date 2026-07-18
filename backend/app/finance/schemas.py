"""Finance schemas (PR 1: accounts + derived balances + ledger movements).

A balance is DERIVED, never set: no schema here lets a caller write a balance. The
account's ``opening_balance`` is a create-only field (part of the derivation) and is not
present on :class:`AccountUpdate`.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AccountType = Literal["CASH", "BANK", "MOBILE_MONEY", "CUSTODY"]
Direction = Literal["IN", "OUT"]


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    type: AccountType
    # Required for CASH / BANK / MOBILE_MONEY (enforced in the service); optional for a
    # tenant-wide CUSTODY account.
    branch_id: uuid.UUID | None = None
    currency: str = Field(default="ZMW", min_length=1, max_length=8)
    opening_balance: Decimal = Field(default=Decimal("0"))
    opening_as_of: dt.date | None = None


class AccountUpdate(BaseModel):
    # Deliberately NOT editable: type, branch, currency, opening_balance — changing any of
    # those would change a derived balance or break ledger coherence. Only naming and the
    # active flag can be edited.
    name: str | None = Field(default=None, min_length=1, max_length=256)
    is_active: bool | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    branch_id: uuid.UUID | None
    branch_name: str | None = None
    name: str
    type: AccountType
    currency: str
    opening_balance: Decimal
    opening_as_of: dt.date | None
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class AccountBalanceOut(AccountOut):
    """An account plus its DERIVED position: balance == opening_balance + total_in - total_out."""

    total_in: Decimal
    total_out: Decimal
    balance: Decimal


PaymentMethod = Literal["cash", "card", "mobile_money", "bank_transfer", "cheque", "store_credit"]


class PaymentMappingSet(BaseModel):
    branch_id: uuid.UUID
    method: PaymentMethod
    account_id: uuid.UUID


class PaymentMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    branch_id: uuid.UUID
    branch_name: str | None = None
    method: PaymentMethod
    account_id: uuid.UUID
    account_name: str | None = None


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    direction: Direction
    amount: Decimal
    occurred_at: dt.datetime
    category: str | None
    reference_type: str | None
    reference_id: uuid.UUID | None
    description: str | None
    created_by: uuid.UUID | None
    created_at: dt.datetime
    reversal_of: uuid.UUID | None


# ------------------------------ expenses --------------------------------- #
class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_active: bool


class ExpenseCreate(BaseModel):
    account_id: uuid.UUID
    branch_id: uuid.UUID | None = None  # defaults to the account's branch
    amount: Decimal = Field(gt=0)
    expense_date: dt.date
    category_id: uuid.UUID | None = None
    payee: str | None = Field(default=None, max_length=256)
    description: str | None = None
    reference_no: str | None = Field(default=None, max_length=128)


class ExpenseUpdate(BaseModel):
    # Metadata only. Amount and account are NOT editable — changing what an expense cost
    # means voiding it (reversing the OUT) and recording a fresh one.
    category_id: uuid.UUID | None = None
    payee: str | None = Field(default=None, max_length=256)
    description: str | None = None
    reference_no: str | None = Field(default=None, max_length=128)
    expense_date: dt.date | None = None


class ExpenseVoid(BaseModel):
    reason: str = Field(min_length=1, max_length=512)


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    branch_id: uuid.UUID | None
    branch_name: str | None = None
    account_id: uuid.UUID
    account_name: str | None = None
    amount: Decimal
    expense_date: dt.date
    category_id: uuid.UUID | None
    category_name: str | None = None
    payee: str | None
    description: str | None
    reference_no: str | None
    status: str
    recorded_by: uuid.UUID | None
    void_reason: str | None
    voided_by: uuid.UUID | None
    voided_at: dt.datetime | None
    has_attachment: bool = False
    created_at: dt.datetime
