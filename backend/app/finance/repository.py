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

from app.models import (
    AccountMovement,
    AccountTransfer,
    Branch,
    CashHandover,
    CashHandoverAttachment,
    Expense,
    ExpenseAttachment,
    ExpenseCategory,
    FinancePaymentAccountMap,
    FinancialAccount,
)


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
        # Always stamp a business moment (tz-aware UTC) so time-based reads (statement, day
        # book) are well-defined; defaults to now when the caller has no specific date.
        occ = occurred_at if occurred_at is not None else dt.datetime.now(dt.UTC)
        if occ.tzinfo is None:
            occ = occ.replace(tzinfo=dt.UTC)
        movement = AccountMovement(
            tenant_id=tenant_id, account_id=account_id, direction=direction, amount=amount,
            occurred_at=occ, category=category, reference_type=reference_type,
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

    # ------------------------- period aggregations ----------------------- #
    async def period_category_sums(
        self, account_ids: Sequence[uuid.UUID], start_dt: dt.datetime, end_dt: dt.datetime,
    ) -> dict[tuple[str | None, str], Decimal]:
        """{(category, direction): amount} for the accounts within [start, end]."""
        if not account_ids:
            return {}
        res = await self.session.execute(
            select(AccountMovement.category, AccountMovement.direction,
                   func.coalesce(func.sum(AccountMovement.amount), 0))
            .where(AccountMovement.account_id.in_(list(account_ids)),
                   AccountMovement.occurred_at >= start_dt,
                   AccountMovement.occurred_at <= end_dt)
            .group_by(AccountMovement.category, AccountMovement.direction)
        )
        return {(cat, direction): Decimal(str(total)) for cat, direction, total in res.all()}

    async def signed_sum_before(
        self, account_ids: Sequence[uuid.UUID], before_dt: dt.datetime,
    ) -> tuple[Decimal, Decimal]:
        """(sum_in, sum_out) for the accounts before ``before_dt`` — used for an opening balance."""
        if not account_ids:
            return Decimal("0"), Decimal("0")
        res = await self.session.execute(
            select(AccountMovement.direction, func.coalesce(func.sum(AccountMovement.amount), 0))
            .where(AccountMovement.account_id.in_(list(account_ids)),
                   AccountMovement.occurred_at < before_dt)
            .group_by(AccountMovement.direction)
        )
        totals = {d: Decimal(str(t)) for d, t in res.all()}
        return totals.get("IN", Decimal("0")), totals.get("OUT", Decimal("0"))

    async def money_in_by_account(
        self, account_ids: Sequence[uuid.UUID], start_dt: dt.datetime, end_dt: dt.datetime,
    ) -> dict[uuid.UUID, Decimal]:
        """Operational money IN (sale payments) per account within the period."""
        if not account_ids:
            return {}
        res = await self.session.execute(
            select(AccountMovement.account_id, func.coalesce(func.sum(AccountMovement.amount), 0))
            .where(AccountMovement.account_id.in_(list(account_ids)),
                   AccountMovement.direction == "IN",
                   AccountMovement.category == "sale_payment",
                   AccountMovement.occurred_at >= start_dt,
                   AccountMovement.occurred_at <= end_dt)
            .group_by(AccountMovement.account_id)
        )
        return {aid: Decimal(str(total)) for aid, total in res.all()}

    async def statement_movements(
        self, account_id: uuid.UUID, start_dt: dt.datetime, end_dt: dt.datetime,
    ) -> list[AccountMovement]:
        """An account's movements in the window, in strict time order (for a running balance)."""
        res = await self.session.execute(
            select(AccountMovement)
            .where(AccountMovement.account_id == account_id,
                   AccountMovement.occurred_at >= start_dt,
                   AccountMovement.occurred_at <= end_dt)
            .order_by(AccountMovement.occurred_at, AccountMovement.created_at)
        )
        return list(res.scalars().all())

    async def unreversed_for_reference(
        self, reference_type: str, reference_id: uuid.UUID
    ) -> list[AccountMovement]:
        """Movements for a source document that have NOT yet been cancelled by a reversal —
        so a void reverses each original exactly once (and never a reversal itself)."""
        rows = (await self.session.execute(
            select(AccountMovement).where(
                AccountMovement.reference_type == reference_type,
                AccountMovement.reference_id == reference_id,
                AccountMovement.reversal_of.is_(None),
            )
        )).scalars().all()
        reversed_ids = set(
            (await self.session.execute(
                select(AccountMovement.reversal_of).where(AccountMovement.reversal_of.isnot(None))
            )).scalars().all()
        )
        return [m for m in rows if m.id not in reversed_ids]

    # --------------------------- payment mapping -------------------------- #
    async def mapping_for(
        self, branch_id: uuid.UUID, method: str
    ) -> FinancePaymentAccountMap | None:
        res = await self.session.execute(
            select(FinancePaymentAccountMap).where(
                FinancePaymentAccountMap.branch_id == branch_id,
                FinancePaymentAccountMap.method == method,
            )
        )
        return res.scalar_one_or_none()

    async def branch_has_mappings(self, branch_id: uuid.UUID) -> bool:
        res = await self.session.execute(
            select(FinancePaymentAccountMap.id)
            .where(FinancePaymentAccountMap.branch_id == branch_id)
            .limit(1)
        )
        return res.first() is not None

    async def list_mappings(
        self, branch_ids: Sequence[uuid.UUID] | None
    ) -> list[FinancePaymentAccountMap]:
        stmt = select(FinancePaymentAccountMap)
        if branch_ids is not None:
            stmt = stmt.where(FinancePaymentAccountMap.branch_id.in_(list(branch_ids)))
        stmt = stmt.order_by(FinancePaymentAccountMap.branch_id, FinancePaymentAccountMap.method)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def upsert_mapping(
        self, *, tenant_id: uuid.UUID, branch_id: uuid.UUID, method: str, account_id: uuid.UUID
    ) -> FinancePaymentAccountMap:
        existing = await self.mapping_for(branch_id, method)
        if existing is not None:
            existing.account_id = account_id
            await self.session.flush()
            return existing
        row = FinancePaymentAccountMap(
            tenant_id=tenant_id, branch_id=branch_id, method=method, account_id=account_id
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_mapping(self, mapping_id: uuid.UUID) -> FinancePaymentAccountMap | None:
        return await self.session.get(FinancePaymentAccountMap, mapping_id)

    async def delete_mapping(self, row: FinancePaymentAccountMap) -> None:
        await self.session.delete(row)
        await self.session.flush()

    # ------------------------- expense categories ------------------------ #
    async def add_category(self, category: ExpenseCategory) -> ExpenseCategory:
        self.session.add(category)
        await self.session.flush()
        return category

    async def get_category(self, category_id: uuid.UUID) -> ExpenseCategory | None:
        return await self.session.get(ExpenseCategory, category_id)

    async def category_by_name(self, name: str) -> ExpenseCategory | None:
        res = await self.session.execute(
            select(ExpenseCategory).where(func.lower(ExpenseCategory.name) == name.lower())
        )
        return res.scalar_one_or_none()

    async def list_categories(self, *, active_only: bool = False) -> list[ExpenseCategory]:
        stmt = select(ExpenseCategory)
        if active_only:
            stmt = stmt.where(ExpenseCategory.is_active.is_(True))
        stmt = stmt.order_by(ExpenseCategory.name)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def category_name_map(self) -> dict[uuid.UUID, str]:
        res = await self.session.execute(select(ExpenseCategory.id, ExpenseCategory.name))
        return {cid: name for cid, name in res.all()}

    # ------------------------------ expenses ----------------------------- #
    async def add_expense(self, expense: Expense) -> Expense:
        self.session.add(expense)
        await self.session.flush()
        return expense

    async def get_expense(self, expense_id: uuid.UUID) -> Expense | None:
        return await self.session.get(Expense, expense_id)

    async def list_expenses(
        self, *, branch_ids: Sequence[uuid.UUID] | None, category_id: uuid.UUID | None = None,
        account_id: uuid.UUID | None = None, status: str | None = None,
        date_from: dt.date | None = None, date_to: dt.date | None = None,
    ) -> list[Expense]:
        stmt = select(Expense)
        if branch_ids is not None:
            stmt = stmt.where(Expense.branch_id.in_(list(branch_ids)))
        if category_id is not None:
            stmt = stmt.where(Expense.category_id == category_id)
        if account_id is not None:
            stmt = stmt.where(Expense.account_id == account_id)
        if status is not None:
            stmt = stmt.where(Expense.status == status)
        if date_from is not None:
            stmt = stmt.where(Expense.expense_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Expense.expense_date <= date_to)
        stmt = stmt.order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    # ---------------------------- attachments ---------------------------- #
    async def get_attachment(self, expense_id: uuid.UUID) -> ExpenseAttachment | None:
        res = await self.session.execute(
            select(ExpenseAttachment).where(ExpenseAttachment.expense_id == expense_id)
        )
        return res.scalar_one_or_none()

    async def upsert_attachment(
        self, *, tenant_id: uuid.UUID, expense_id: uuid.UUID, filename: str,
        content_type: str | None, data: bytes, uploaded_by: uuid.UUID | None,
    ) -> ExpenseAttachment:
        existing = await self.get_attachment(expense_id)
        if existing is not None:
            existing.filename = filename
            existing.content_type = content_type
            existing.data = data
            existing.uploaded_by = uploaded_by
            await self.session.flush()
            return existing
        row = ExpenseAttachment(
            tenant_id=tenant_id, expense_id=expense_id, filename=filename,
            content_type=content_type, data=data, uploaded_by=uploaded_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def attachment_expense_ids(self, expense_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
        if not expense_ids:
            return set()
        res = await self.session.execute(
            select(ExpenseAttachment.expense_id).where(ExpenseAttachment.expense_id.in_(list(expense_ids)))
        )
        return set(res.scalars().all())

    # ------------------------------ transfers ---------------------------- #
    async def add_transfer(self, transfer: AccountTransfer) -> AccountTransfer:
        self.session.add(transfer)
        await self.session.flush()
        return transfer

    async def get_transfer(self, transfer_id: uuid.UUID) -> AccountTransfer | None:
        return await self.session.get(AccountTransfer, transfer_id)

    async def list_transfers(
        self, *, account_ids: Sequence[uuid.UUID] | None
    ) -> list[AccountTransfer]:
        stmt = select(AccountTransfer)
        if account_ids is not None:
            ids = list(account_ids)
            stmt = stmt.where(
                AccountTransfer.from_account_id.in_(ids) | AccountTransfer.to_account_id.in_(ids)
            )
        stmt = stmt.order_by(AccountTransfer.occurred_at.desc(), AccountTransfer.created_at.desc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    # ------------------------------ handovers ---------------------------- #
    async def add_handover(self, handover: CashHandover) -> CashHandover:
        self.session.add(handover)
        await self.session.flush()
        return handover

    async def get_handover(self, handover_id: uuid.UUID) -> CashHandover | None:
        return await self.session.get(CashHandover, handover_id)

    async def list_handovers(
        self, *, branch_ids: Sequence[uuid.UUID] | None, status: str | None = None,
        person: str | None = None, date_from: dt.date | None = None, date_to: dt.date | None = None,
    ) -> list[CashHandover]:
        stmt = select(CashHandover)
        if branch_ids is not None:
            stmt = stmt.where(CashHandover.branch_id.in_(list(branch_ids)))
        if status is not None:
            stmt = stmt.where(CashHandover.status == status)
        if person is not None:
            like = f"%{person.lower()}%"
            stmt = stmt.where(
                func.lower(func.coalesce(CashHandover.received_by_name, "")).like(like)
                | func.lower(func.coalesce(CashHandover.handed_over_by_name, "")).like(like)
            )
        if date_from is not None:
            stmt = stmt.where(CashHandover.handover_datetime >= dt.datetime.combine(date_from, dt.time()))
        if date_to is not None:
            stmt = stmt.where(CashHandover.handover_datetime <= dt.datetime.combine(date_to, dt.time.max))
        stmt = stmt.order_by(CashHandover.handover_datetime.desc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_handover_attachment(self, handover_id: uuid.UUID) -> CashHandoverAttachment | None:
        res = await self.session.execute(
            select(CashHandoverAttachment).where(CashHandoverAttachment.handover_id == handover_id)
        )
        return res.scalar_one_or_none()

    async def upsert_handover_attachment(
        self, *, tenant_id: uuid.UUID, handover_id: uuid.UUID, filename: str,
        content_type: str | None, data: bytes, uploaded_by: uuid.UUID | None,
    ) -> CashHandoverAttachment:
        existing = await self.get_handover_attachment(handover_id)
        if existing is not None:
            existing.filename = filename
            existing.content_type = content_type
            existing.data = data
            existing.uploaded_by = uploaded_by
            await self.session.flush()
            return existing
        row = CashHandoverAttachment(
            tenant_id=tenant_id, handover_id=handover_id, filename=filename,
            content_type=content_type, data=data, uploaded_by=uploaded_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row
