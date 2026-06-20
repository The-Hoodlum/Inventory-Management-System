"""Module-level integration tests for ReorderService using in-memory fakes.

No database: the repositories are faked, so these exercise the orchestration,
persistence calls, grouping, totals, and auditing without infrastructure. PO
creation is delegated to a fake ProcurementService (the single creation path).
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.reorder.schemas import GeneratePurchaseOrdersRequest, RunReorderRequest
from app.reorder.service import ReorderService


def _product(*, sku, name, supplier_id, upc=10, moq=0, lead=7, cost="2.5",
             reorder_point=None, safety_stock=None, commodity_tags=None,
             country_of_origin=None, criticality="medium", supplier_dependency=None,
             demand_type=None, substitutability=None):
    return SimpleNamespace(
        id=uuid.uuid4(), sku=sku, name=name, primary_supplier_id=supplier_id,
        units_per_carton=upc, moq=moq, lead_time_days=lead, cost_price=Decimal(cost),
        reorder_point=reorder_point, safety_stock=safety_stock,
        status="active", deleted_at=None, category_id=None,
        # Product Intelligence Profile (defaults are neutral → no behaviour change)
        commodity_tags=commodity_tags or [], country_of_origin=country_of_origin,
        transport_mode=None, criticality=criticality,
        supplier_dependency=supplier_dependency, demand_type=demand_type,
        substitutability=substitutability, volume_per_carton=None, weight_per_carton=None,
    )


class FakeReorderRepo:
    def __init__(self, *, products, warehouses, demand=None, stock=None, on_order=None,
                 suppliers=None, supplier_products=None):
        self.products = products
        self.warehouses = warehouses
        self.demand = demand or {}
        self.stock = stock or {}
        self.on_order = on_order or {}
        self.suppliers = suppliers or {}
        self.supplier_products = supplier_products or {}
        self.products_by_id = {p.id: p for p in products}
        self.saved: list = []
        self.recs_by_id: dict[uuid.UUID, SimpleNamespace] = {}

    async def list_warehouses(self, *, warehouse_id=None):
        if warehouse_id:
            return [w for w in self.warehouses if w.id == warehouse_id]
        return list(self.warehouses)

    async def list_products(self, *, category_id=None, supplier_id=None):
        items = list(self.products)
        if supplier_id:
            items = [p for p in items if p.primary_supplier_id == supplier_id]
        return items

    async def demand_aggregates(self, product_id, warehouse_id, start_date):
        return self.demand.get((product_id, warehouse_id), (Decimal(0), Decimal(0), 0))

    async def stock_position(self, product_id, warehouse_id):
        return self.stock.get((product_id, warehouse_id), (Decimal(0), Decimal(0), Decimal(0)))

    async def on_order_qty(self, product_id, warehouse_id):
        return self.on_order.get((product_id, warehouse_id), Decimal(0))

    async def get_supplier(self, supplier_id):
        return self.suppliers.get(supplier_id)

    async def get_supplier_product(self, supplier_id, product_id):
        return self.supplier_products.get((supplier_id, product_id))

    async def get_product(self, product_id):
        return self.products_by_id.get(product_id)

    async def save_recommendation(self, **fields):
        rec = SimpleNamespace(id=uuid.uuid4(), **fields)
        self.saved.append(rec)
        self.recs_by_id[rec.id] = rec
        return rec

    async def get_recommendations_by_ids(self, ids):
        return [self.recs_by_id[i] for i in ids if i in self.recs_by_id]

    async def list_recommendations(self, **kwargs):
        return list(self.saved), len(self.saved)


class FakeProcurementService:
    """Stands in for the real PO creation path: computes totals from the lines
    and records each call so the test can assert delegation."""

    def __init__(self):
        self._seq = 0
        self.created: list = []

    async def create_po(self, *, tenant_id, user_id, data, ip=None):
        self._seq += 1
        lines = []
        subtotal = Decimal(0)
        for ln in data.lines:
            line_total = Decimal(ln.ordered_qty) * Decimal(ln.unit_cost)
            subtotal += line_total
            lines.append(SimpleNamespace(
                id=uuid.uuid4(), product_id=ln.product_id,
                ordered_qty=Decimal(ln.ordered_qty), ordered_cartons=ln.ordered_cartons,
                unit_cost=Decimal(ln.unit_cost), line_total=line_total, received_qty=Decimal(0),
            ))
        po = SimpleNamespace(
            id=uuid.uuid4(), po_number=f"PO-TEST-{self._seq:05d}",
            supplier_id=data.supplier_id, warehouse_id=data.warehouse_id,
            status="draft", currency="USD", fx_rate=Decimal(1),
            subtotal=subtotal, tax=Decimal(0), total=subtotal,
            notes=data.notes, expected_date=data.expected_date,
            created_at=dt.datetime.now(dt.UTC), lines=lines,
        )
        self.created.append(po)
        return po


def _service(reorder_repo, fake_audit_repo) -> ReorderService:
    return ReorderService(reorder_repo, FakeProcurementService(), fake_audit_repo)


# --------------------------------- run --------------------------------- #
async def test_run_persists_actionable_recommendation_and_audits(fake_audit_repo):
    supplier_id = uuid.uuid4()
    wh = SimpleNamespace(id=uuid.uuid4(), code="W1", is_active=True)
    product = _product(sku="SKU1", name="Prod1", supplier_id=supplier_id, upc=10, lead=7)
    repo = FakeReorderRepo(
        products=[product],
        warehouses=[wh],
        demand={(product.id, wh.id): (Decimal(180), Decimal(0), 90)},  # avg/day = 2
        stock={(product.id, wh.id): (Decimal(5), Decimal(0), Decimal(0))},
        suppliers={supplier_id: SimpleNamespace(id=supplier_id, currency="USD")},
    )
    svc = _service(repo, fake_audit_repo)

    resp = await svc.run(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=RunReorderRequest(window_days=90), ip="1.2.3.4",
    )

    # ADD=2, safety=2*7=14, ROP=2*7+14=28, S=28, IP=5, gap=23 -> ceil(23/10)=3 -> 30 units
    assert resp.to_order == 1
    assert len(resp.items) == 1
    item = resp.items[0]
    assert item.should_reorder is True
    assert item.recommended_qty == Decimal("30")
    assert item.recommended_cartons == 3
    assert item.recommendation_id is not None

    assert len(repo.saved) == 1
    assert repo.saved[0].recommended_qty == Decimal("30")
    assert repo.saved[0].status == "pending"
    assert any(e["action"] == "reorder.run" for e in fake_audit_repo.entries)


async def test_run_healthy_stock_persists_nothing(fake_audit_repo):
    supplier_id = uuid.uuid4()
    wh = SimpleNamespace(id=uuid.uuid4(), code="W1", is_active=True)
    product = _product(sku="SKU1", name="Prod1", supplier_id=supplier_id)
    repo = FakeReorderRepo(
        products=[product],
        warehouses=[wh],
        demand={(product.id, wh.id): (Decimal(180), Decimal(0), 90)},
        stock={(product.id, wh.id): (Decimal(500), Decimal(0), Decimal(0))},  # well stocked
        suppliers={supplier_id: SimpleNamespace(id=supplier_id, currency="USD")},
    )
    svc = _service(repo, fake_audit_repo)

    resp = await svc.run(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=RunReorderRequest(window_days=90), ip=None,
    )
    assert resp.to_order == 0
    assert resp.items == []
    assert repo.saved == []


class _FakeDemandRepo:
    """Returns a steady daily series for forecast-driven reorder mode."""

    def __init__(self, qty_per_day: str, days: int = 90):
        self.qty = Decimal(qty_per_day)
        self.days = days

    async def daily_series(self, *, product_id, warehouse_id, start_date, end_date):
        from app.forecast.domain.models import DemandPoint
        return [
            DemandPoint(day=end_date - dt.timedelta(days=i), quantity=self.qty)
            for i in range(self.days)
        ]


async def test_run_forecast_mode_matches_steady_historical(fake_audit_repo):
    # With steady demand of 2/day, forecast-driven mode should reach the same
    # recommendation as historical mode (proves the forecast branch + wiring).
    supplier_id = uuid.uuid4()
    wh = SimpleNamespace(id=uuid.uuid4(), code="W1", is_active=True)
    product = _product(sku="SKU1", name="Prod1", supplier_id=supplier_id, upc=10, lead=7)
    repo = FakeReorderRepo(
        products=[product],
        warehouses=[wh],
        stock={(product.id, wh.id): (Decimal(5), Decimal(0), Decimal(0))},
        suppliers={supplier_id: SimpleNamespace(id=supplier_id, currency="USD")},
    )
    svc = ReorderService(repo, FakeProcurementService(), fake_audit_repo, _FakeDemandRepo("2"))

    resp = await svc.run(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=RunReorderRequest(window_days=90, demand_mode="forecast"), ip=None,
    )
    assert resp.to_order == 1
    assert resp.items[0].recommended_qty == Decimal("30")  # same as historical SKU1 case
    assert resp.items[0].avg_daily_demand == Decimal("2.0000")


async def test_run_only_below_rop_false_returns_all_evaluated(fake_audit_repo):
    supplier_id = uuid.uuid4()
    wh = SimpleNamespace(id=uuid.uuid4(), code="W1", is_active=True)
    product = _product(sku="SKU1", name="Prod1", supplier_id=supplier_id)
    repo = FakeReorderRepo(
        products=[product],
        warehouses=[wh],
        demand={(product.id, wh.id): (Decimal(180), Decimal(0), 90)},
        stock={(product.id, wh.id): (Decimal(500), Decimal(0), Decimal(0))},
        suppliers={supplier_id: SimpleNamespace(id=supplier_id, currency="USD")},
    )
    svc = _service(repo, fake_audit_repo)

    resp = await svc.run(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=RunReorderRequest(window_days=90, only_below_rop=False), ip=None,
    )
    assert resp.evaluated == 1
    assert len(resp.items) == 1
    assert resp.items[0].should_reorder is False


# --------------------------- purchase orders --------------------------- #
async def test_create_purchase_orders_groups_totals_and_marks_ordered(fake_audit_repo):
    supplier_id = uuid.uuid4()
    wh_id = uuid.uuid4()
    p1 = _product(sku="P1", name="Prod1", supplier_id=supplier_id, cost="2.5")
    p2 = _product(sku="P2", name="Prod2", supplier_id=supplier_id, cost="1.2")
    p3 = _product(sku="P3", name="Prod3", supplier_id=None)

    repo = FakeReorderRepo(
        products=[p1, p2, p3],
        warehouses=[SimpleNamespace(id=wh_id, code="W1", is_active=True)],
        suppliers={supplier_id: SimpleNamespace(id=supplier_id, currency="USD")},
        supplier_products={
            (supplier_id, p1.id): SimpleNamespace(
                cost_price=Decimal("2.5"), moq=None, lead_time_days=None, units_per_carton=None
            )
            # p2 has no supplier_product -> falls back to product.cost_price (1.2)
        },
    )

    def _rec(product, qty, cartons, supplier, status="pending"):
        rec = SimpleNamespace(
            id=uuid.uuid4(), product_id=product.id, warehouse_id=wh_id,
            supplier_id=supplier, recommended_qty=Decimal(qty),
            recommended_cartons=cartons, status=status,
        )
        repo.recs_by_id[rec.id] = rec
        return rec

    rec1 = _rec(p1, 30, 3, supplier_id)
    rec2 = _rec(p2, 500, 50, supplier_id)
    rec3 = _rec(p3, 40, 4, None)                          # no supplier -> skipped
    rec4 = _rec(p1, 30, 3, supplier_id, status="ordered")  # already ordered -> skipped

    svc = _service(repo, fake_audit_repo)
    resp = await svc.create_purchase_orders(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=GeneratePurchaseOrdersRequest(
            recommendation_ids=[rec1.id, rec2.id, rec3.id, rec4.id], notes="auto"
        ),
        ip=None,
    )

    assert resp.created == 1
    po = resp.purchase_orders[0]
    assert po.po_number.startswith("PO-TEST-")
    assert len(po.lines) == 2
    # 30*2.5 + 500*1.2 = 75 + 600 = 675  (effective costs resolved by the service)
    assert po.subtotal == Decimal("675")
    assert po.total == Decimal("675")
    assert set(resp.skipped_recommendation_ids) == {rec3.id, rec4.id}
    assert rec1.status == "ordered"
    assert rec2.status == "ordered"
    # reorder records a linkage audit tying the PO back to the recommendations
    convert = [e for e in fake_audit_repo.entries if e["action"] == "reorder.convert"]
    assert len(convert) == 1
    assert set(convert[0]["changes"]["recommendation_ids"]) == {str(rec1.id), str(rec2.id)}


async def test_create_purchase_orders_consolidates_duplicate_product_recs(fake_audit_repo):
    # Two pending recommendations for the SAME product+warehouse (e.g. left by two
    # reorder runs) must not produce two PO lines — that violates the
    # (po_id, product_id) unique constraint. Keep one line at the larger quantity.
    supplier_id = uuid.uuid4()
    wh_id = uuid.uuid4()
    p1 = _product(sku="P1", name="Prod1", supplier_id=supplier_id, cost="2")

    repo = FakeReorderRepo(
        products=[p1],
        warehouses=[SimpleNamespace(id=wh_id, code="W1", is_active=True)],
        suppliers={supplier_id: SimpleNamespace(id=supplier_id, currency="USD")},
    )

    def _rec(qty, cartons):
        rec = SimpleNamespace(
            id=uuid.uuid4(), product_id=p1.id, warehouse_id=wh_id,
            supplier_id=supplier_id, recommended_qty=Decimal(qty),
            recommended_cartons=cartons, status="pending",
        )
        repo.recs_by_id[rec.id] = rec
        return rec

    small = _rec(10, 1)
    large = _rec(40, 4)

    svc = _service(repo, fake_audit_repo)
    resp = await svc.create_purchase_orders(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=GeneratePurchaseOrdersRequest(recommendation_ids=[small.id, large.id]),
        ip=None,
    )

    assert resp.created == 1
    po = resp.purchase_orders[0]
    assert len(po.lines) == 1                  # consolidated, not duplicated
    assert po.lines[0].product_id == p1.id
    assert po.lines[0].ordered_qty == Decimal("40")  # kept the larger recommendation
    assert po.subtotal == Decimal("80")        # 40 * 2 (cost falls back to product)
    # both source recs are marked ordered — none left dangling
    assert small.status == "ordered" and large.status == "ordered"


class _FakeIntelRepo:
    """Active intelligence rows + supplier→country map for risk-aware reorder."""

    def __init__(self, rows, country_map):
        self._rows = rows
        self._country = country_map

    async def active(self):
        return list(self._rows)

    async def supplier_country_map(self):
        return dict(self._country)


def _intel_row(category, scope_type, scope_key, severity, headline):
    return SimpleNamespace(
        category=category, scope_type=scope_type, scope_key=scope_key,
        severity=Decimal(severity), demand_factor=Decimal("1"),
        confidence=Decimal("0.9"), headline=headline,
    )


def _risk_setup():
    supplier_id = uuid.uuid4()
    wh = SimpleNamespace(id=uuid.uuid4(), code="W1", is_active=True)
    product = _product(sku="SKU1", name="Prod1", supplier_id=supplier_id, upc=10, lead=7, cost="2.5")
    repo = FakeReorderRepo(
        products=[product], warehouses=[wh],
        demand={(product.id, wh.id): (Decimal(180), Decimal(0), 90)},  # avg/day 2
        stock={(product.id, wh.id): (Decimal(5), Decimal(0), Decimal(0))},
        suppliers={supplier_id: SimpleNamespace(id=supplier_id, currency="USD")},
    )
    intel = _FakeIntelRepo(
        rows=[
            _intel_row("supplier", "supplier", str(supplier_id), "0.5", "Acme reliability low"),
            _intel_row("freight", "country", "CN", "0.5", "Freight +40% ex-CN"),
        ],
        country_map={str(supplier_id): "CN"},
    )
    return repo, intel


async def test_run_risk_matches_commodity_tag_and_amplifies_by_product_profile(fake_audit_repo):
    # A steel, critical, single-sourced, non-substitutable product with NO
    # supplier/country signal — only a commodity 'steel' signal exists. The
    # Product Intelligence Profile both BINDS the commodity signal to the SKU
    # and AMPLIFIES it by structural vulnerability.
    supplier_id = uuid.uuid4()
    wh = SimpleNamespace(id=uuid.uuid4(), code="W1", is_active=True)
    product = _product(
        sku="STL1", name="Steel part", supplier_id=supplier_id, upc=10, lead=7, cost="2.5",
        commodity_tags=["steel"], criticality="critical",
        supplier_dependency="single", substitutability="none",
    )
    repo = FakeReorderRepo(
        products=[product], warehouses=[wh],
        demand={(product.id, wh.id): (Decimal(180), Decimal(0), 90)},
        stock={(product.id, wh.id): (Decimal(5), Decimal(0), Decimal(0))},
        suppliers={supplier_id: SimpleNamespace(id=supplier_id, currency="USD")},
    )
    intel = _FakeIntelRepo(
        rows=[_intel_row("commodity", "commodity", "steel", "0.4", "Steel +30%")],
        country_map={},
    )
    svc = ReorderService(repo, FakeProcurementService(), fake_audit_repo, None, intel)

    resp = await svc.run(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=RunReorderRequest(window_days=90), ip=None,
    )
    item = resp.items[0]
    assert item.risk_applied is True
    # base commodity risk 0.4 x vulnerability 1.65 (crit .30 + single .15 + none .20) = 0.66
    assert item.risk_score == Decimal("0.6600")
    assert any("criticality=critical" in d for d in item.risk_drivers)
    assert any("steel" in d.lower() for d in item.risk_drivers)  # commodity signal reached the SKU


async def test_run_risk_aware_lifts_recommendation_and_computes_impact(fake_audit_repo):
    repo, intel = _risk_setup()
    svc = ReorderService(repo, FakeProcurementService(), fake_audit_repo, None, intel)

    resp = await svc.run(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=RunReorderRequest(window_days=90), ip=None,  # risk_aware defaults True
    )
    item = resp.items[0]
    # overall risk = 1-(1-.5)(1-.5)=0.75 ; ss x1.75 ; lead +1.75d -> recommend 40 vs 30
    assert item.risk_applied is True
    assert item.risk_score == Decimal("0.7500")
    assert item.recommended_qty == Decimal("40")
    assert item.expedite is True
    assert item.risk_cost_impact == Decimal("25.0000")  # 10 extra units x 2.5
    assert item.risk_drivers  # which signals contributed
    assert resp.risk_affected == 1
    assert resp.total_risk_cost_impact == Decimal("25.0000")
    # persisted recommendation carries the risk overlay
    assert repo.saved[0].risk_score == Decimal("0.7500")
    assert repo.saved[0].expedite is True


async def test_run_risk_aware_disabled_is_baseline(fake_audit_repo):
    repo, intel = _risk_setup()
    svc = ReorderService(repo, FakeProcurementService(), fake_audit_repo, None, intel)

    resp = await svc.run(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=RunReorderRequest(window_days=90, risk_aware=False), ip=None,
    )
    item = resp.items[0]
    assert item.risk_applied is False
    assert item.recommended_qty == Decimal("30")  # baseline, risk ignored
    assert resp.risk_affected == 0
    assert resp.total_risk_cost_impact == Decimal("0")


async def test_create_purchase_orders_separate_suppliers_make_separate_pos(fake_audit_repo):
    supplier_a, supplier_b = uuid.uuid4(), uuid.uuid4()
    wh_id = uuid.uuid4()
    pa = _product(sku="A", name="ProdA", supplier_id=supplier_a, cost="3")
    pb = _product(sku="B", name="ProdB", supplier_id=supplier_b, cost="4")

    repo = FakeReorderRepo(
        products=[pa, pb],
        warehouses=[SimpleNamespace(id=wh_id, code="W1", is_active=True)],
        suppliers={
            supplier_a: SimpleNamespace(id=supplier_a, currency="USD"),
            supplier_b: SimpleNamespace(id=supplier_b, currency="EUR"),
        },
    )
    rec_a = SimpleNamespace(id=uuid.uuid4(), product_id=pa.id, warehouse_id=wh_id,
                            supplier_id=supplier_a, recommended_qty=Decimal(10),
                            recommended_cartons=1, status="pending")
    rec_b = SimpleNamespace(id=uuid.uuid4(), product_id=pb.id, warehouse_id=wh_id,
                            supplier_id=supplier_b, recommended_qty=Decimal(20),
                            recommended_cartons=2, status="pending")
    repo.recs_by_id[rec_a.id] = rec_a
    repo.recs_by_id[rec_b.id] = rec_b

    svc = _service(repo, fake_audit_repo)
    resp = await svc.create_purchase_orders(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=GeneratePurchaseOrdersRequest(recommendation_ids=[rec_a.id, rec_b.id]),
        ip=None,
    )
    # one PO per distinct supplier (grouping by supplier + warehouse)
    assert resp.created == 2
    assert {po.supplier_id for po in resp.purchase_orders} == {supplier_a, supplier_b}
    assert rec_a.status == "ordered" and rec_b.status == "ordered"
