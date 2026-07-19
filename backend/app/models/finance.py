"""Finance models — a cash book / treasury ledger (NOT double-entry accounting).

Every account is an append-only ledger: its balance is DERIVED by summing movements
(``opening_balance + sum(IN) - sum(OUT)``), never stored as an editable field and never
set. Movements are immutable; a correction is a reversing movement (``reversal_of``),
never an edit or delete. See ``database/sql/finance_accounts.sql`` and ``app/finance/``.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, LargeBinary, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)

# Account types + movement directions (mirrors the CHECK constraints in the SQL).
ACCOUNT_TYPES = ("CASH", "BANK", "MOBILE_MONEY", "CUSTODY")
DIRECTION_IN = "IN"
DIRECTION_OUT = "OUT"

# Sales payment methods that can be mapped to an account (mirrors sales PaymentLineIn).
PAYMENT_METHODS = ("cash", "card", "mobile_money", "bank_transfer", "cheque", "store_credit")
# The account type each method most naturally posts to (a UI hint only; the actual account
# is whatever the tenant maps — nothing is hard-coded in the posting path).
DEFAULT_METHOD_ACCOUNT_TYPE = {
    "cash": "CASH",
    "mobile_money": "MOBILE_MONEY",
    "bank_transfer": "BANK",
    "card": "BANK",
    "cheque": "BANK",
    "store_credit": "CUSTODY",
}


class FinancialAccount(Base):
    """A finance account (cash in hand, a bank account, a mobile-money wallet, or a
    custody account). Branch-scoped; CUSTODY accounts may be tenant-wide (branch_id NULL).
    The balance is never stored here — it is derived from :class:`AccountMovement`."""

    __tablename__ = "financial_accounts"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ZMW'"))
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    opening_as_of: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class AccountMovement(Base):
    """One immutable, append-only money movement — the ONLY thing that changes a balance.
    ``amount`` is always positive; ``direction`` (IN/OUT) carries the sign. A correction is
    a new opposite-direction movement whose ``reversal_of`` points at the one it cancels."""

    __tablename__ = "account_movements"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("financial_accounts.id", ondelete="RESTRICT"), nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)  # always > 0
    occurred_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    reversal_of: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("account_movements.id", ondelete="RESTRICT"), nullable=True)


class FinancePaymentAccountMap(Base):
    """Per-branch mapping of a sales payment method to the finance account it posts to.
    Tenant CONFIGURATION (editable/removable), not a financial record. Once a branch has
    any mapping, an unmapped method on a payment fails loudly rather than dropping money."""

    __tablename__ = "finance_payment_account_map"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("financial_accounts.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class ExpenseCategory(Base):
    """A configurable tenant expense category (fuel, rent, salaries, …). Deactivated,
    never deleted (it's referenced by expense records)."""

    __tablename__ = "expense_categories"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Expense(Base):
    """Money out. Recording one posts an OUT movement to ``account_id`` (append-only
    ledger), so the balance drops by exactly ``amount``. Manager-recorded, no approval.
    A correction is a VOID (reversing IN) + a fresh record — never an amount edit or a
    delete."""

    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True)
    account_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("financial_accounts.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)  # > 0
    expense_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("expense_categories.id", ondelete="RESTRICT"), nullable=True)
    payee: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'recorded'"))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    voided_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    voided_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class ExpenseAttachment(Base):
    """Optional receipt (image/PDF) for an expense — bytes stored in-DB (like ImportFile).
    One per expense; replaceable, not deletable."""

    __tablename__ = "expense_attachments"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    expense_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class AccountTransfer(Base):
    """Money moved between two accounts — one record backing a PAIRED OUT + IN posted in a
    single transaction. Reversible only by a reversing pair."""

    __tablename__ = "account_transfers"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    from_account_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("financial_accounts.id", ondelete="RESTRICT"), nullable=False)
    to_account_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("financial_accounts.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    reference_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'completed'"))
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reversed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    reverse_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class CashHandover(Base):
    """Branch cash handed to a named person / custody account. The OUT posts on record (the
    branch no longer holds it — money in transit); the IN posts on confirm. A short
    confirmation records a discrepancy + mandatory reason and posts the IN for what was
    actually received. Corrections are reversing entries only."""

    __tablename__ = "cash_handovers"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True)
    from_account_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("financial_accounts.id", ondelete="RESTRICT"), nullable=False)
    to_account_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("financial_accounts.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    handover_datetime: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    handed_over_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    handed_over_by_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_by_name: Mapped[str] = mapped_column(Text, nullable=False)
    received_by_user_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reference_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    denomination_breakdown: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'PENDING_CONFIRMATION'"))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    confirmed_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    discrepancy_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    discrepancy_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reversed_at: Mapped[dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    reverse_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class CashHandoverAttachment(Base):
    """Optional signed-slip photo for a handover — bytes in-DB. One per handover; replaceable."""

    __tablename__ = "cash_handover_attachments"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    handover_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("cash_handovers.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
