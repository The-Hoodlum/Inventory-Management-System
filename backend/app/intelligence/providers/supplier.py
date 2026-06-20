"""Supplier-risk provider — the fully-functional, internally-computed provider.

Reads per-supplier delivery performance (on-time rate, lead-time mean/variance,
fill rate, received-PO count) from purchase-order history and turns it into a
supplier-scoped intelligence observation. Confidence scales with sample size, so
a supplier with little history contributes a low-confidence signal rather than a
falsely precise one.
"""
from __future__ import annotations

from decimal import Decimal

from app.intelligence.domain.supplier_risk import SupplierMetrics, supplier_risk
from app.intelligence.providers.base import ONE, Observation, IntelligenceProvider

_FULL_CONFIDENCE_POS = Decimal("10")  # received POs for full confidence


class SupplierRiskProvider(IntelligenceProvider):
    category = "supplier"
    key = "supplier_risk"

    def __init__(self, repo) -> None:
        self.repo = repo

    async def collect(self) -> list[Observation]:
        rows = await self.repo.supplier_metrics()
        observations: list[Observation] = []
        for sid, name, _country, metrics in rows:
            result = supplier_risk(metrics)
            # Skip suppliers with no signal and no concerns.
            if result.risk_score <= 0 and not result.reasons:
                continue

            confidence = min(ONE, Decimal(metrics.received_po_count) / _FULL_CONFIDENCE_POS)
            reason_txt = "; ".join(result.reasons) if result.reasons else "within tolerance"
            observations.append(
                Observation(
                    category=self.category,
                    scope_type="supplier",
                    scope_key=str(sid),
                    severity=result.risk_score,
                    demand_factor=ONE,
                    confidence=confidence,
                    headline=f"{name}: reliability {result.reliability} — {reason_txt}",
                    source=self.key,
                    detail={
                        "reliability": str(result.reliability),
                        "components": {k: str(v) for k, v in result.components.items()},
                        "reasons": result.reasons,
                        "received_po_count": metrics.received_po_count,
                    },
                )
            )
        return observations
