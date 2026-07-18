"""Finance service — the derived-balance invariant and its guardrails.

The guarantees under test (mirroring the stock ledger's discipline):
- balance is DERIVED (opening + sum(IN) - sum(OUT)); there is no field/endpoint to set it;
- posting a movement changes the derived balance by exactly the amount + direction;
- a reversal nets to zero and never deletes the original;
- a non-positive amount is rejected (direction carries the sign);
- a CASH/BANK/MOBILE_MONEY account requires a branch; CUSTODY may be tenant-wide;
- branch scoping is enforced: a scoped user can't create in / read a foreign branch.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessRuleError, PermissionDeniedError
from app.finance.schemas import AccountCreate, AccountUpdate
from app.finance.service import FinanceService, derive_balance
from app.models import AccountMovement, FinancialAccount
from tests.conftest import FakeAuditRepo

TENANT = uuid.uuid4()
USER = uuid.uuid4()
BRANCH_A = uuid.uuid4()
BRANCH_B = uuid.uuid4()


class _FakeFinanceRepo:
    """In-memory stand-in for FinanceRepository (no DB): stores accounts + movements and
    computes the sums the service derives balances from."""

    def __init__(self) -> None:
        self.accounts: dict[uuid.UUID, FinancialAccount] = {}
        self.movements: list[AccountMovement] = []

        class _S:
            async def flush(self_inner) -> None:
                return None

        self.session = _S()

    async def add_account(self, account: FinancialAccount) -> FinancialAccount:
        if account.id is None:
            account.id = uuid.uuid4()
        now = dt.datetime.now(dt.UTC)
        account.created_at = now
        account.updated_at = now
        if account.is_active is None:
            account.is_active = True
        self.accounts[account.id] = account
        return account

    async def get_account(self, account_id):
        return self.accounts.get(account_id)

    async def get_account_for_update(self, account_id):
        return self.accounts.get(account_id)

    async def list_accounts(self, *, branch_ids, active_only=False, type=None):
        out = []
        for a in self.accounts.values():
            if branch_ids is not None and a.branch_id is not None and a.branch_id not in branch_ids:
                continue
            if active_only and not a.is_active:
                continue
            if type is not None and a.type != type:
                continue
            out.append(a)
        return out

    async def branch_name_map(self):
        return {BRANCH_A: "Lusaka", BRANCH_B: "Solwezi"}

    async def add_movement(self, **kwargs):
        mv = AccountMovement(**kwargs)
        mv.id = uuid.uuid4()
        mv.created_at = dt.datetime.now(dt.UTC)
        if mv.occurred_at is None:
            mv.occurred_at = mv.created_at
        self.movements.append(mv)
        return mv

    def _sums(self, account_id):
        tin = sum((m.amount for m in self.movements if m.account_id == account_id and m.direction == "IN"), Decimal("0"))
        tout = sum((m.amount for m in self.movements if m.account_id == account_id and m.direction == "OUT"), Decimal("0"))
        return tin, tout

    async def movement_sums(self, account_id):
        return self._sums(account_id)

    async def sums_by_account(self, account_ids):
        return {aid: self._sums(aid) for aid in account_ids}

    async def get_movement(self, movement_id):
        return next((m for m in self.movements if m.id == movement_id), None)


def _svc():
    return FinanceService(_FakeFinanceRepo(), FakeAuditRepo())


# ------------------------------------------------------------------------- #
def test_derive_balance_formula():
    assert derive_balance(Decimal("100"), Decimal("50"), Decimal("30")) == Decimal("120")
    assert derive_balance(Decimal("0"), Decimal("0"), Decimal("0")) == Decimal("0")


def test_balance_is_not_a_settable_field():
    # No schema exposes a balance/opening to be written after creation — the balance can
    # only ever be derived, never set/edited/zeroed via an endpoint.
    assert "balance" not in AccountUpdate.model_fields
    assert "opening_balance" not in AccountUpdate.model_fields


async def test_cash_account_requires_a_branch():
    svc = _svc()
    with pytest.raises(BusinessRuleError):
        await svc.create_account(
            tenant_id=TENANT, user_id=USER,
            data=AccountCreate(name="Cash", type="CASH", branch_id=None),
        )


async def test_custody_account_may_be_tenant_wide():
    svc = _svc()
    acct = await svc.create_account(
        tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="HQ custody", type="CUSTODY", branch_id=None),
    )
    assert acct.branch_id is None
    # A fresh account with no movements has balance == opening.
    bal = await svc.get_account(account_id=acct.id)
    assert bal.balance == Decimal("0")


async def test_posting_movements_moves_the_derived_balance():
    svc = _svc()
    acct = await svc.create_account(
        tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="Cash", type="CASH", branch_id=BRANCH_A, opening_balance=Decimal("100")),
    )
    await svc.post_movement(tenant_id=TENANT, user_id=USER, account_id=acct.id,
                            direction="IN", amount=Decimal("250"), category="sale_payment")
    await svc.post_movement(tenant_id=TENANT, user_id=USER, account_id=acct.id,
                            direction="OUT", amount=Decimal("40"), category="expense")
    assert await svc.account_balance(acct.id) == Decimal("310")  # 100 + 250 - 40


async def test_reversal_nets_to_zero_and_keeps_original():
    svc = _svc()
    acct = await svc.create_account(
        tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="Cash", type="CASH", branch_id=BRANCH_A),
    )
    mv = await svc.post_movement(tenant_id=TENANT, user_id=USER, account_id=acct.id,
                                 direction="IN", amount=Decimal("500"))
    assert await svc.account_balance(acct.id) == Decimal("500")
    rev = await svc.reverse_movement(tenant_id=TENANT, user_id=USER, movement_id=mv.id, reason="mistake")
    # Original preserved; reversal points back at it; balance self-corrects to zero.
    assert rev.reversal_of == mv.id
    assert rev.direction == "OUT"
    assert await svc.account_balance(acct.id) == Decimal("0")
    assert await svc.repo.get_movement(mv.id) is not None  # never deleted


async def test_non_positive_amount_rejected():
    svc = _svc()
    acct = await svc.create_account(
        tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="Cash", type="CASH", branch_id=BRANCH_A),
    )
    for bad in (Decimal("0"), Decimal("-5")):
        with pytest.raises(BusinessRuleError):
            await svc.post_movement(tenant_id=TENANT, user_id=USER, account_id=acct.id,
                                    direction="IN", amount=bad)


async def test_branch_scoping_blocks_foreign_branch():
    svc = _svc()
    allowed = frozenset({BRANCH_A})
    # Cannot create an account in a branch that isn't theirs.
    with pytest.raises(PermissionDeniedError):
        await svc.create_account(
            tenant_id=TENANT, user_id=USER,
            data=AccountCreate(name="Cash B", type="CASH", branch_id=BRANCH_B),
            allowed_branch_ids=allowed,
        )
    # Cannot read an account in a foreign branch.
    foreign = await svc.create_account(
        tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="Cash B", type="CASH", branch_id=BRANCH_B),
    )
    with pytest.raises(PermissionDeniedError):
        await svc.get_account(account_id=foreign.id, allowed_branch_ids=allowed)


async def test_scoped_user_sees_tenant_wide_custody():
    svc = _svc()
    custody = await svc.create_account(
        tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="HQ custody", type="CUSTODY", branch_id=None),
    )
    # A branch-scoped user can still see (and later hand over to) tenant-wide custody.
    out = await svc.get_account(account_id=custody.id, allowed_branch_ids=frozenset({BRANCH_A}))
    assert out.id == custody.id
