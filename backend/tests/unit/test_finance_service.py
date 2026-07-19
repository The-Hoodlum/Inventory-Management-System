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
from app.finance.schemas import (
    AccountCreate,
    AccountUpdate,
    ExpenseCreate,
    HandoverCreate,
    TransferCreate,
)
from app.finance.service import FinanceService, derive_balance
from app.models import (
    AccountMovement,
    AccountTransfer,
    CashHandover,
    Expense,
    ExpenseCategory,
    FinancePaymentAccountMap,
    FinancialAccount,
)
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
        self.mappings: list[FinancePaymentAccountMap] = []
        self.categories: dict[uuid.UUID, ExpenseCategory] = {}
        self.expenses: dict[uuid.UUID, Expense] = {}
        self.attachments: dict[uuid.UUID, object] = {}
        self.transfers: dict[uuid.UUID, AccountTransfer] = {}
        self.handovers: dict[uuid.UUID, CashHandover] = {}
        self.handover_attachments: dict[uuid.UUID, object] = {}

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

    async def unreversed_for_reference(self, reference_type, reference_id):
        reversed_ids = {m.reversal_of for m in self.movements if m.reversal_of is not None}
        return [
            m for m in self.movements
            if m.reference_type == reference_type and m.reference_id == reference_id
            and m.reversal_of is None and m.id not in reversed_ids
        ]

    async def mapping_for(self, branch_id, method):
        return next((m for m in self.mappings if m.branch_id == branch_id and m.method == method), None)

    async def branch_has_mappings(self, branch_id):
        return any(m.branch_id == branch_id for m in self.mappings)

    async def upsert_mapping(self, *, tenant_id, branch_id, method, account_id):
        row = FinancePaymentAccountMap(tenant_id=tenant_id, branch_id=branch_id, method=method, account_id=account_id)
        row.id = uuid.uuid4()
        self.mappings.append(row)
        return row

    # categories
    async def add_category(self, category):
        if category.id is None:
            category.id = uuid.uuid4()
        if category.is_active is None:
            category.is_active = True
        self.categories[category.id] = category
        return category

    async def get_category(self, category_id):
        return self.categories.get(category_id)

    async def category_by_name(self, name):
        return next((c for c in self.categories.values() if c.name.lower() == name.lower()), None)

    async def list_categories(self, *, active_only=False):
        return [c for c in self.categories.values() if not active_only or c.is_active]

    async def category_name_map(self):
        return {cid: c.name for cid, c in self.categories.items()}

    # expenses
    async def add_expense(self, expense):
        if expense.id is None:
            expense.id = uuid.uuid4()
        expense.created_at = dt.datetime.now(dt.UTC)
        if expense.status is None:
            expense.status = "recorded"
        self.expenses[expense.id] = expense
        return expense

    async def get_expense(self, expense_id):
        return self.expenses.get(expense_id)

    async def list_expenses(self, *, branch_ids, **f):
        out = list(self.expenses.values())
        if branch_ids is not None:
            out = [e for e in out if e.branch_id in branch_ids]
        return out

    async def get_attachment(self, expense_id):
        return self.attachments.get(expense_id)

    async def upsert_attachment(self, **kwargs):
        self.attachments[kwargs["expense_id"]] = kwargs
        return kwargs

    async def attachment_expense_ids(self, expense_ids):
        return {eid for eid in expense_ids if eid in self.attachments}

    # transfers
    async def add_transfer(self, transfer):
        if transfer.id is None:
            transfer.id = uuid.uuid4()
        transfer.created_at = dt.datetime.now(dt.UTC)
        if transfer.status is None:
            transfer.status = "completed"
        if transfer.occurred_at is None:
            transfer.occurred_at = transfer.created_at
        self.transfers[transfer.id] = transfer
        return transfer

    async def get_transfer(self, transfer_id):
        return self.transfers.get(transfer_id)

    async def list_transfers(self, *, account_ids):
        return list(self.transfers.values())

    # handovers
    async def add_handover(self, handover):
        if handover.id is None:
            handover.id = uuid.uuid4()
        handover.created_at = dt.datetime.now(dt.UTC)
        if handover.status is None:
            handover.status = "PENDING_CONFIRMATION"
        if handover.handover_datetime is None:
            handover.handover_datetime = handover.created_at
        self.handovers[handover.id] = handover
        return handover

    async def get_handover(self, handover_id):
        return self.handovers.get(handover_id)

    async def list_handovers(self, *, branch_ids, **f):
        out = list(self.handovers.values())
        if branch_ids is not None:
            out = [h for h in out if h.branch_id in branch_ids]
        return out

    async def get_handover_attachment(self, handover_id):
        return self.handover_attachments.get(handover_id)

    async def upsert_handover_attachment(self, **kwargs):
        self.handover_attachments[kwargs["handover_id"]] = kwargs
        return kwargs


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


# ---------------------- money-in from invoice payments -------------------- #
async def _account(svc, name, typ, branch):
    return await svc.create_account(
        tenant_id=TENANT, user_id=USER, data=AccountCreate(name=name, type=typ, branch_id=branch))


async def test_money_in_dormant_without_mappings():
    svc = _svc()
    cash = await _account(svc, "Cash", "CASH", BRANCH_A)
    inv = uuid.uuid4()
    posted = await svc.post_invoice_payments(
        tenant_id=TENANT, user_id=USER, branch_id=BRANCH_A, invoice_id=inv,
        invoice_number="INV-1", lines=[("cash", Decimal("300"))])
    assert posted == []  # branch has no mappings -> nothing posted (sales untouched)
    assert await svc.account_balance(cash.id) == Decimal("0")


async def test_cash_payment_posts_in_to_mapped_account():
    svc = _svc()
    cash = await _account(svc, "Cash", "CASH", BRANCH_A)
    await svc.set_mapping(tenant_id=TENANT, user_id=USER, branch_id=BRANCH_A, method="cash", account_id=cash.id)
    inv = uuid.uuid4()
    posted = await svc.post_invoice_payments(
        tenant_id=TENANT, user_id=USER, branch_id=BRANCH_A, invoice_id=inv,
        invoice_number="INV-1", lines=[("cash", Decimal("300"))])
    assert len(posted) == 1 and posted[0].direction == "IN"
    assert await svc.account_balance(cash.id) == Decimal("300")


async def test_split_payment_posts_one_per_method_to_correct_accounts():
    svc = _svc()
    cash = await _account(svc, "Cash", "CASH", BRANCH_A)
    bank = await _account(svc, "Bank", "BANK", BRANCH_A)
    await svc.set_mapping(tenant_id=TENANT, user_id=USER, branch_id=BRANCH_A, method="cash", account_id=cash.id)
    await svc.set_mapping(tenant_id=TENANT, user_id=USER, branch_id=BRANCH_A, method="bank_transfer", account_id=bank.id)
    inv = uuid.uuid4()
    lines = [("cash", Decimal("120")), ("bank_transfer", Decimal("80"))]
    posted = await svc.post_invoice_payments(
        tenant_id=TENANT, user_id=USER, branch_id=BRANCH_A, invoice_id=inv,
        invoice_number="INV-2", lines=lines)
    assert len(posted) == 2  # one movement per line
    assert await svc.account_balance(cash.id) == Decimal("120")
    assert await svc.account_balance(bank.id) == Decimal("80")
    # Reconciles EXACTLY with the payment total — no double-count, no second source.
    total_in = sum(m.amount for m in posted)
    assert total_in == sum(amt for _m, amt in lines) == Decimal("200")


async def test_unmapped_method_on_active_branch_fails_loudly():
    svc = _svc()
    cash = await _account(svc, "Cash", "CASH", BRANCH_A)
    await svc.set_mapping(tenant_id=TENANT, user_id=USER, branch_id=BRANCH_A, method="cash", account_id=cash.id)
    inv = uuid.uuid4()
    # The branch is finance-active (has a cash mapping) but 'mobile_money' is unmapped —
    # must fail loudly rather than silently dropping the money.
    with pytest.raises(BusinessRuleError):
        await svc.post_invoice_payments(
            tenant_id=TENANT, user_id=USER, branch_id=BRANCH_A, invoice_id=inv,
            invoice_number="INV-3", lines=[("mobile_money", Decimal("50"))])


async def test_void_reverses_payment_movements_keeping_originals():
    svc = _svc()
    cash = await _account(svc, "Cash", "CASH", BRANCH_A)
    await svc.set_mapping(tenant_id=TENANT, user_id=USER, branch_id=BRANCH_A, method="cash", account_id=cash.id)
    inv = uuid.uuid4()
    await svc.post_invoice_payments(
        tenant_id=TENANT, user_id=USER, branch_id=BRANCH_A, invoice_id=inv,
        invoice_number="INV-4", lines=[("cash", Decimal("500"))])
    assert await svc.account_balance(cash.id) == Decimal("500")
    reversals = await svc.reverse_reference(
        tenant_id=TENANT, user_id=USER, reference_type="invoice_payment",
        reference_id=inv, reason="voided")
    assert len(reversals) == 1 and reversals[0].direction == "OUT"
    assert await svc.account_balance(cash.id) == Decimal("0")  # money-in reversed
    # A second void attempt reverses nothing (originals already cancelled; none deleted).
    again = await svc.reverse_reference(
        tenant_id=TENANT, user_id=USER, reference_type="invoice_payment",
        reference_id=inv, reason="voided again")
    assert again == []


async def test_mapping_rejects_foreign_branch_account():
    svc = _svc()
    bank_b = await _account(svc, "Bank B", "BANK", BRANCH_B)
    # Mapping branch A's method to an account that belongs to branch B is rejected.
    with pytest.raises(BusinessRuleError):
        await svc.set_mapping(tenant_id=TENANT, user_id=USER, branch_id=BRANCH_A,
                              method="bank_transfer", account_id=bank_b.id)


# -------------------------------- expenses -------------------------------- #
async def test_expense_posts_out_reducing_balance_by_exactly_amount():
    svc = _svc()
    cash = await svc.create_account(
        tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="Cash", type="CASH", branch_id=BRANCH_A, opening_balance=Decimal("1000")))
    cat = await svc.create_category(tenant_id=TENANT, user_id=USER, name="Fuel")
    exp = await svc.create_expense(
        tenant_id=TENANT, user_id=USER,
        data=ExpenseCreate(account_id=cash.id, amount=Decimal("300"),
                           expense_date=dt.date(2026, 7, 19), category_id=cat.id, payee="Total"))
    assert exp.status == "recorded"
    assert await svc.account_balance(cash.id) == Decimal("700")  # 1000 - 300


async def test_void_expense_restores_balance_and_is_idempotent():
    svc = _svc()
    cash = await svc.create_account(
        tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="Cash", type="CASH", branch_id=BRANCH_A, opening_balance=Decimal("500")))
    exp = await svc.create_expense(
        tenant_id=TENANT, user_id=USER,
        data=ExpenseCreate(account_id=cash.id, amount=Decimal("200"), expense_date=dt.date(2026, 7, 19)))
    assert await svc.account_balance(cash.id) == Decimal("300")
    voided = await svc.void_expense(tenant_id=TENANT, user_id=USER, expense_id=exp.id, reason="wrong")
    assert voided.status == "voided"
    assert await svc.account_balance(cash.id) == Decimal("500")  # OUT reversed, not deleted
    with pytest.raises(BusinessRuleError):
        await svc.void_expense(tenant_id=TENANT, user_id=USER, expense_id=exp.id, reason="again")


async def test_expense_requires_a_branch():
    svc = _svc()
    custody = await svc.create_account(
        tenant_id=TENANT, user_id=USER, data=AccountCreate(name="HQ", type="CUSTODY", branch_id=None))
    # Tenant-wide account + no branch given -> can't scope the expense.
    with pytest.raises(BusinessRuleError):
        await svc.create_expense(
            tenant_id=TENANT, user_id=USER,
            data=ExpenseCreate(account_id=custody.id, amount=Decimal("50"), expense_date=dt.date(2026, 7, 19)))


async def test_expense_branch_scoping_blocks_foreign_account():
    svc = _svc()
    cash_b = await svc.create_account(
        tenant_id=TENANT, user_id=USER, data=AccountCreate(name="Cash B", type="CASH", branch_id=BRANCH_B))
    with pytest.raises(PermissionDeniedError):
        await svc.create_expense(
            tenant_id=TENANT, user_id=USER,
            data=ExpenseCreate(account_id=cash_b.id, amount=Decimal("50"), expense_date=dt.date(2026, 7, 19)),
            allowed_branch_ids=frozenset({BRANCH_A}))


async def test_duplicate_category_rejected():
    from app.core.exceptions import ConflictError
    svc = _svc()
    await svc.create_category(tenant_id=TENANT, user_id=USER, name="Rent")
    with pytest.raises(ConflictError):
        await svc.create_category(tenant_id=TENANT, user_id=USER, name="rent")


# ------------------------------- transfers -------------------------------- #
async def test_transfer_posts_paired_out_in_net_zero():
    svc = _svc()
    cash = await svc.create_account(tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="Cash", type="CASH", branch_id=BRANCH_A, opening_balance=Decimal("1000")))
    bank = await svc.create_account(tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="Bank", type="BANK", branch_id=BRANCH_A, opening_balance=Decimal("0")))
    await svc.create_transfer(tenant_id=TENANT, user_id=USER,
        data=TransferCreate(from_account_id=cash.id, to_account_id=bank.id, amount=Decimal("400")))
    assert await svc.account_balance(cash.id) == Decimal("600")
    assert await svc.account_balance(bank.id) == Decimal("400")
    # Net across the two accounts is unchanged (money only moved).
    assert await svc.account_balance(cash.id) + await svc.account_balance(bank.id) == Decimal("1000")


async def test_transfer_same_account_rejected_and_reverse_nets_back():
    svc = _svc()
    cash = await svc.create_account(tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="Cash", type="CASH", branch_id=BRANCH_A, opening_balance=Decimal("500")))
    bank = await svc.create_account(tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="Bank", type="BANK", branch_id=BRANCH_A))
    with pytest.raises(BusinessRuleError):
        await svc.create_transfer(tenant_id=TENANT, user_id=USER,
            data=TransferCreate(from_account_id=cash.id, to_account_id=cash.id, amount=Decimal("10")))
    t = await svc.create_transfer(tenant_id=TENANT, user_id=USER,
        data=TransferCreate(from_account_id=cash.id, to_account_id=bank.id, amount=Decimal("200")))
    await svc.reverse_transfer(tenant_id=TENANT, user_id=USER, transfer_id=t.id, reason="mistake")
    assert await svc.account_balance(cash.id) == Decimal("500")
    assert await svc.account_balance(bank.id) == Decimal("0")


# ------------------------------- handovers -------------------------------- #
async def _cash_and_custody(svc):
    cash = await svc.create_account(tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="Till", type="CASH", branch_id=BRANCH_A, opening_balance=Decimal("1000")))
    custody = await svc.create_account(tenant_id=TENANT, user_id=USER,
        data=AccountCreate(name="HQ custody", type="CUSTODY", branch_id=None))
    return cash, custody


async def test_handover_out_on_record_not_counted_in_both():
    svc = _svc()
    cash, custody = await _cash_and_custody(svc)
    h = await svc.create_handover(tenant_id=TENANT, user_id=USER,
        data=HandoverCreate(from_account_id=cash.id, to_account_id=custody.id, branch_id=BRANCH_A,
                            amount=Decimal("600"), received_by_name="Grace (accountant)"))
    assert h.status == "PENDING_CONFIRMATION"
    # Branch cash dropped by exactly the amount (money left the branch)...
    assert await svc.account_balance(cash.id) == Decimal("400")
    # ...but the destination has NOT been credited yet — not counted in both (in transit).
    assert await svc.account_balance(custody.id) == Decimal("0")


async def test_handover_confirm_matching_posts_in():
    svc = _svc()
    cash, custody = await _cash_and_custody(svc)
    h = await svc.create_handover(tenant_id=TENANT, user_id=USER,
        data=HandoverCreate(from_account_id=cash.id, to_account_id=custody.id, branch_id=BRANCH_A,
                            amount=Decimal("600"), received_by_name="Grace"))
    out = await svc.confirm_handover(tenant_id=TENANT, user_id=USER, handover_id=h.id,
                                     confirmed_amount=Decimal("600"))
    assert out.status == "CONFIRMED"
    assert await svc.account_balance(custody.id) == Decimal("600")  # IN now posted


async def test_short_handover_requires_reason_and_does_not_absorb_shortfall():
    svc = _svc()
    cash, custody = await _cash_and_custody(svc)
    h = await svc.create_handover(tenant_id=TENANT, user_id=USER,
        data=HandoverCreate(from_account_id=cash.id, to_account_id=custody.id, branch_id=BRANCH_A,
                            amount=Decimal("600"), received_by_name="Grace"))
    # A mismatch with NO reason is rejected (a shortfall is never silently absorbed).
    with pytest.raises(BusinessRuleError):
        await svc.confirm_handover(tenant_id=TENANT, user_id=USER, handover_id=h.id,
                                   confirmed_amount=Decimal("550"))
    out = await svc.confirm_handover(tenant_id=TENANT, user_id=USER, handover_id=h.id,
                                     confirmed_amount=Decimal("550"), discrepancy_reason="short by 50")
    assert out.status == "DISPUTED"
    assert out.discrepancy_amount == Decimal("50")
    # Branch already lost the full 600; only the 550 actually received is credited — the
    # 50 shortfall is surfaced, not absorbed.
    assert await svc.account_balance(cash.id) == Decimal("400")
    assert await svc.account_balance(custody.id) == Decimal("550")


async def test_handover_reverse_returns_cash_to_branch():
    svc = _svc()
    cash, custody = await _cash_and_custody(svc)
    h = await svc.create_handover(tenant_id=TENANT, user_id=USER,
        data=HandoverCreate(from_account_id=cash.id, to_account_id=custody.id, branch_id=BRANCH_A,
                            amount=Decimal("600"), received_by_name="Grace"))
    await svc.reverse_handover(tenant_id=TENANT, user_id=USER, handover_id=h.id, reason="cancelled")
    # The reversing IN restores the branch cash; nothing left in transit.
    assert await svc.account_balance(cash.id) == Decimal("1000")
