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

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID = PGUUID(as_uuid=True)

# Account types + movement directions (mirrors the CHECK constraints in the SQL).
ACCOUNT_TYPES = ("CASH", "BANK", "MOBILE_MONEY", "CUSTODY")
DIRECTION_IN = "IN"
DIRECTION_OUT = "OUT"


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
