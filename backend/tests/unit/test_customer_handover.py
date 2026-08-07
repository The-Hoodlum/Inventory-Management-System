"""Unit tests for the Customer Handover: the pure completion gate, the signature/balance
reconcile logic, the no-direct-stock-write guard, and a create->complete run over fakes
that proves completing a handover marks the unit delivered + stamps warranty + logs the
'delivered' event WITHOUT changing the terminal 'sold' sale status."""
from __future__ import annotations

import datetime as dt
import pathlib
import uuid
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import Boolean, Numeric
from sqlalchemy.types import DateTime

from app.customer_handovers.domain import status as S
from app.customer_handovers.schemas import HandoverCreate
from app.customer_handovers.service import CustomerHandoverService
from app.models import CustomerHandover, MotorcycleUnitEvent


# --------------------------------------------------------------------------- #
# Pure completion gate
# --------------------------------------------------------------------------- #
def _ready() -> SimpleNamespace:
    return SimpleNamespace(
        balance_zmw=Decimal("0"),
        quality_control_officer_signed=True,
        branch_manager_signed=True,
        customer_signature_name="John Banda",
        delivery_date=dt.date(2026, 8, 8),
    )


def test_completion_ready_has_no_errors():
    assert S.completion_errors(_ready()) == []


def test_completion_blocks_on_outstanding_balance():
    h = _ready()
    h.balance_zmw = Decimal("500")
    errs = S.completion_errors(h)
    assert any("balance" in e.lower() for e in errs)


def test_completion_requires_qc_manager_customer_and_date():
    h = SimpleNamespace(
        balance_zmw=Decimal("0"),
        quality_control_officer_signed=False,
        branch_manager_signed=False,
        customer_signature_name="",
        delivery_date=None,
    )
    errs = S.completion_errors(h)
    assert len(errs) == 4  # QC, manager, customer signature, delivery date


def test_status_set():
    assert S.STATUSES == {"DRAFT", "COMPLETED"}


# --------------------------------------------------------------------------- #
# Reconcile logic (static — works on any attribute bag)
# --------------------------------------------------------------------------- #
def test_reconcile_stamps_and_clears_approval_times():
    h = SimpleNamespace(customer_signature_name=None, customer_signed_at=None)
    for role in (
        "mechanic_inspector", "assembly_technician", "quality_control_officer",
        "salesperson", "branch_manager",
    ):
        setattr(h, f"{role}_signed", False)
        setattr(h, f"{role}_signed_at", None)
    h.quality_control_officer_signed = True

    CustomerHandoverService._reconcile_signatures(h)
    assert h.quality_control_officer_signed_at is not None
    assert h.branch_manager_signed_at is None   # still unsigned

    # Un-sign clears the timestamp.
    h.quality_control_officer_signed = False
    CustomerHandoverService._reconcile_signatures(h)
    assert h.quality_control_officer_signed_at is None


def test_reconcile_customer_signature_time_tracks_name():
    h = SimpleNamespace(customer_signature_name="John", customer_signed_at=None)
    for role in ("mechanic_inspector", "assembly_technician", "quality_control_officer", "salesperson", "branch_manager"):
        setattr(h, f"{role}_signed", False)
        setattr(h, f"{role}_signed_at", None)
    CustomerHandoverService._reconcile_signatures(h)
    assert h.customer_signed_at is not None


# --------------------------------------------------------------------------- #
# Package guard: a handover never writes stock.
# --------------------------------------------------------------------------- #
def test_handover_module_never_writes_stock_directly():
    pkg = pathlib.Path(S.__file__).resolve().parents[1]  # app/customer_handovers/
    offenders = []
    for path in pkg.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "qty_on_hand =" in text or "qty_on_hand=" in text or ".add_movement(" in text:
            offenders.append(path.name)
    assert offenders == [], f"handover must not write stock directly: {offenders}"


# --------------------------------------------------------------------------- #
# create -> complete over fakes
# --------------------------------------------------------------------------- #
def _normalize(obj) -> None:
    """Fill the DB-side defaults a real flush would (booleans False, non-null numerics 0,
    a uuid id, a created_at) so schema serialization works without a database."""
    table = getattr(obj, "__table__", None)
    if table is None:
        return
    for col in table.columns:
        if getattr(obj, col.name, None) is not None:
            continue
        if isinstance(col.type, Boolean):
            setattr(obj, col.name, False)
        elif isinstance(col.type, Numeric) and not col.nullable:
            setattr(obj, col.name, Decimal("0"))
        elif isinstance(col.type, DateTime) and not col.nullable:
            setattr(obj, col.name, dt.datetime.now(dt.UTC))
    if getattr(obj, "id", None) is None:
        obj.id = uuid.uuid4()


class _FakeSession:
    def __init__(self) -> None:
        self.objects: list = []

    def add(self, obj) -> None:
        self.objects.append(obj)

    async def flush(self) -> None:
        for o in self.objects:
            _normalize(o)


class _FakeAudit:
    def __init__(self) -> None:
        self.entries: list = []

    async def add(self, **kw) -> None:
        self.entries.append(kw)


class _FakeRepo:
    def __init__(self, session, invoice, unit, customer) -> None:
        self.session = session
        self._invoice = invoice
        self._unit = unit
        self._customer = customer
        self.handover: CustomerHandover | None = None

    async def number(self, tenant_id):
        return "HO-2026-00001"

    async def get_invoice(self, iid):
        return self._invoice

    async def get_unit(self, uid, *, lock=False):
        return self._unit

    async def get_customer(self, cid):
        return self._customer

    async def default_address(self, cid):
        return None

    async def order_salesperson(self, invoice):
        return invoice.created_by

    async def user_display(self, uid):
        return "Grace M" if uid else None

    async def unit_handover(self, tenant_id, unit_id):
        return self.handover

    async def unit_context(self, unit_id):
        return {
            "chassis_number": self._unit.chassis_number,
            "engine_number": self._unit.engine_number,
            "model_name": "TVS HLX 125",
            "colour_name": "Red",
        }

    async def branch_name(self, bid):
        return "Lusaka Main" if bid else None

    async def invoice_number(self, iid):
        return self._invoice.invoice_number if iid else None

    async def get(self, hid, *, lock=False):
        return self.handover


def _make_fixtures():
    invoice_id = uuid.uuid4()
    unit = SimpleNamespace(
        id=uuid.uuid4(), chassis_number="CH-ABC-123", engine_number="ENG-999",
        sold_ref=invoice_id, branch_id=uuid.uuid4(), customer_id=uuid.uuid4(),
        status="sold", warranty_start=None, version=0, delivered=False, delivered_at=None,
    )
    invoice = SimpleNamespace(
        id=invoice_id, invoice_number="INV-2026-0042", grand_total_zmw=Decimal("18500"),
        amount_paid=Decimal("18500"), customer_id=unit.customer_id,
        branch_id=unit.branch_id, sales_order_id=None, created_by=uuid.uuid4(),
    )
    customer = SimpleNamespace(
        name="John Banda", tax_number="123456/78/1", phone="0977000000", email="jb@example.com",
    )
    return invoice, unit, customer


async def test_create_autofills_from_invoice_and_unit():
    invoice, unit, customer = _make_fixtures()
    session = _FakeSession()
    repo = _FakeRepo(session, invoice, unit, customer)
    svc = CustomerHandoverService(repo, _FakeAudit())

    out = await svc.create(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        payload=HandoverCreate(invoice_id=invoice.id, unit_id=unit.id),
    )
    repo.handover = next(o for o in session.objects if isinstance(o, CustomerHandover))

    assert out.handover_no == "HO-2026-00001"
    assert out.status == "DRAFT"
    assert out.full_name == "John Banda"           # snapshot from customer master
    assert out.nrc_passport_no == "123456/78/1"
    assert out.chassis_number == "CH-ABC-123"      # resolved from the unit
    assert out.invoice_amount_zmw == Decimal("18500")
    assert out.balance_zmw == Decimal("0")         # fully paid
    assert out.delivery_date is not None           # defaulted to today


async def test_complete_marks_unit_delivered_and_stamps_warranty():
    invoice, unit, customer = _make_fixtures()
    session = _FakeSession()
    repo = _FakeRepo(session, invoice, unit, customer)
    audit = _FakeAudit()
    svc = CustomerHandoverService(repo, audit)

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    await svc.create(
        tenant_id=tenant_id, user_id=user_id,
        payload=HandoverCreate(
            invoice_id=invoice.id, unit_id=unit.id,
            quality_control_officer_signed=True, branch_manager_signed=True,
            customer_signature_name="John Banda",
        ),
    )
    repo.handover = next(o for o in session.objects if isinstance(o, CustomerHandover))

    out = await svc.complete(tenant_id=tenant_id, user_id=user_id, handover_id=repo.handover.id)

    assert out.status == "COMPLETED"
    assert out.warranty_start_date is not None
    # The unit is now an independent 'delivered' fact — sale status stays terminal 'sold'.
    assert unit.delivered is True
    assert unit.delivered_at is not None
    assert unit.warranty_start is not None
    assert unit.status == "sold"
    # A 'delivered' event was written to the unit ledger.
    events = [o for o in session.objects if isinstance(o, MotorcycleUnitEvent)]
    assert len(events) == 1
    assert events[0].event_type == "delivered"
    assert events[0].reference_type == "customer_handover"


async def test_cannot_complete_with_outstanding_balance():
    invoice, unit, customer = _make_fixtures()
    invoice.amount_paid = Decimal("10000")  # 8,500 outstanding
    session = _FakeSession()
    repo = _FakeRepo(session, invoice, unit, customer)
    svc = CustomerHandoverService(repo, _FakeAudit())

    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    await svc.create(
        tenant_id=tenant_id, user_id=user_id,
        payload=HandoverCreate(
            invoice_id=invoice.id, unit_id=unit.id,
            quality_control_officer_signed=True, branch_manager_signed=True,
            customer_signature_name="John Banda",
        ),
    )
    repo.handover = next(o for o in session.objects if isinstance(o, CustomerHandover))

    from app.core.exceptions import BusinessRuleError

    try:
        await svc.complete(tenant_id=tenant_id, user_id=user_id, handover_id=repo.handover.id)
        raise AssertionError("expected completion to be blocked")
    except BusinessRuleError as e:
        assert unit.delivered is False   # unchanged
        assert e.details and "reasons" in e.details
