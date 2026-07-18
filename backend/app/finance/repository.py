"""Finance repository: accounts CRUD + the append-only movement ledger.

Tenant isolation is enforced by RLS (the request sets ``app.current_tenant``); queries
here do not filter by ``tenant_id`` but INSERTs must set it. Branch scoping is applied
explicitly (a scoped user only sees their branches' accounts plus tenant-wide custody).
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, select

from app.models import AccountMovement, Branch, FinancialAccount


class FinanceRepository:
    def __init__(self, session) -> None:
        self.session = session

    # ------------------------------ accounts ------------------------------ #
    async def add_account(self, account: FinancialAccount) -> FinancialAccount:
        self.session.add(account)
        await self.session.flush()  # populate id + server defaults
        return account

    async def get_account(self, account_id: uuid.UUID) -> FinancialAccount | None:
        return await self.session.get(FinancialAccount, account_id)

    async def get_account_for_update(self, account_id: uuid.UUID) -> FinancialAccount | None:
        """Lock the account row for the duration of a posting — the same SELECT FOR UPDATE
        discipline the stock ledger uses, so concurrent postings serialize cleanly."""
        res = await self.session.execute(
            select(FinancialAccount).where(FinancialAccount.id == account_id).with_for_update()
        )
        return res.scalar_one_or_none()

    async def list_accounts(
        self, *, branch_ids: Sequence[uuid.UUID] | None, active_only: bool = False,
        type: str | None = None,
    ) -> list[FinancialAccount]:
        stmt = select(FinancialAccount)
        if branch_ids is not None:
            # Scoped user: their branches' accounts + tenant-wide custody (branch_id NULL),
            # which is a valid handover destination for any branch.
            stmt = stmt.where(
                FinancialAccount.branch_id.in_(list(branch_ids))
                | FinancialAccount.branch_id.is_(None)
            )
        if active_only:
            stmt = stmt.where(FinancialAccount.is_active.is_(True))
        if type is not None:
            stmt = stmt.where(FinancialAccount.type == type)
        stmt = stmt.order_by(FinancialAccount.type, FinancialAccount.name)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def branch_name_map(self) -> dict[uuid.UUID, str]:
        res = await self.session.execute(select(Branch.id, Branch.name))
        return {bid: name for bid, name in res.all()}

    # ------------------------------ movements ----------------------------- #
    async def add_movement(
        self, *, tenant_id: uuid.UUID, account_id: uuid.UUID, direction: str, amount: Decimal,
        occurred_at: dt.datetime | None = None, category: str | None = None,
        reference_type: str | None = None, reference_id: uuid.UUID | None = None,
        description: str | None = None, created_by: uuid.UUID | None = None,
        reversal_of: uuid.UUID | None = None,
    ) -> AccountMovement:
        movement = AccountMovement(
            tenant_id=tenant_id, account_id=account_id, direction=direction, amount=amount,
            occurred_at=occurred_at, category=category, reference_type=reference_type,
            reference_id=reference_id, description=description, created_by=created_by,
            reversal_of=reversal_of,
        )
        self.session.add(movement)
        await self.session.flush()
        return movement

    async def movement_sums(self, account_id: uuid.UUID) -> tuple[Decimal, Decimal]:
        """(total_in, total_out) across an account's whole ledger."""
        res = await self.session.execute(
            select(
                AccountMovement.direction,
                func.coalesce(func.sum(AccountMovement.amount), 0),
            )
            .where(AccountMovement.account_id == account_id)
            .group_by(AccountMovement.direction)
        )
        totals = {direction: Decimal(str(total)) for direction, total in res.all()}
        return totals.get("IN", Decimal("0")), totals.get("OUT", Decimal("0"))

    async def sums_by_account(
        self, account_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
        """Batched (total_in, total_out) per account for the accounts list — one query."""
        if not account_ids:
            return {}
        res = await self.session.execute(
            select(
                AccountMovement.account_id,
                AccountMovement.direction,
                func.coalesce(func.sum(AccountMovement.amount), 0),
            )
            .where(AccountMovement.account_id.in_(list(account_ids)))
            .group_by(AccountMovement.account_id, AccountMovement.direction)
        )
        out: dict[uuid.UUID, tuple[Decimal, Decimal]] = {
            aid: (Decimal("0"), Decimal("0")) for aid in account_ids
        }
        for account_id, direction, total in res.all():
            cur_in, cur_out = out[account_id]
            if direction == "IN":
                out[account_id] = (Decimal(str(total)), cur_out)
            else:
                out[account_id] = (cur_in, Decimal(str(total)))
        return out

    async def list_movements(
        self, *, account_id: uuid.UUID, date_from: dt.datetime | None = None,
        date_to: dt.datetime | None = None,
    ) -> list[AccountMovement]:
        """An account's movements in time order (for statements). Time order is
        (occurred_at, created_at) so a running balance is well-defined."""
        stmt = select(AccountMovement).where(AccountMovement.account_id == account_id)
        if date_from is not None:
            stmt = stmt.where(AccountMovement.occurred_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(AccountMovement.occurred_at <= date_to)
        stmt = stmt.order_by(AccountMovement.occurred_at, AccountMovement.created_at)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_movement(self, movement_id: uuid.UUID) -> AccountMovement | None:
        return await self.session.get(AccountMovement, movement_id)
