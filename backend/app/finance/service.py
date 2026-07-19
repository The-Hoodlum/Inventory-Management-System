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
    NotFoundError,
    PermissionDeniedError,
)
from app.finance.repository import FinanceRepository
from app.finance.schemas import (
    AccountBalanceOut,
    AccountCreate,
    AccountOut,
    AccountUpdate,
    PaymentMappingOut,
)
from app.models import AccountMovement, FinancialAccount
from app.models.finance import (
    ACCOUNT_TYPES,
    DIRECTION_IN,
    DIRECTION_OUT,
    PAYMENT_METHODS,
)
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
