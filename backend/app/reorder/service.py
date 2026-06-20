"""Application service: turns database state into reorder recommendations and
purchase orders by driving the pure domain engine.

The service owns orchestration and persistence/auditing only — all reorder maths
live in ``app.reorder.domain``. Purchase-order *creation* is delegated to
``ProcurementService`` so there is a single PO creation path: every PO (whether
hand-built or generated from recommendations) gets the same numbering, totals,
lifecycle event timeline, and audit trail.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from app.catalog.profile import ProductProfile, suggested_forecast_method, vulnerability
from app.forecast.domain.methods import build_series
from app.forecast.domain.models import ForecastParams
from app.forecast.domain.providers import default_provider_key, get_provider
from app.forecast.domain.signals import SignalContext, default_pipeline
from app.intelligence.domain.scoring import assess, combine_severities
from app.intelligence.signals import build_snapshot, match_context
from app.procurement.schemas import POCreate, POLineCreate
from app.reorder.domain.engine import compute_reorder
from app.reorder.domain.models import (
    DemandStatistics,
    ReorderPolicy,
    ReorderResult,
    RiskAdjustment,
    SafetyStockMethod,
    StockPosition,
)
from app.reorder.domain.risk import build_risk_adjustment
from app.reorder.repository import ReorderRepository
from app.reorder.schemas import (
    GeneratePurchaseOrdersRequest,
    GeneratePurchaseOrdersResponse,
    PurchaseOrderLineOut,
    PurchaseOrderOut,
    ReorderLineResult,
    ReorderRunResponse,
    RunReorderRequest,
)

# Risk categories that delay supply, and so stretch the effective lead time.
_LEAD_TIME_RISK_CATEGORIES = ("freight", "port", "geopolitical")

if TYPE_CHECKING:
    from app.procurement.service import ProcurementService

_CONVERTIBLE = ("pending", "accepted")
_Q4 = Decimal("0.0001")


@dataclass(frozen=True)
class SupplierTerms:
    supplier_id: uuid.UUID | None
    units_per_carton: int
    moq: int
    lead_time_days: Decimal
    cost_price: Decimal
    currency: str


class ReorderService:
    def __init__(
        self,
        reorder_repo: ReorderRepository,
        procurement_service: ProcurementService,
        audit_repo,
        demand_repo=None,
        intelligence_repo=None,
    ) -> None:
        self.repo = reorder_repo
        self.procurement = procurement_service
        self.audit = audit_repo
        # Only required for demand_mode='forecast'; historical mode never uses it.
        self.demand = demand_repo
        # Optional: enables risk-aware procurement (safety stock / ROP / timing).
        self.intelligence = intelligence_repo

    # ------------------------------------------------------------------ #
    # Recommendation generation
    # ------------------------------------------------------------------ #
    async def run(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        req: RunReorderRequest,
        ip: str | None = None,
    ) -> ReorderRunResponse:
        method = SafetyStockMethod(req.method)
        snapshot = await self._risk_snapshot(req)

        warehouses = await self.repo.list_warehouses(warehouse_id=req.warehouse_id)
        products = await self.repo.list_products(
            category_id=req.category_id, supplier_id=req.supplier_id
        )

        items: list[ReorderLineResult] = []
        evaluated = 0
        to_order = 0
        risk_affected = 0
        total_risk_cost = Decimal("0")

        for wh in warehouses:
            for product in products:
                evaluated += 1
                terms = await self._resolve_terms(product)
                profile = ProductProfile.from_product(product)

                demand = await self._demand_for(product, wh, req, profile)

                on_hand, reserved, damaged = await self.repo.stock_position(product.id, wh.id)
                on_order = await self.repo.on_order_qty(product.id, wh.id)
                stock = StockPosition(
                    on_hand=on_hand, reserved=reserved, damaged=damaged, on_order=on_order
                )

                policy = ReorderPolicy(
                    units_per_carton=terms.units_per_carton,
                    moq=terms.moq,
                    lead_time_days=terms.lead_time_days,
                    review_period_days=req.review_period_days,
                    safety_days=req.safety_days,
                    service_level=req.service_level,
                    method=method,
                    reorder_point_override=(
                        Decimal(product.reorder_point)
                        if product.reorder_point is not None
                        else None
                    ),
                    safety_stock_override=(
                        Decimal(product.safety_stock)
                        if product.safety_stock is not None
                        else None
                    ),
                )

                risk = self._risk_for(terms, profile, snapshot)
                result = compute_reorder(policy, demand, stock, risk if risk.is_material else None)

                # Estimated financial impact of the risk-driven uplift: the extra
                # units risk added, valued at unit cost.
                risk_cost = Decimal("0")
                if risk.is_material:
                    base = compute_reorder(policy, demand, stock, None)
                    extra_units = result.recommended_units - base.recommended_units
                    if extra_units > 0:
                        risk_cost = (Decimal(extra_units) * terms.cost_price).quantize(_Q4)

                actionable = result.should_reorder and result.recommended_units > 0
                if actionable and result.risk_applied:
                    risk_affected += 1
                    total_risk_cost += risk_cost

                rec_id: uuid.UUID | None = None
                if actionable:
                    to_order += 1
                    if req.persist:
                        rec = await self.repo.save_recommendation(
                            tenant_id=tenant_id,
                            product_id=product.id,
                            warehouse_id=wh.id,
                            supplier_id=terms.supplier_id,
                            available_qty=result.available,
                            on_order_qty=result.on_order,
                            avg_daily_demand=result.avg_daily_demand,
                            reorder_point=result.reorder_point,
                            safety_stock=result.safety_stock,
                            recommended_qty=Decimal(result.recommended_units),
                            recommended_cartons=result.recommended_cartons,
                            status="pending",
                            risk_score=result.risk_score,
                            lead_time_extra_days=risk.lead_time_extra_days,
                            risk_cost_impact=risk_cost,
                            expedite=result.expedite,
                            risk_drivers=result.risk_drivers or None,
                        )
                        rec_id = rec.id

                if (not req.only_below_rop) or actionable:
                    items.append(
                        self._to_line(product, wh.id, terms.supplier_id, result, rec_id, risk_cost)
                    )

        await self.audit.add(
            tenant_id=tenant_id,
            user_id=user_id,
            action="reorder.run",
            entity_type="reorder_run",
            entity_id=None,
            changes={
                "window_days": req.window_days,
                "method": req.method,
                "demand_mode": req.demand_mode,
                "risk_aware": req.risk_aware and snapshot is not None,
                "evaluated": evaluated,
                "to_order": to_order,
                "risk_affected": risk_affected,
                "total_risk_cost_impact": str(total_risk_cost),
                "persisted": req.persist,
            },
            ip_address=ip,
        )

        return ReorderRunResponse(
            generated_at=dt.datetime.now(dt.UTC),
            window_days=req.window_days,
            evaluated=evaluated,
            to_order=to_order,
            risk_affected=risk_affected,
            total_risk_cost_impact=total_risk_cost,
            items=items,
        )

    # ------------------------------------------------------------------ #
    # Risk overlay
    # ------------------------------------------------------------------ #
    async def _risk_snapshot(self, req: RunReorderRequest):
        """Load the active-intelligence snapshot once per run (None when risk is
        disabled or no intelligence repository is wired)."""
        if not req.risk_aware or self.intelligence is None:
            return None
        rows = await self.intelligence.active()
        if not rows:
            return None
        country_map = await self.intelligence.supplier_country_map()
        return build_snapshot(rows, country_map)

    def _risk_for(
        self, terms: SupplierTerms, profile: ProductProfile, snapshot
    ) -> RiskAdjustment:
        """Turn the intelligence that matches this SKU into a reorder risk
        adjustment. Matching uses the supplier AND the Product Intelligence
        Profile (the product's commodity tags + country of origin), so commodity
        and origin-country signals finally reach the item. The product's
        structural vulnerability (criticality / sourcing / substitutability) then
        amplifies the signal-driven risk. Lead-time risk comes only from
        supply-delaying categories."""
        if snapshot is None:
            return RiskAdjustment()
        matched = match_context(
            snapshot,
            terms.supplier_id,
            commodity_tags=profile.commodity_tags,
            origin_country=profile.country_of_origin,
        )
        if not matched:
            return RiskAdjustment()
        assessment = assess(matched)

        amplifier, vuln_drivers = vulnerability(profile)
        overall_risk = assessment.risk_score * amplifier
        if overall_risk > Decimal("1"):
            overall_risk = Decimal("1")

        lead_time_risk = combine_severities(
            [assessment.by_category.get(c, Decimal("0")) for c in _LEAD_TIME_RISK_CATEGORIES]
        )
        return build_risk_adjustment(
            overall_risk=overall_risk,
            lead_time_risk=lead_time_risk,
            demand_factor=assessment.demand_factor,
            lead_time_days=terms.lead_time_days,
            drivers=assessment.drivers + vuln_drivers,
        )

    # ------------------------------------------------------------------ #
    # Purchase-order generation (delegates to the single PO creation path)
    # ------------------------------------------------------------------ #
    async def create_purchase_orders(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        req: GeneratePurchaseOrdersRequest,
        ip: str | None = None,
    ) -> GeneratePurchaseOrdersResponse:
        recs = await self.repo.get_recommendations_by_ids(req.recommendation_ids)

        # Group convertible recommendations by (supplier, warehouse). One PO each.
        groups: dict[tuple[uuid.UUID, uuid.UUID], list] = {}
        skipped: list[uuid.UUID] = []
        for rec in recs:
            if rec.status not in _CONVERTIBLE or rec.supplier_id is None:
                skipped.append(rec.id)
                continue
            groups.setdefault((rec.supplier_id, rec.warehouse_id), []).append(rec)

        purchase_orders: list[PurchaseOrderOut] = []
        for (supplier_id, warehouse_id), group in groups.items():
            # One PO line per product. If several recommendations target the same
            # product (e.g. multiple reorder runs each left a pending rec for it),
            # keep the one with the largest recommended quantity rather than emitting
            # a duplicate line — the PO schema allows a product only once — or summing
            # them, which would double-order the same need. Every rec in the group is
            # still marked 'ordered' below, so none is left dangling.
            best_by_product: dict = {}
            for rec in group:
                current = best_by_product.get(rec.product_id)
                if current is None or Decimal(rec.recommended_qty) > Decimal(current.recommended_qty):
                    best_by_product[rec.product_id] = rec

            lines: list[POLineCreate] = []
            for rec in best_by_product.values():
                unit_cost = await self._effective_cost(supplier_id, rec.product_id)
                lines.append(
                    POLineCreate(
                        product_id=rec.product_id,
                        ordered_qty=Decimal(rec.recommended_qty),
                        unit_cost=unit_cost,
                        ordered_cartons=rec.recommended_cartons,
                    )
                )

            # Delegate to the canonical PO creation path (numbering, totals,
            # 'created' event, and po.create audit all handled there).
            po = await self.procurement.create_po(
                tenant_id=tenant_id,
                user_id=user_id,
                data=POCreate(
                    supplier_id=supplier_id,
                    warehouse_id=warehouse_id,
                    expected_date=req.expected_date,
                    notes=req.notes,
                    lines=lines,
                ),
                ip=ip,
            )

            for rec in group:
                rec.status = "ordered"

            # Reorder-specific linkage so a PO is traceable back to the run.
            await self.audit.add(
                tenant_id=tenant_id,
                user_id=user_id,
                action="reorder.convert",
                entity_type="purchase_order",
                entity_id=po.id,
                changes={
                    "po_number": po.po_number,
                    "supplier_id": str(supplier_id),
                    "warehouse_id": str(warehouse_id),
                    "lines": len(group),
                    "recommendation_ids": [str(r.id) for r in group],
                },
                ip_address=ip,
            )
            purchase_orders.append(self._po_out_from_procurement(po))

        return GeneratePurchaseOrdersResponse(
            created=len(purchase_orders),
            purchase_orders=purchase_orders,
            skipped_recommendation_ids=skipped,
        )

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    async def list_recommendations(self, **kwargs):
        return await self.repo.list_recommendations(**kwargs)

    # ------------------------------------------------------------------ #
    # Demand input (historical mean vs forecast-driven)
    # ------------------------------------------------------------------ #
    async def _demand_for(
        self, product, wh, req: RunReorderRequest, profile: ProductProfile | None = None
    ) -> DemandStatistics:
        """Build the demand statistics that drive the reorder calculation.

        historical : window mean + variance straight from sales_daily.
        forecast   : run a forecast provider over the same daily series (through
                     the signal pipeline) and use its expected daily demand. The
                     reorder engine itself is unchanged — only its demand input is.

        When the caller doesn't pin a forecast method, the product's demand
        character (Product Intelligence Profile) picks a sensible default.
        """
        today = dt.date.today()
        if req.demand_mode == "forecast" and self.demand is not None:
            start = today - dt.timedelta(days=req.window_days - 1)
            points = await self.demand.daily_series(
                product_id=product.id, warehouse_id=wh.id, start_date=start, end_date=today
            )
            series = build_series(points, end_day=today, window_days=req.window_days)
            demand_type = profile.demand_type if profile else None
            method_key = (
                req.forecast_method
                or suggested_forecast_method(demand_type)
                or default_provider_key()
            )
            provider = get_provider(method_key)
            base = provider.generate(
                series,
                ForecastParams(
                    window_days=req.window_days,
                    ma_window=req.forecast_ma_window,
                    alpha=req.forecast_alpha,
                ),
            )
            adjusted = default_pipeline().apply(
                SignalContext(base=base, product_id=product.id, warehouse_id=wh.id, as_of=today)
            )
            return DemandStatistics(
                avg_daily=adjusted.adjusted_daily_demand,
                std_dev_daily=base.std_dev_daily,
                sample_days=req.window_days,
                days_with_sales=base.days_with_demand,
                total_units=base.total_demand,
            )

        start_date = today - dt.timedelta(days=req.window_days)
        total, sum_sq, days_with_sales = await self.repo.demand_aggregates(
            product.id, wh.id, start_date
        )
        return DemandStatistics.from_aggregates(
            total_units=total,
            sum_of_squares=sum_sq,
            window_days=req.window_days,
            days_with_sales=days_with_sales,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    async def _resolve_terms(self, product) -> SupplierTerms:
        supplier_id = product.primary_supplier_id
        sp = None
        supplier = None
        if supplier_id is not None:
            sp = await self.repo.get_supplier_product(supplier_id, product.id)
            supplier = await self.repo.get_supplier(supplier_id)

        upc = (sp.units_per_carton if sp and sp.units_per_carton else None) or product.units_per_carton or 1
        moq = sp.moq if (sp and sp.moq is not None) else product.moq
        lead = (sp.lead_time_days if sp else None) or product.lead_time_days
        cost = sp.cost_price if (sp and sp.cost_price is not None) else product.cost_price
        currency = supplier.currency if supplier else "USD"

        return SupplierTerms(
            supplier_id=supplier_id,
            units_per_carton=int(upc),
            moq=int(moq or 0),
            lead_time_days=Decimal(lead or 0),
            cost_price=Decimal(cost or 0),
            currency=currency,
        )

    async def _effective_cost(self, supplier_id: uuid.UUID, product_id: uuid.UUID) -> Decimal:
        sp = await self.repo.get_supplier_product(supplier_id, product_id)
        if sp and sp.cost_price is not None:
            return Decimal(sp.cost_price)
        product = await self.repo.get_product(product_id)
        return Decimal(product.cost_price) if product and product.cost_price is not None else Decimal("0")

    @staticmethod
    def _to_line(
        product,
        warehouse_id: uuid.UUID,
        supplier_id: uuid.UUID | None,
        r: ReorderResult,
        rec_id: uuid.UUID | None,
        risk_cost: Decimal = Decimal("0"),
    ) -> ReorderLineResult:
        return ReorderLineResult(
            product_id=product.id,
            sku=product.sku,
            name=product.name,
            warehouse_id=warehouse_id,
            supplier_id=supplier_id,
            avg_daily_demand=r.avg_daily_demand,
            avg_monthly_sales=r.avg_monthly_sales,
            std_dev_daily=r.std_dev_daily,
            lead_time_days=r.lead_time_days,
            review_period_days=r.review_period_days,
            units_per_carton=r.units_per_carton,
            moq=r.moq,
            safety_stock=r.safety_stock,
            safety_stock_method=r.safety_stock_method,
            reorder_point=r.reorder_point,
            order_up_to_level=r.order_up_to_level,
            on_hand=r.on_hand,
            reserved=r.reserved,
            available=r.available,
            on_order=r.on_order,
            inventory_position=r.inventory_position,
            should_reorder=r.should_reorder,
            recommended_qty=Decimal(r.recommended_units),
            recommended_cartons=r.recommended_cartons,
            applied_moq=r.applied_moq,
            reason=r.reason,
            risk_applied=r.risk_applied,
            risk_score=r.risk_score,
            effective_lead_time_days=r.effective_lead_time_days,
            safety_stock_multiplier=r.safety_stock_multiplier,
            expedite=r.expedite,
            risk_cost_impact=risk_cost,
            risk_drivers=r.risk_drivers,
            recommendation_id=rec_id,
        )

    @staticmethod
    def _po_out_from_procurement(po) -> PurchaseOrderOut:
        """Map the procurement service's POOut onto the reorder response shape."""
        return PurchaseOrderOut(
            id=po.id,
            po_number=po.po_number,
            supplier_id=po.supplier_id,
            warehouse_id=po.warehouse_id,
            status=po.status,
            currency=po.currency,
            fx_rate=po.fx_rate,
            subtotal=po.subtotal,
            tax=po.tax,
            total=po.total,
            notes=po.notes,
            expected_date=po.expected_date,
            created_at=po.created_at,
            lines=[
                PurchaseOrderLineOut(
                    id=ln.id,
                    product_id=ln.product_id,
                    ordered_qty=ln.ordered_qty,
                    ordered_cartons=ln.ordered_cartons,
                    unit_cost=ln.unit_cost,
                    line_total=ln.line_total,
                    received_qty=ln.received_qty,
                )
                for ln in po.lines
            ],
        )
