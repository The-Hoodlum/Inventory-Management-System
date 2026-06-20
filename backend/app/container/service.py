"""Container load planning service (Phase 9).

Orchestration only — the maths live in ``app.container.domain.planning``. Builds
``LoadItem`` rows from the request's order lines (pulling each product's carton
volume/weight, and converting units → whole cartons via units-per-carton), then
plans them against a chosen or recommended container and derives an MOQ-aware
top-off suggestion. Reads only; nothing is persisted.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from app.container.domain.planning import (
    STANDARD_CONTAINERS,
    LoadItem,
    additional_cartons_that_fit,
    get_container,
    recommend_container,
)
from app.container.domain.planning import plan as plan_load
from app.container.schemas import (
    ContainerOption,
    ContainerPlanRequest,
    ContainerPlanResponse,
    PlanLineOut,
    TopOffSuggestion,
)
from app.core.exceptions import BusinessRuleError


class ContainerService:
    def __init__(self, repo) -> None:
        self.repo = repo

    # ------------------------------ containers ----------------------------- #
    @staticmethod
    def containers() -> list[ContainerOption]:
        return [
            ContainerOption(
                code=c.code,
                label=c.label,
                internal_volume_m3=c.internal_volume_m3,
                max_payload_kg=c.max_payload_kg,
            )
            for c in STANDARD_CONTAINERS
        ]

    # -------------------------------- plan --------------------------------- #
    async def plan(self, *, req: ContainerPlanRequest) -> ContainerPlanResponse:
        products = await self.repo.load_products([ln.product_id for ln in req.lines])

        items: list[LoadItem] = []
        line_outs: list[PlanLineOut] = []
        skipped: list = []
        by_ref: dict[str, object] = {}  # LoadItem.ref -> product (for top-off)

        for ln in req.lines:
            p = products.get(ln.product_id)
            vol = getattr(p, "volume_per_carton", None) if p else None
            wt = getattr(p, "weight_per_carton", None) if p else None
            if p is None or vol is None or wt is None or vol <= 0 or wt <= 0:
                skipped.append(ln.product_id)  # can't plan without carton dimensions
                continue
            upc = int(getattr(p, "units_per_carton", 1) or 1)
            cartons = ln.cartons if ln.cartons is not None else (int(ln.units) + upc - 1) // upc
            item = LoadItem(
                ref=str(ln.product_id),
                cartons=cartons,
                volume_per_carton_m3=Decimal(vol),
                weight_per_carton_kg=Decimal(wt),
            )
            items.append(item)
            line_outs.append(
                PlanLineOut(
                    product_id=p.id, sku=p.sku, cartons=cartons,
                    volume_m3=item.volume_m3, weight_kg=item.weight_kg,
                )
            )
            by_ref[item.ref] = p

        return self._finalize(
            items, line_outs, by_ref, skipped,
            container_code=req.container_code, usable_fraction=req.usable_fraction,
        )

    # ----------------------- plan from reorder recs ------------------------ #
    async def plan_from_recommendations(self, *, req) -> ContainerPlanResponse:
        """Plan a shipment directly from reorder recommendations — the bridge from
        forecast-driven reordering to container loading. Each rec's cartons come
        from ``recommended_cartons`` (falling back to qty ÷ units-per-carton)."""
        recs = await self.repo.load_recommendations(req.recommendation_ids)
        products = await self.repo.load_products([r.product_id for r in recs])

        items: list[LoadItem] = []
        line_outs: list[PlanLineOut] = []
        skipped: list = []
        by_ref: dict[str, object] = {}

        for rec in recs:
            p = products.get(rec.product_id)
            vol = getattr(p, "volume_per_carton", None) if p else None
            wt = getattr(p, "weight_per_carton", None) if p else None
            if p is None or vol is None or wt is None or vol <= 0 or wt <= 0:
                skipped.append(rec.product_id)
                continue
            upc = int(getattr(p, "units_per_carton", 1) or 1)
            cartons = int(rec.recommended_cartons or 0)
            if cartons <= 0:
                qty = Decimal(rec.recommended_qty or 0)
                cartons = (
                    int((qty / Decimal(upc)).to_integral_value(rounding=ROUND_CEILING))
                    if qty > 0
                    else 0
                )
            if cartons <= 0:
                skipped.append(rec.product_id)
                continue
            item = LoadItem(
                ref=str(rec.product_id), cartons=cartons,
                volume_per_carton_m3=Decimal(vol), weight_per_carton_kg=Decimal(wt),
            )
            items.append(item)
            line_outs.append(
                PlanLineOut(
                    product_id=p.id, sku=p.sku, cartons=cartons,
                    volume_m3=item.volume_m3, weight_kg=item.weight_kg,
                )
            )
            by_ref[item.ref] = p

        return self._finalize(
            items, line_outs, by_ref, skipped,
            container_code=req.container_code, usable_fraction=req.usable_fraction,
        )

    # ------------------------------- shared -------------------------------- #
    def _finalize(
        self, items, line_outs, by_ref, skipped, *, container_code, usable_fraction
    ) -> ContainerPlanResponse:
        if not items:
            raise BusinessRuleError(
                "No plannable lines: the selected products have no carton volume/weight set."
            )
        if container_code:
            result = plan_load(get_container(container_code), items, usable_fraction=usable_fraction)
        else:
            result = recommend_container(items, usable_fraction=usable_fraction)

        return ContainerPlanResponse(
            container_code=result.container_code,
            container_label=result.container_label,
            containers_needed=result.containers_needed,
            total_cartons=result.total_cartons,
            total_volume_m3=result.total_volume_m3,
            total_weight_kg=result.total_weight_kg,
            volume_utilization=result.volume_utilization,
            weight_utilization=result.weight_utilization,
            binding_constraint=result.binding_constraint,
            spare_volume_m3=result.spare_volume_m3,
            spare_weight_kg=result.spare_weight_kg,
            lines=line_outs,
            top_off=self._top_off(result, items, by_ref),
            drivers=result.drivers,
            skipped_product_ids=skipped,
        )

    @staticmethod
    def _top_off(result, items: list[LoadItem], by_ref: dict) -> TopOffSuggestion | None:
        """How much more of the load's dominant item fits the provisioned containers."""
        if result.is_empty or not items:
            return None
        dominant = max(items, key=lambda i: i.volume_m3)
        extra_cartons = additional_cartons_that_fit(
            result,
            volume_per_carton_m3=dominant.volume_per_carton_m3,
            weight_per_carton_kg=dominant.weight_per_carton_kg,
        )
        if extra_cartons <= 0:
            return None
        product = by_ref[dominant.ref]
        units_per_carton = int(getattr(product, "units_per_carton", 1) or 1)
        moq = int(getattr(product, "moq", 0) or 0)
        extra_units = extra_cartons * units_per_carton
        shortfall = max(0, moq - extra_units) if moq else 0
        note = (
            f"Up to {extra_cartons} more carton(s) (~{extra_units} units) of {product.sku} "
            f"fit the {result.containers_needed}×{result.container_code} at no extra container."
        )
        if shortfall:
            note += f" That is {shortfall} units below the product MOQ of {moq}."
        return TopOffSuggestion(
            product_id=product.id,
            sku=product.sku,
            additional_cartons=extra_cartons,
            additional_units=extra_units,
            moq_shortfall=shortfall,
            note=note,
        )
