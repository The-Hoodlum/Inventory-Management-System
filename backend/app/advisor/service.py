"""AI Supply Chain Analyst service (Phase 10).

Assembles the platform's real signals — pending reorder recommendations, active
supply-chain intelligence signals, supplier scorecards, and the latest demand
forecasts — into a deterministic, explainable ``AdvisoryContext`` (the maths live in
``domain/briefing.py``), then optionally asks an LLM to narrate those grounded
findings. With no LLM configured the briefing is fully deterministic and complete.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_CEILING, Decimal

from app.advisor.domain.briefing import (
    AdvisoryContext,
    build_context,
    finding_from_container_usage,
    select_relevant,
)
from app.advisor.domain.llm import LLMProvider
from app.advisor.schemas import AdvisoryAnswerResponse, AdvisoryBriefingResponse, FindingOut
from app.container.domain.planning import (
    LoadItem,
    additional_cartons_that_fit,
    recommend_container,
)


class AdvisorService:
    def __init__(
        self, reorder_repo, intelligence_repo, forecast_repo, container_repo, llm_provider: LLMProvider
    ) -> None:
        self.reorder = reorder_repo
        self.intel = intelligence_repo
        self.forecast = forecast_repo
        self.container = container_repo
        self.llm = llm_provider

    async def _assemble_context(self) -> AdvisoryContext:
        """Gather the platform's real signals into one grounded context (shared by
        the briefing and the ask endpoint)."""
        recs, _ = await self.reorder.list_recommendations(status="pending", page_size=200)
        signals = await self.intel.active()
        supplier_scores = await self.intel.latest_supplier_scores()
        forecasts = await self.forecast.latest_per_pair()
        products = await self.container.load_products([r.product_id for r in recs])
        return build_context(
            reorder=recs,
            signals=signals,
            supplier_scores=supplier_scores,
            forecasts=forecasts,
            container_findings=self._container_findings(recs, products),
        )

    async def briefing(self, *, question: str | None = None) -> AdvisoryBriefingResponse:
        context = await self._assemble_context()
        narrative = await self.llm.narrate(context, question)

        return AdvisoryBriefingResponse(
            generated_at=context.generated_at,
            summary=context.summary_line,
            llm_enabled=bool(getattr(self.llm, "enabled", False)),
            narrative=narrative,
            metrics=context.metrics,
            findings=[
                FindingOut(
                    category=f.category,
                    severity=f.severity,
                    title=f.title,
                    detail=f.detail,
                    refs=f.refs,
                    recommended_action=f.recommended_action,
                )
                for f in context.findings
            ],
        )

    async def ask(self, *, question: str) -> AdvisoryAnswerResponse:
        """Answer a free-text question: the deterministic relevant findings always,
        plus an LLM answer grounded in those findings when one is configured."""
        context = await self._assemble_context()
        relevant = select_relevant(context, question)
        answer = await self.llm.narrate(context, question)
        return AdvisoryAnswerResponse(
            question=question,
            generated_at=context.generated_at,
            llm_enabled=bool(getattr(self.llm, "enabled", False)),
            answer=answer,
            relevant_findings=[self._finding_out(f) for f in relevant],
            metrics=context.metrics,
        )

    @staticmethod
    def _finding_out(f) -> FindingOut:
        return FindingOut(
            category=f.category, severity=f.severity, title=f.title,
            detail=f.detail, refs=f.refs, recommended_action=f.recommended_action,
        )

    @staticmethod
    def _container_findings(recs, products) -> list:
        """A shipment per supplier: build a load from that supplier's sourced reorder
        recs (those whose products have carton dims), plan it, and flag under-utilised
        containers. Reuses the container domain so the advisor reasons over the full
        demand→reorder→shipping chain."""
        groups: dict = defaultdict(list)
        for r in recs:
            sid = getattr(r, "supplier_id", None)
            if sid is not None:
                groups[sid].append(r)

        findings = []
        for sid, group in groups.items():
            items: list[LoadItem] = []
            for r in group:
                p = products.get(getattr(r, "product_id", None))
                vol = getattr(p, "volume_per_carton", None) if p else None
                wt = getattr(p, "weight_per_carton", None) if p else None
                if p is None or vol is None or wt is None or vol <= 0 or wt <= 0:
                    continue
                upc = int(getattr(p, "units_per_carton", 1) or 1)
                cartons = int(getattr(r, "recommended_cartons", 0) or 0)
                if cartons <= 0:
                    qty = Decimal(getattr(r, "recommended_qty", 0) or 0)
                    cartons = (
                        int((qty / Decimal(upc)).to_integral_value(rounding=ROUND_CEILING))
                        if qty > 0
                        else 0
                    )
                if cartons <= 0:
                    continue
                items.append(
                    LoadItem(
                        ref=str(r.product_id), cartons=cartons,
                        volume_per_carton_m3=Decimal(vol), weight_per_carton_kg=Decimal(wt),
                    )
                )
            if not items:
                continue
            plan = recommend_container(items)
            if plan.is_empty:
                continue
            dominant = max(items, key=lambda i: i.volume_m3)
            top_off = additional_cartons_that_fit(
                plan,
                volume_per_carton_m3=dominant.volume_per_carton_m3,
                weight_per_carton_kg=dominant.weight_per_carton_kg,
            )
            finding = finding_from_container_usage(
                label=f"Supplier {str(sid)[:8]}",
                container_code=plan.container_code,
                containers_needed=plan.containers_needed,
                fill=max(plan.volume_utilization, plan.weight_utilization),
                top_off_cartons=top_off,
            )
            if finding is not None:
                findings.append(finding)
        return findings
