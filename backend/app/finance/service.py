"""Finance service — accounts, the append-only movement ledger, and the SINGLE
derived-balance calculation every caller reuses.

Invariant (mirrors the stock ledger):

    balance == opening_balance + sum(IN) - sum(OUT)

The balance is DERIVED here and nowhere else. No method sets, edits, or zeroes a balance;
if a balance changes, a movement explains it. Corrections are reversing movements
(:meth:`reverse_movement`), never edits or deletes. Everything is branch-scoped and audited.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.finance.repository import FinanceRepository
from app.finance.schemas import (
    AccountBalanceOut,
    AccountCreate,
    AccountOut,
    AccountStatementOut,
    AccountUpdate,
    CategoryOut,
    DayBookBranchRow,
    DayBookOut,
    ExpenseCreate,
    ExpenseOut,
    ExpenseUpdate,
    FinanceDashboardOut,
    HandoverCreate,
    HandoverOut,
    MoneyInByAccount,
    PaymentMappingOut,
    StatementRow,
    TransferCreate,
    TransferOut,
)
from app.models import (
    AccountMovement,
    AccountTransfer,
    CashHandover,
    Expense,
    ExpenseCategory,
    FinancialAccount,
)
from app.models.finance import (
    ACCOUNT_TYPES,
    DIRECTION_IN,
    DIRECTION_OUT,
    PAYMENT_METHODS,
)
from app.reports.sales_log import _period_bounds
from app.repositories.audit_repo import AuditRepository

# Types that hold real cash/value at a physical site — a branch is mandatory. A CUSTODY
# account (accountant / head-office custody) may be tenant-wide (no branch).
_BRANCH_REQUIRED_TYPES = ("CASH", "BANK", "MOBILE_MONEY")


def derive_balance(opening: Decimal, total_in: Decimal, total_out: Decimal) -> Decimal:
    """THE balance formula (pure, DB-free, unit-testable). Every caller uses this — there is
    no parallel balance logic anywhere in the module."""
    return Decimal(opening) + Decimal(total_in) - Decimal(total_out)


class FinanceService:
    def __init__(self, repo: FinanceRepository, audit: AuditRepository) -> None:
        self.repo = repo
        self.audit = audit

    # ------------------------------ helpers ------------------------------- #
    def _ensure_visible(
        self, account: FinancialAccount, allowed_branch_ids: frozenset[uuid.UUID] | None
    ) -> None:
        """Server-side branch boundary: a scoped user may only touch accounts in their
        branch(es) — plus tenant-wide custody accounts (branch_id NULL), a valid handover
        destination for any branch. ``None`` = unrestricted (owners/admins)."""
        if allowed_branch_ids is None:
            return
        if account.branch_id is not None and account.branch_id not in allowed_branch_ids:
            raise PermissionDeniedError("You are not assigned to that account's branch.")

    async def _require_account(
        self, account_id: uuid.UUID, allowed_branch_ids: frozenset[uuid.UUID] | None = None
    ) -> FinancialAccount:
        account = await self.repo.get_account(account_id)
        if account is None:
            raise NotFoundError("Account not found")
        self._ensure_visible(account, allowed_branch_ids)
        return account

    async def _to_out(self, account: FinancialAccount, names: dict | None = None) -> AccountOut:
        if names is None:
            names = await self.repo.branch_name_map()
        out = AccountOut.model_validate(account)
        out.branch_name = names.get(account.branch_id) if account.branch_id else None
        return out

    # ------------------------------ accounts ------------------------------ #
    async def create_account(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, data: AccountCreate,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None, ip: str | None = None,
    ) -> AccountOut:
        if data.type not in ACCOUNT_TYPES:
            raise BusinessRuleError(f"Unknown account type '{data.type}'.")
        if data.type in _BRANCH_REQUIRED_TYPES and data.branch_id is None:
            raise BusinessRuleError(
                f"A branch is required for a {data.type} account (cash in hand is per branch)."
            )
        if data.branch_id is not None and allowed_branch_ids is not None:
            if data.branch_id not in allowed_branch_ids:
                raise PermissionDeniedError("You are not assigned to that branch.")
        if data.opening_balance < 0:
            raise BusinessRuleError("Opening balance cannot be negative.")
        account = FinancialAccount(
            tenant_id=tenant_id, branch_id=data.branch_id, name=data.name.strip(),
            type=data.type, currency=data.currency, opening_balance=data.opening_balance,
            opening_as_of=data.opening_as_of, is_active=True,
        )
        await self.repo.add_account(account)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="create", entity_type="financial_account",
            entity_id=account.id,
            changes={"after": {"name": account.name, "type": account.type,
                               "branch_id": str(account.branch_id) if account.branch_id else None,
                               "currency": account.currency,
                               "opening_balance": str(account.opening_balance)}},
            ip_address=ip,
        )
        return await self._to_out(account)

    async def update_account(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, account_id: uuid.UUID,
        data: AccountUpdate, allowed_branch_ids: frozenset[uuid.UUID] | None = None,
        ip: str | None = None,
    ) -> AccountOut:
        account = await self._require_account(account_id, allowed_branch_ids)
        changes = data.model_dump(exclude_unset=True)
        before = {"name": account.name, "is_active": account.is_active}
        if "name" in changes and changes["name"] is not None:
            account.name = changes["name"].strip()
        if "is_active" in changes and changes["is_active"] is not None:
            account.is_active = changes["is_active"]
        await self.repo.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="update", entity_type="financial_account",
            entity_id=account.id,
            changes={"before": before, "after": {"name": account.name, "is_active": account.is_active}},
            ip_address=ip,
        )
        return await self._to_out(account)

    async def get_account(
        self, *, account_id: uuid.UUID, allowed_branch_ids: frozenset[uuid.UUID] | None = None
    ) -> AccountBalanceOut:
        account = await self._require_account(account_id, allowed_branch_ids)
        total_in, total_out = await self.repo.movement_sums(account.id)
        return await self._to_balance_out(account, total_in, total_out)

    async def account_balance(self, account_id: uuid.UUID) -> Decimal:
        """The single reusable balance accessor: opening + sum(IN) - sum(OUT)."""
        account = await self.repo.get_account(account_id)
        if account is None:
            raise NotFoundError("Account not found")
        total_in, total_out = await self.repo.movement_sums(account_id)
        return derive_balance(account.opening_balance, total_in, total_out)

    async def list_accounts(
        self, *, allowed_branch_ids: frozenset[uuid.UUID] | None, active_only: bool = False,
        type: str | None = None,
    ) -> list[AccountBalanceOut]:
        branch_ids = None if allowed_branch_ids is None else list(allowed_branch_ids)
        accounts = await self.repo.list_accounts(
            branch_ids=branch_ids, active_only=active_only, type=type
        )
        sums = await self.repo.sums_by_account([a.id for a in accounts])
        names = await self.repo.branch_name_map()
        out: list[AccountBalanceOut] = []
        for a in accounts:
            total_in, total_out = sums.get(a.id, (Decimal("0"), Decimal("0")))
            out.append(await self._to_balance_out(a, total_in, total_out, names))
        return out

    async def _to_balance_out(
        self, account: FinancialAccount, total_in: Decimal, total_out: Decimal,
        names: dict | None = None,
    ) -> AccountBalanceOut:
        base = await self._to_out(account, names)
        return AccountBalanceOut(
            **base.model_dump(),
            total_in=total_in, total_out=total_out,
            balance=derive_balance(account.opening_balance, total_in, total_out),
        )

    # ------------------------------ movements ----------------------------- #
    async def post_movement(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID | None, account_id: uuid.UUID,
        direction: str, amount: Decimal, category: str | None = None,
        reference_type: str | None = None, reference_id: uuid.UUID | None = None,
        description: str | None = None, occurred_at: dt.datetime | None = None,
        reversal_of: uuid.UUID | None = None,
    ) -> AccountMovement:
        """THE single append-only writer every producer (money-in, expense, transfer,
        handover) funnels through. Locks the account row (SELECT FOR UPDATE), appends ONE
        immutable movement, and audits it. Never mutates a stored balance — the balance is
        always re-derived from the ledger.

        Runs inside the caller's transaction, so a failure rolls the whole operation back.
        """
        if direction not in (DIRECTION_IN, DIRECTION_OUT):
            raise BusinessRuleError(f"Invalid movement direction '{direction}'.")
        if amount is None or Decimal(amount) <= 0:
            raise BusinessRuleError("Movement amount must be positive (direction carries the sign).")
        account = await self.repo.get_account_for_update(account_id)
        if account is None:
            raise NotFoundError("Account not found")
        if not account.is_active:
            raise BusinessRuleError(f"Account '{account.name}' is inactive and cannot take movements.")
        movement = await self.repo.add_movement(
            tenant_id=tenant_id, account_id=account_id, direction=direction, amount=Decimal(amount),
            occurred_at=occurred_at, category=category, reference_type=reference_type,
            reference_id=reference_id, description=description, created_by=user_id,
            reversal_of=reversal_of,
        )
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="finance.movement",
            entity_type="account_movement", entity_id=movement.id,
            changes={"account_id": str(account_id), "direction": direction,
                     "amount": str(amount), "category": category,
                     "reference_type": reference_type,
                     "reference_id": str(reference_id) if reference_id else None,
                     "reversal_of": str(reversal_of) if reversal_of else None},
        )
        return movement

    async def reverse_movement(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID | None, movement_id: uuid.UUID,
        reason: str, occurred_at: dt.datetime | None = None,
    ) -> AccountMovement:
        """Cancel a movement WITHOUT deleting it: post a new movement in the opposite
        direction, same amount, pointing back at the original via ``reversal_of``. The
        original stays for audit; the balance self-corrects because the two net to zero."""
        original = await self.repo.get_movement(movement_id)
        if original is None:
            raise NotFoundError("Movement not found")
        opposite = DIRECTION_OUT if original.direction == DIRECTION_IN else DIRECTION_IN
        return await self.post_movement(
            tenant_id=tenant_id, user_id=user_id, account_id=original.account_id,
            direction=opposite, amount=original.amount, category=original.category,
            reference_type=original.reference_type, reference_id=original.reference_id,
            description=f"Reversal: {reason}", occurred_at=occurred_at, reversal_of=original.id,
        )

    async def reverse_reference(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID | None, reference_type: str,
        reference_id: uuid.UUID, reason: str,
    ) -> list[AccountMovement]:
        """Reverse every not-yet-reversed movement tied to a source document (e.g. all the
        IN movements from a voided invoice's payments). Originals are preserved."""
        originals = await self.repo.unreversed_for_reference(reference_type, reference_id)
        return [
            await self.reverse_movement(
                tenant_id=tenant_id, user_id=user_id, movement_id=mv.id, reason=reason)
            for mv in originals
        ]

    # ------------------------ money-in from payments ---------------------- #
    async def post_invoice_payments(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID | None,
        branch_id: uuid.UUID | None, invoice_id: uuid.UUID, invoice_number: str,
        lines: list[tuple[str, Decimal]],
    ) -> list[AccountMovement]:
        """Money in is never re-entered: given the payment lines the SALES module just
        recorded, post ONE IN movement per line to the account mapped to that method at the
        sale's branch. A SPLIT payment therefore posts one movement per line.

        Activation is per branch: if the branch has NO mappings, finance money-in is dormant
        and nothing is posted (the sales flow is untouched). If it HAS mappings but a line's
        method is unmapped, this RAISES — failing the whole sale rather than silently dropping
        the money. Runs in the caller's transaction, so a failure rolls the sale back.
        """
        if branch_id is None:
            return []
        if not await self.repo.branch_has_mappings(branch_id):
            return []  # finance money-in not configured for this branch — dormant
        posted: list[AccountMovement] = []
        for method, amount in lines:
            mapping = await self.repo.mapping_for(branch_id, method)
            if mapping is None:
                raise BusinessRuleError(
                    f"No finance account is mapped for '{method}' payments at this branch. "
                    "Map one under Finance → Payment Setup (or remove this branch's mappings "
                    "to turn finance money-in off)."
                )
            posted.append(await self.post_movement(
                tenant_id=tenant_id, user_id=user_id, account_id=mapping.account_id,
                direction=DIRECTION_IN, amount=Decimal(amount), category="sale_payment",
                reference_type="invoice_payment", reference_id=invoice_id,
                description=f"{method} payment on invoice {invoice_number}",
            ))
        return posted

    # --------------------------- payment mapping -------------------------- #
    async def list_mappings(
        self, *, allowed_branch_ids: frozenset[uuid.UUID] | None
    ) -> list[PaymentMappingOut]:
        branch_ids = None if allowed_branch_ids is None else list(allowed_branch_ids)
        rows = await self.repo.list_mappings(branch_ids)
        names = await self.repo.branch_name_map()
        accounts = {a.id: a.name for a in await self.repo.list_accounts(branch_ids=branch_ids)}
        return [
            PaymentMappingOut(
                id=r.id, branch_id=r.branch_id, branch_name=names.get(r.branch_id),
                method=r.method, account_id=r.account_id, account_name=accounts.get(r.account_id),
            )
            for r in rows
        ]

    async def set_mapping(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, branch_id: uuid.UUID, method: str,
        account_id: uuid.UUID, allowed_branch_ids: frozenset[uuid.UUID] | None = None,
        ip: str | None = None,
    ) -> PaymentMappingOut:
        if method not in PAYMENT_METHODS:
            raise BusinessRuleError(f"Unknown payment method '{method}'.")
        if allowed_branch_ids is not None and branch_id not in allowed_branch_ids:
            raise PermissionDeniedError("You are not assigned to that branch.")
        account = await self._require_account(account_id, allowed_branch_ids)
        # The account must serve this branch (its own branch, or a tenant-wide account).
        if account.branch_id is not None and account.branch_id != branch_id:
            raise BusinessRuleError("The chosen account belongs to a different branch.")
        if not account.is_active:
            raise BusinessRuleError("The chosen account is inactive.")
        row = await self.repo.upsert_mapping(
            tenant_id=tenant_id, branch_id=branch_id, method=method, account_id=account_id)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="finance.mapping.set",
            entity_type="finance_payment_map", entity_id=row.id,
            changes={"branch_id": str(branch_id), "method": method, "account_id": str(account_id)},
            ip_address=ip,
        )
        names = await self.repo.branch_name_map()
        return PaymentMappingOut(
            id=row.id, branch_id=branch_id, branch_name=names.get(branch_id), method=method,
            account_id=account_id, account_name=account.name,
        )

    async def delete_mapping(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, mapping_id: uuid.UUID,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None, ip: str | None = None,
    ) -> None:
        row = await self.repo.get_mapping(mapping_id)
        if row is None:
            raise NotFoundError("Mapping not found")
        if allowed_branch_ids is not None and row.branch_id not in allowed_branch_ids:
            raise PermissionDeniedError("You are not assigned to that branch.")
        await self.repo.delete_mapping(row)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="finance.mapping.delete",
            entity_type="finance_payment_map", entity_id=mapping_id,
            changes={"branch_id": str(row.branch_id), "method": row.method}, ip_address=ip,
        )

    # ------------------------- expense categories ------------------------ #
    async def list_categories(self, *, active_only: bool = False) -> list[CategoryOut]:
        return [CategoryOut.model_validate(c) for c in await self.repo.list_categories(active_only=active_only)]

    async def create_category(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, name: str, ip: str | None = None
    ) -> CategoryOut:
        name = name.strip()
        if await self.repo.category_by_name(name) is not None:
            raise ConflictError(f"An expense category '{name}' already exists.")
        category = ExpenseCategory(tenant_id=tenant_id, name=name, is_active=True)
        await self.repo.add_category(category)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="create", entity_type="expense_category",
            entity_id=category.id, changes={"name": name}, ip_address=ip,
        )
        return CategoryOut.model_validate(category)

    async def update_category(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, category_id: uuid.UUID,
        name: str | None = None, is_active: bool | None = None, ip: str | None = None,
    ) -> CategoryOut:
        category = await self.repo.get_category(category_id)
        if category is None:
            raise NotFoundError("Category not found")
        if name is not None and name.strip() and name.strip().lower() != category.name.lower():
            if await self.repo.category_by_name(name.strip()) is not None:
                raise ConflictError(f"An expense category '{name.strip()}' already exists.")
            category.name = name.strip()
        if is_active is not None:
            category.is_active = is_active
        await self.repo.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="update", entity_type="expense_category",
            entity_id=category.id, changes={"name": category.name, "is_active": category.is_active},
            ip_address=ip,
        )
        return CategoryOut.model_validate(category)

    # ------------------------------ expenses ----------------------------- #
    async def _to_expense_out(
        self, expense: Expense, *, names: dict | None = None, accounts: dict | None = None,
        categories: dict | None = None, has_attachment: bool = False,
    ) -> ExpenseOut:
        if names is None:
            names = await self.repo.branch_name_map()
        if categories is None:
            categories = await self.repo.category_name_map()
        out = ExpenseOut.model_validate(expense)
        out.branch_name = names.get(expense.branch_id) if expense.branch_id else None
        out.category_name = categories.get(expense.category_id) if expense.category_id else None
        if accounts is not None:
            out.account_name = accounts.get(expense.account_id)
        else:
            acct = await self.repo.get_account(expense.account_id)
            out.account_name = acct.name if acct is not None else None
        out.has_attachment = has_attachment
        return out

    async def create_expense(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, data: ExpenseCreate,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None, ip: str | None = None,
    ) -> ExpenseOut:
        if data.amount <= 0:
            raise BusinessRuleError("Expense amount must be positive.")
        account = await self._require_account(data.account_id, allowed_branch_ids)
        if not account.is_active:
            raise BusinessRuleError(f"Account '{account.name}' is inactive.")
        # An expense is branch-scoped: use the given branch, else the account's own branch.
        branch_id = data.branch_id or account.branch_id
        if branch_id is None:
            raise BusinessRuleError("A branch is required to record an expense.")
        if allowed_branch_ids is not None and branch_id not in allowed_branch_ids:
            raise PermissionDeniedError("You are not assigned to that branch.")
        if account.branch_id is not None and account.branch_id != branch_id:
            raise BusinessRuleError("The chosen account belongs to a different branch.")
        if data.category_id is not None:
            category = await self.repo.get_category(data.category_id)
            if category is None:
                raise NotFoundError("Category not found")
            if not category.is_active:
                raise BusinessRuleError("That expense category is inactive.")
        expense = Expense(
            tenant_id=tenant_id, branch_id=branch_id, account_id=data.account_id,
            amount=data.amount, expense_date=data.expense_date, category_id=data.category_id,
            payee=(data.payee or None), description=data.description,
            reference_no=(data.reference_no or None), status="recorded", recorded_by=user_id,
        )
        await self.repo.add_expense(expense)
        # The money leaves the account: one OUT movement through the append-only ledger, so
        # the balance drops by exactly the amount.
        await self.post_movement(
            tenant_id=tenant_id, user_id=user_id, account_id=data.account_id,
            direction=DIRECTION_OUT, amount=data.amount, category="expense",
            reference_type="expense", reference_id=expense.id,
            occurred_at=dt.datetime.combine(data.expense_date, dt.time()),
            description=f"Expense: {data.payee or (data.description or 'recorded')}",
        )
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="create", entity_type="expense",
            entity_id=expense.id,
            changes={"account_id": str(data.account_id), "amount": str(data.amount),
                     "branch_id": str(branch_id), "category_id": str(data.category_id) if data.category_id else None},
            ip_address=ip,
        )
        return await self._to_expense_out(expense)

    async def list_expenses(
        self, *, allowed_branch_ids: frozenset[uuid.UUID] | None, category_id=None,
        account_id=None, status=None, date_from=None, date_to=None,
    ) -> list[ExpenseOut]:
        branch_ids = None if allowed_branch_ids is None else list(allowed_branch_ids)
        rows = await self.repo.list_expenses(
            branch_ids=branch_ids, category_id=category_id, account_id=account_id,
            status=status, date_from=date_from, date_to=date_to)
        names = await self.repo.branch_name_map()
        categories = await self.repo.category_name_map()
        accounts = {a.id: a.name for a in await self.repo.list_accounts(branch_ids=branch_ids)}
        with_attach = await self.repo.attachment_expense_ids([e.id for e in rows])
        return [
            await self._to_expense_out(
                e, names=names, accounts=accounts, categories=categories,
                has_attachment=e.id in with_attach)
            for e in rows
        ]

    async def _require_expense(
        self, expense_id: uuid.UUID, allowed_branch_ids: frozenset[uuid.UUID] | None
    ) -> Expense:
        expense = await self.repo.get_expense(expense_id)
        if expense is None:
            raise NotFoundError("Expense not found")
        if allowed_branch_ids is not None and expense.branch_id not in allowed_branch_ids:
            raise PermissionDeniedError("You are not assigned to that expense's branch.")
        return expense

    async def get_expense(
        self, *, expense_id: uuid.UUID, allowed_branch_ids: frozenset[uuid.UUID] | None = None
    ) -> ExpenseOut:
        expense = await self._require_expense(expense_id, allowed_branch_ids)
        has = await self.repo.get_attachment(expense_id) is not None
        return await self._to_expense_out(expense, has_attachment=has)

    async def update_expense(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, expense_id: uuid.UUID,
        data: ExpenseUpdate, allowed_branch_ids: frozenset[uuid.UUID] | None = None,
        ip: str | None = None,
    ) -> ExpenseOut:
        expense = await self._require_expense(expense_id, allowed_branch_ids)
        if expense.status == "voided":
            raise BusinessRuleError("A voided expense cannot be edited.")
        changes = data.model_dump(exclude_unset=True)
        if "category_id" in changes and changes["category_id"] is not None:
            if await self.repo.get_category(changes["category_id"]) is None:
                raise NotFoundError("Category not found")
        for field in ("category_id", "payee", "description", "reference_no", "expense_date"):
            if field in changes:
                setattr(expense, field, changes[field])
        await self.repo.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="update", entity_type="expense",
            entity_id=expense.id, changes={k: str(v) for k, v in changes.items()}, ip_address=ip,
        )
        has = await self.repo.get_attachment(expense_id) is not None
        return await self._to_expense_out(expense, has_attachment=has)

    async def void_expense(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, expense_id: uuid.UUID, reason: str,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None, ip: str | None = None,
    ) -> ExpenseOut:
        """Correct an expense WITHOUT deleting it: reverse the OUT movement (a reversing IN
        restores the account balance) and mark the record voided with who/when/why."""
        reason = (reason or "").strip()
        if not reason:
            raise BusinessRuleError("A reason is required to void an expense.")
        expense = await self._require_expense(expense_id, allowed_branch_ids)
        if expense.status == "voided":
            raise BusinessRuleError("This expense is already voided.")
        await self.reverse_reference(
            tenant_id=tenant_id, user_id=user_id, reference_type="expense",
            reference_id=expense.id, reason=f"Expense voided: {reason}")
        expense.status = "voided"
        expense.void_reason = reason
        expense.voided_by = user_id
        expense.voided_at = dt.datetime.now(dt.UTC)
        await self.repo.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="void", entity_type="expense",
            entity_id=expense.id, changes={"reason": reason}, ip_address=ip,
        )
        has = await self.repo.get_attachment(expense_id) is not None
        return await self._to_expense_out(expense, has_attachment=has)

    # ---------------------------- attachments ---------------------------- #
    async def set_attachment(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, expense_id: uuid.UUID,
        filename: str, content_type: str | None, data: bytes,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None,
    ) -> None:
        if not data:
            raise BusinessRuleError("The uploaded receipt is empty.")
        await self._require_expense(expense_id, allowed_branch_ids)
        await self.repo.upsert_attachment(
            tenant_id=tenant_id, expense_id=expense_id, filename=filename,
            content_type=content_type, data=data, uploaded_by=user_id)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="attachment", entity_type="expense",
            entity_id=expense_id, changes={"filename": filename})

    async def get_attachment(
        self, *, expense_id: uuid.UUID, allowed_branch_ids: frozenset[uuid.UUID] | None = None
    ) -> tuple[bytes, str, str | None]:
        await self._require_expense(expense_id, allowed_branch_ids)
        att = await self.repo.get_attachment(expense_id)
        if att is None:
            raise NotFoundError("No receipt attached to this expense.")
        return att.data, att.filename, att.content_type

    # ------------------------------ transfers ---------------------------- #
    async def _lock_two(self, a: uuid.UUID, b: uuid.UUID) -> None:
        """Lock two account rows in a deterministic order so concurrent transfers/handovers
        can't deadlock (mirrors the stock transfer's ordered locking)."""
        for aid in sorted((a, b), key=str):
            await self.repo.get_account_for_update(aid)

    async def create_transfer(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, data: TransferCreate,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None, ip: str | None = None,
    ) -> TransferOut:
        if data.from_account_id == data.to_account_id:
            raise BusinessRuleError("Source and destination accounts must differ.")
        if data.amount <= 0:
            raise BusinessRuleError("Transfer amount must be positive.")
        src = await self._require_account(data.from_account_id, allowed_branch_ids)
        dst = await self._require_account(data.to_account_id, allowed_branch_ids)
        if not src.is_active or not dst.is_active:
            raise BusinessRuleError("Both accounts must be active to transfer.")
        await self._lock_two(src.id, dst.id)
        transfer = AccountTransfer(
            tenant_id=tenant_id, from_account_id=src.id, to_account_id=dst.id, amount=data.amount,
            occurred_at=data.occurred_at, reference_no=(data.reference_no or None),
            notes=data.notes, status="completed", created_by=user_id,
        )
        await self.repo.add_transfer(transfer)
        # Paired OUT + IN in ONE transaction, both tagged to this transfer — never one-sided.
        desc = f"Transfer to {dst.name}"
        await self.post_movement(
            tenant_id=tenant_id, user_id=user_id, account_id=src.id, direction=DIRECTION_OUT,
            amount=data.amount, category="transfer", reference_type="transfer",
            reference_id=transfer.id, occurred_at=data.occurred_at, description=desc)
        await self.post_movement(
            tenant_id=tenant_id, user_id=user_id, account_id=dst.id, direction=DIRECTION_IN,
            amount=data.amount, category="transfer", reference_type="transfer",
            reference_id=transfer.id, occurred_at=data.occurred_at,
            description=f"Transfer from {src.name}")
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="finance.transfer", entity_type="account_transfer",
            entity_id=transfer.id,
            changes={"from": str(src.id), "to": str(dst.id), "amount": str(data.amount)}, ip_address=ip)
        return await self._to_transfer_out(transfer)

    async def _to_transfer_out(self, t: AccountTransfer, accounts: dict | None = None) -> TransferOut:
        if accounts is None:
            accounts = {a.id: a.name for a in await self.repo.list_accounts(branch_ids=None)}
        out = TransferOut.model_validate(t)
        out.from_account_name = accounts.get(t.from_account_id)
        out.to_account_name = accounts.get(t.to_account_id)
        return out

    async def list_transfers(
        self, *, allowed_branch_ids: frozenset[uuid.UUID] | None
    ) -> list[TransferOut]:
        branch_ids = None if allowed_branch_ids is None else list(allowed_branch_ids)
        accounts_full = await self.repo.list_accounts(branch_ids=branch_ids)
        account_ids = None if branch_ids is None else [a.id for a in accounts_full]
        rows = await self.repo.list_transfers(account_ids=account_ids)
        accounts = {a.id: a.name for a in await self.repo.list_accounts(branch_ids=None)}
        return [await self._to_transfer_out(t, accounts) for t in rows]

    async def reverse_transfer(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, transfer_id: uuid.UUID, reason: str,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None, ip: str | None = None,
    ) -> TransferOut:
        reason = (reason or "").strip()
        if not reason:
            raise BusinessRuleError("A reason is required to reverse a transfer.")
        transfer = await self.repo.get_transfer(transfer_id)
        if transfer is None:
            raise NotFoundError("Transfer not found")
        # Both accounts must be in scope to reverse.
        await self._require_account(transfer.from_account_id, allowed_branch_ids)
        await self._require_account(transfer.to_account_id, allowed_branch_ids)
        if transfer.status == "reversed":
            raise BusinessRuleError("This transfer is already reversed.")
        await self.reverse_reference(
            tenant_id=tenant_id, user_id=user_id, reference_type="transfer",
            reference_id=transfer.id, reason=f"Transfer reversed: {reason}")
        transfer.status = "reversed"
        transfer.reversed_by = user_id
        transfer.reversed_at = dt.datetime.now(dt.UTC)
        transfer.reverse_reason = reason
        await self.repo.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="finance.transfer.reverse",
            entity_type="account_transfer", entity_id=transfer.id,
            changes={"reason": reason}, ip_address=ip)
        return await self._to_transfer_out(transfer)

    # ------------------------------ handovers ---------------------------- #
    async def _to_handover_out(
        self, h: CashHandover, *, names: dict | None = None, accounts: dict | None = None,
        has_attachment: bool = False,
    ) -> HandoverOut:
        if names is None:
            names = await self.repo.branch_name_map()
        if accounts is None:
            accounts = {a.id: a.name for a in await self.repo.list_accounts(branch_ids=None)}
        out = HandoverOut.model_validate(h)
        out.branch_name = names.get(h.branch_id) if h.branch_id else None
        out.from_account_name = accounts.get(h.from_account_id)
        out.to_account_name = accounts.get(h.to_account_id)
        out.has_attachment = has_attachment
        return out

    async def create_handover(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, data: HandoverCreate,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None, ip: str | None = None,
    ) -> HandoverOut:
        if data.from_account_id == data.to_account_id:
            raise BusinessRuleError("The handover source and destination must differ.")
        if data.amount <= 0:
            raise BusinessRuleError("Handover amount must be positive.")
        if not data.received_by_name.strip():
            raise BusinessRuleError("The receiver's name is required.")
        src = await self._require_account(data.from_account_id, allowed_branch_ids)
        dst = await self._require_account(data.to_account_id, allowed_branch_ids)
        if not src.is_active:
            raise BusinessRuleError("The branch cash account is inactive.")
        branch_id = data.branch_id or src.branch_id
        if branch_id is None:
            raise BusinessRuleError("A branch is required to record a handover.")
        if allowed_branch_ids is not None and branch_id not in allowed_branch_ids:
            raise PermissionDeniedError("You are not assigned to that branch.")
        handover = CashHandover(
            tenant_id=tenant_id, branch_id=branch_id, from_account_id=src.id, to_account_id=dst.id,
            amount=data.amount, handover_datetime=data.handover_datetime,
            handed_over_by=user_id, handed_over_by_name=(data.handed_over_by_name or None),
            received_by_name=data.received_by_name.strip(), received_by_user_id=data.received_by_user_id,
            reference_no=(data.reference_no or None), notes=data.notes,
            denomination_breakdown=data.denomination_breakdown, status="PENDING_CONFIRMATION",
            created_by=user_id,
        )
        await self.repo.add_handover(handover)
        # The branch no longer holds the cash: post the OUT immediately (money in transit).
        # The receiver's NAME is in the description so the branch statement answers
        # "where did the cash go" on its own.
        await self.post_movement(
            tenant_id=tenant_id, user_id=user_id, account_id=src.id, direction=DIRECTION_OUT,
            amount=data.amount, category="handover", reference_type="handover",
            reference_id=handover.id, occurred_at=data.handover_datetime,
            description=f"Cash handover to {handover.received_by_name}")
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="finance.handover.record",
            entity_type="cash_handover", entity_id=handover.id,
            changes={"from": str(src.id), "to": str(dst.id), "amount": str(data.amount),
                     "received_by": handover.received_by_name}, ip_address=ip)
        return await self._to_handover_out(handover)

    async def confirm_handover(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, handover_id: uuid.UUID,
        confirmed_amount: Decimal, discrepancy_reason: str | None = None,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None, ip: str | None = None,
    ) -> HandoverOut:
        handover = await self._require_handover(handover_id, allowed_branch_ids)
        if handover.status != "PENDING_CONFIRMATION":
            raise BusinessRuleError(f"This handover is already {handover.status.lower()}.")
        if confirmed_amount < 0:
            raise BusinessRuleError("The confirmed amount cannot be negative.")
        matches = Decimal(confirmed_amount) == Decimal(handover.amount)
        if not matches and not (discrepancy_reason or "").strip():
            # A shortfall/overage is NEVER silently absorbed — a reason is mandatory.
            raise BusinessRuleError(
                "The counted amount differs from the handover amount — a discrepancy reason is required.")
        handover.confirmed_by = user_id
        handover.confirmed_at = dt.datetime.now(dt.UTC)
        handover.confirmed_amount = Decimal(confirmed_amount)
        if matches:
            handover.status = "CONFIRMED"
            handover.discrepancy_amount = Decimal("0")
        else:
            handover.status = "DISPUTED"
            handover.discrepancy_amount = Decimal(handover.amount) - Decimal(confirmed_amount)
            handover.discrepancy_reason = discrepancy_reason.strip()
        # Post the IN for what was ACTUALLY received (skip a zero-value movement).
        if Decimal(confirmed_amount) > 0:
            await self.post_movement(
                tenant_id=tenant_id, user_id=user_id, account_id=handover.to_account_id,
                direction=DIRECTION_IN, amount=Decimal(confirmed_amount), category="handover",
                reference_type="handover", reference_id=handover.id,
                description=f"Cash handover received from {handover.handed_over_by_name or 'branch'}")
        await self.repo.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="finance.handover.confirm",
            entity_type="cash_handover", entity_id=handover.id,
            changes={"confirmed_amount": str(confirmed_amount), "status": handover.status,
                     "discrepancy_amount": str(handover.discrepancy_amount)}, ip_address=ip)
        return await self._to_handover_out(handover, has_attachment=await self.repo.get_handover_attachment(handover.id) is not None)

    async def reverse_handover(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, handover_id: uuid.UUID, reason: str,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None, ip: str | None = None,
    ) -> HandoverOut:
        reason = (reason or "").strip()
        if not reason:
            raise BusinessRuleError("A reason is required to reverse a handover.")
        handover = await self._require_handover(handover_id, allowed_branch_ids)
        if handover.reversed_at is not None:
            raise BusinessRuleError("This handover is already reversed.")
        # Reverse whatever legs exist (the OUT always; the IN too if it was confirmed).
        await self.reverse_reference(
            tenant_id=tenant_id, user_id=user_id, reference_type="handover",
            reference_id=handover.id, reason=f"Handover reversed: {reason}")
        handover.reversed_by = user_id
        handover.reversed_at = dt.datetime.now(dt.UTC)
        handover.reverse_reason = reason
        await self.repo.session.flush()
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="finance.handover.reverse",
            entity_type="cash_handover", entity_id=handover.id, changes={"reason": reason}, ip_address=ip)
        return await self._to_handover_out(handover, has_attachment=await self.repo.get_handover_attachment(handover.id) is not None)

    async def _require_handover(
        self, handover_id: uuid.UUID, allowed_branch_ids: frozenset[uuid.UUID] | None
    ) -> CashHandover:
        handover = await self.repo.get_handover(handover_id)
        if handover is None:
            raise NotFoundError("Handover not found")
        if allowed_branch_ids is not None and handover.branch_id not in allowed_branch_ids:
            raise PermissionDeniedError("You are not assigned to that handover's branch.")
        return handover

    async def get_handover(
        self, *, handover_id: uuid.UUID, allowed_branch_ids: frozenset[uuid.UUID] | None = None
    ) -> HandoverOut:
        handover = await self._require_handover(handover_id, allowed_branch_ids)
        has = await self.repo.get_handover_attachment(handover_id) is not None
        return await self._to_handover_out(handover, has_attachment=has)

    async def list_handovers(
        self, *, allowed_branch_ids: frozenset[uuid.UUID] | None, status=None, person=None,
        date_from=None, date_to=None,
    ) -> list[HandoverOut]:
        branch_ids = None if allowed_branch_ids is None else list(allowed_branch_ids)
        rows = await self.repo.list_handovers(
            branch_ids=branch_ids, status=status, person=person, date_from=date_from, date_to=date_to)
        names = await self.repo.branch_name_map()
        accounts = {a.id: a.name for a in await self.repo.list_accounts(branch_ids=None)}
        return [await self._to_handover_out(h, names=names, accounts=accounts) for h in rows]

    async def set_handover_attachment(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, handover_id: uuid.UUID,
        filename: str, content_type: str | None, data: bytes,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None,
    ) -> None:
        if not data:
            raise BusinessRuleError("The uploaded slip is empty.")
        await self._require_handover(handover_id, allowed_branch_ids)
        await self.repo.upsert_handover_attachment(
            tenant_id=tenant_id, handover_id=handover_id, filename=filename,
            content_type=content_type, data=data, uploaded_by=user_id)
        await self.audit.add(
            tenant_id=tenant_id, user_id=user_id, action="attachment", entity_type="cash_handover",
            entity_id=handover_id, changes={"filename": filename})

    async def get_handover_attachment(
        self, *, handover_id: uuid.UUID, allowed_branch_ids: frozenset[uuid.UUID] | None = None
    ) -> tuple[bytes, str, str | None]:
        await self._require_handover(handover_id, allowed_branch_ids)
        att = await self.repo.get_handover_attachment(handover_id)
        if att is None:
            raise NotFoundError("No slip attached to this handover.")
        return att.data, att.filename, att.content_type

    async def handover_slip_pdf(
        self, *, handover_id: uuid.UUID, allowed_branch_ids: frozenset[uuid.UUID] | None = None
    ) -> tuple[bytes, str]:
        from app.finance.pdf import build_handover_slip_pdf

        out = await self.get_handover(handover_id=handover_id, allowed_branch_ids=allowed_branch_ids)
        return build_handover_slip_pdf(out), f"handover-{str(out.id)[:8]}"

    # =================== dashboard / statement / day book ================= #
    @staticmethod
    def _bounds(date_from: dt.date, date_to: dt.date) -> tuple[dt.datetime, dt.datetime]:
        return (dt.datetime.combine(date_from, dt.time.min, tzinfo=dt.UTC),
                dt.datetime.combine(date_to, dt.time.max, tzinfo=dt.UTC))

    async def _opening(self, accounts: list[FinancialAccount], before_dt: dt.datetime) -> Decimal:
        """The combined balance of ``accounts`` as of just before ``before_dt`` — the sum of
        their opening balances plus every movement dated earlier."""
        base = sum((Decimal(a.opening_balance) for a in accounts), Decimal("0"))
        sin, sout = await self.repo.signed_sum_before([a.id for a in accounts], before_dt)
        return base + sin - sout

    async def dashboard(
        self, *, allowed_branch_ids: frozenset[uuid.UUID] | None, date_from: dt.date, date_to: dt.date,
    ) -> FinanceDashboardOut:
        accounts = await self.list_accounts(allowed_branch_ids=allowed_branch_ids)  # with balances
        branch_ids = None if allowed_branch_ids is None else list(allowed_branch_ids)
        account_rows = await self.repo.list_accounts(branch_ids=branch_ids)
        ids = [a.id for a in account_rows]
        start_dt, end_dt = self._bounds(date_from, date_to)
        sums = await self.repo.period_category_sums(ids, start_dt, end_dt)
        money_in = sums.get(("sale_payment", "IN"), Decimal("0"))
        expenses_out = sums.get(("expense", "OUT"), Decimal("0"))
        handovers_out = sums.get(("handover", "OUT"), Decimal("0"))
        transfers_out = sums.get(("transfer", "OUT"), Decimal("0"))
        total_in = sum((v for (_c, d), v in sums.items() if d == "IN"), Decimal("0"))
        total_out = sum((v for (_c, d), v in sums.items() if d == "OUT"), Decimal("0"))
        by_account = await self.repo.money_in_by_account(ids, start_dt, end_dt)
        names = {a.id: a.name for a in account_rows}
        breakdown = [
            MoneyInByAccount(account_id=aid, account_name=names.get(aid), amount=amt)
            for aid, amt in sorted(by_account.items(), key=lambda kv: -kv[1])
        ]
        return FinanceDashboardOut(
            date_from=date_from, date_to=date_to, accounts=accounts,
            money_in=money_in, expenses_out=expenses_out, handovers_out=handovers_out,
            transfers_out=transfers_out, net_movement=total_in - total_out,
            money_in_by_account=breakdown,
        )

    async def account_statement(
        self, *, account_id: uuid.UUID, date_from: dt.date, date_to: dt.date,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None,
    ) -> AccountStatementOut:
        account = await self._require_account(account_id, allowed_branch_ids)
        start_dt, end_dt = self._bounds(date_from, date_to)
        opening = await self._opening([account], start_dt)
        movements = await self.repo.statement_movements(account.id, start_dt, end_dt)
        running = opening
        total_in = total_out = Decimal("0")
        rows: list[StatementRow] = []
        for m in movements:
            amt = Decimal(m.amount)
            is_in = m.direction == DIRECTION_IN
            running = running + amt if is_in else running - amt
            if is_in:
                total_in += amt
            else:
                total_out += amt
            rows.append(StatementRow(
                id=m.id, occurred_at=m.occurred_at, description=m.description, category=m.category,
                reference_type=m.reference_type, reference_id=m.reference_id, direction=m.direction,
                amount=amt, in_amount=amt if is_in else Decimal("0"),
                out_amount=amt if not is_in else Decimal("0"), running_balance=running,
            ))
        return AccountStatementOut(
            account_id=account.id, account_name=account.name, currency=account.currency,
            date_from=date_from, date_to=date_to, opening_balance=opening, rows=rows,
            total_in=total_in, total_out=total_out, closing_balance=running,
        )

    async def day_book(
        self, *, allowed_branch_ids: frozenset[uuid.UUID] | None, period: str, on: dt.date,
    ) -> DayBookOut:
        """Cash position for a day / month, per branch: opening + money in - expenses -
        handovers -> closing (transfers between the branch's own accounts net out). Reuses
        the sales report's period bounds so a day/month lines up with the sales reports."""
        date_from, date_to, label = _period_bounds(on, period)
        start_dt, end_dt = self._bounds(date_from, date_to)
        branch_ids = None if allowed_branch_ids is None else list(allowed_branch_ids)
        accounts = await self.repo.list_accounts(branch_ids=branch_ids)
        names = await self.repo.branch_name_map()

        by_branch: dict = {}
        for a in accounts:
            by_branch.setdefault(a.branch_id, []).append(a)

        rows: list[DayBookBranchRow] = []
        for branch_id, branch_accounts in by_branch.items():
            row = await self._day_book_row(branch_id, names.get(branch_id), branch_accounts, start_dt, end_dt)
            rows.append(row)
        rows.sort(key=lambda r: (r.branch_name or ""))
        totals = await self._day_book_row(None, "All branches", accounts, start_dt, end_dt)
        return DayBookOut(period=period, label=label, date_from=date_from, date_to=date_to,
                          rows=rows, totals=totals)

    async def _day_book_row(
        self, branch_id, branch_name, accounts, start_dt, end_dt,
    ) -> DayBookBranchRow:
        ids = [a.id for a in accounts]
        opening = await self._opening(accounts, start_dt)
        sums = await self.repo.period_category_sums(ids, start_dt, end_dt)
        money_in = sums.get(("sale_payment", "IN"), Decimal("0"))
        expenses = sums.get(("expense", "OUT"), Decimal("0"))
        handovers = sums.get(("handover", "OUT"), Decimal("0"))
        transfers_in = sums.get(("transfer", "IN"), Decimal("0"))
        transfers_out = sums.get(("transfer", "OUT"), Decimal("0"))
        total_in = sum((v for (_c, d), v in sums.items() if d == "IN"), Decimal("0"))
        total_out = sum((v for (_c, d), v in sums.items() if d == "OUT"), Decimal("0"))
        other_in = total_in - money_in - transfers_in
        other_out = total_out - expenses - handovers - transfers_out
        closing = opening + total_in - total_out
        return DayBookBranchRow(
            branch_id=branch_id, branch_name=branch_name, opening=opening, money_in=money_in,
            expenses=expenses, handovers=handovers, transfers_in=transfers_in,
            transfers_out=transfers_out, other_in=other_in, other_out=other_out, closing=closing,
        )

    async def account_statement_pdf(
        self, *, account_id: uuid.UUID, date_from: dt.date, date_to: dt.date,
        allowed_branch_ids: frozenset[uuid.UUID] | None = None,
    ) -> tuple[bytes, str]:
        from app.finance.pdf import build_statement_pdf

        stmt = await self.account_statement(
            account_id=account_id, date_from=date_from, date_to=date_to,
            allowed_branch_ids=allowed_branch_ids)
        return build_statement_pdf(stmt), f"statement-{stmt.account_name or account_id}"

    async def day_book_pdf(
        self, *, allowed_branch_ids: frozenset[uuid.UUID] | None, period: str, on: dt.date,
    ) -> tuple[bytes, str]:
        from app.finance.pdf import build_day_book_pdf

        book = await self.day_book(allowed_branch_ids=allowed_branch_ids, period=period, on=on)
        return build_day_book_pdf(book), f"day-book-{book.label}"
