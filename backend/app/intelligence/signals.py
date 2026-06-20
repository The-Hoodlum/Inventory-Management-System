"""Bridge from the intelligence data layer into the forecast SignalPipeline.

A point-in-time ``IntelligenceSnapshot`` (built from active observations) is
attached to a ``SignalContext.extra['intelligence']``; the registered
``IntelligenceForecastSignal`` reads it, matches the context (global +
supplier + the supplier's country), and collapses every matching observation
into ONE ``SignalAdjustment`` for the pipeline. With no snapshot attached the
signal abstains, so forecasting is unaffected until intelligence is supplied.

This module sits *above* the forecast core: it depends on the pipeline seam
(`ForecastSignal`, `SignalContext`, `SignalAdjustment`, `register_signal`), never
the other way around. Importing it registers the bridge.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.forecast.domain.signals import (
    ForecastSignal,
    SignalAdjustment,
    SignalContext,
    register_signal,
)
from app.intelligence.domain.geo import to_iso2
from app.intelligence.domain.scoring import ScopedAdjustment, combine_risk_factor


@dataclass
class IntelligenceSnapshot:
    """Active intelligence grouped by how it can be matched to a context."""

    global_adjustments: list[ScopedAdjustment] = field(default_factory=list)
    by_supplier: dict[str, list[ScopedAdjustment]] = field(default_factory=dict)
    by_country: dict[str, list[ScopedAdjustment]] = field(default_factory=dict)
    by_commodity: dict[str, list[ScopedAdjustment]] = field(default_factory=dict)
    supplier_country: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not (
            self.global_adjustments or self.by_supplier or self.by_country or self.by_commodity
        )


def build_snapshot(
    rows, supplier_country: dict[str, str] | None = None
) -> IntelligenceSnapshot:
    """Group active ``intelligence_signals`` rows into a matchable snapshot.

    ``rows`` are objects with category/scope_type/scope_key/severity/demand_factor/
    confidence/headline (ORM rows or any duck-typed equivalent)."""
    # Normalise supplier countries to ISO-2 so they match country-scoped signals
    # (e.g. supplier 'USA' matches a 'US' signal). Unmappable values are kept as-is.
    snap = IntelligenceSnapshot(
        supplier_country={
            k: (to_iso2(v) or v) for k, v in (supplier_country or {}).items()
        }
    )
    for r in rows:
        adj = ScopedAdjustment(
            category=r.category,
            severity=r.severity,
            demand_factor=r.demand_factor,
            confidence=r.confidence,
            headline=r.headline,
        )
        if r.scope_type == "supplier" and r.scope_key:
            snap.by_supplier.setdefault(r.scope_key, []).append(adj)
        elif r.scope_type == "country" and r.scope_key:
            snap.by_country.setdefault(to_iso2(r.scope_key) or r.scope_key, []).append(adj)
        elif r.scope_type == "commodity" and r.scope_key:
            snap.by_commodity.setdefault(r.scope_key, []).append(adj)
        elif r.scope_type == "global":
            snap.global_adjustments.append(adj)
        # route/port scopes are surfaced on the dashboard; they bind to live
        # decisions once products/lanes carry the corresponding identifier.
    return snap


def match_context(
    snapshot: IntelligenceSnapshot,
    supplier_id,
    *,
    commodity_tags: tuple[str, ...] | list[str] = (),
    origin_country: str | None = None,
    include_global: bool = True,
) -> list[ScopedAdjustment]:
    """All adjustments that apply to a context: global + the supplier + the
    supplier's country + (Product Intelligence Profile) the product's own
    commodity tags and country of origin. Shared by the forecast-signal bridge
    and the reorder risk path so matching stays consistent. Deduplicated so a
    signal that matches on two axes (e.g. supplier country == origin country) is
    only counted once. Set ``include_global=False`` for supplier scoring, where
    only supplier-specific risk should count (not macro/global signals)."""
    matched: list[ScopedAdjustment] = list(snapshot.global_adjustments) if include_global else []
    if supplier_id is not None:
        sid = str(supplier_id)
        matched += snapshot.by_supplier.get(sid, [])
        country = snapshot.supplier_country.get(sid)
        if country:
            matched += snapshot.by_country.get(country, [])
    if origin_country:
        matched += snapshot.by_country.get(to_iso2(origin_country) or origin_country, [])
    for tag in commodity_tags:
        matched += snapshot.by_commodity.get(tag, [])

    seen: set[int] = set()
    deduped: list[ScopedAdjustment] = []
    for adj in matched:
        if id(adj) not in seen:
            seen.add(id(adj))
            deduped.append(adj)
    return deduped


class IntelligenceForecastSignal(ForecastSignal):
    """The single registered signal that injects intelligence into the pipeline."""

    key = "intelligence"
    category = "intelligence"

    def evaluate(self, ctx: SignalContext) -> SignalAdjustment | None:
        snap = (ctx.extra or {}).get("intelligence")
        if not isinstance(snap, IntelligenceSnapshot) or snap.is_empty:
            return None

        matched = match_context(snap, ctx.supplier_id)
        if not matched:
            return None

        risk, factor = combine_risk_factor(matched)
        top = sorted(matched, key=lambda a: a.severity, reverse=True)[:3]
        return SignalAdjustment(
            source=self.key,
            category=self.category,
            demand_factor=factor,
            risk_delta=risk,
            reason="; ".join(a.headline for a in top),
        )


# Register the bridge so it participates in default_pipeline().
register_signal(IntelligenceForecastSignal())
