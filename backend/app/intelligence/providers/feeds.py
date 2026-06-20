"""External-feed intelligence providers: freight, port, commodity, trade.

Each is a thin specialisation of ``FeedIntelligenceProvider`` that fixes the
category, the scope it reports against (so it can be matched to a forecast
context), and how raw metrics map to a 0..1 severity. They are no-ops until an
``ExternalSource`` adapter is injected — wiring a real vendor (Freightos, Xeneta,
a commodity-price or customs/tariff API) means implementing ``ExternalSource``
and passing it in; nothing else changes. Analysts can also enter observations
for these categories manually via the intelligence API.
"""
from __future__ import annotations

from decimal import Decimal

from app.intelligence.providers.base import FeedIntelligenceProvider


class FreightIntelligenceProvider(FeedIntelligenceProvider):
    """Ocean/air freight cost & capacity pressure (e.g. Freightos/Xeneta indexes).
    Scoped by origin country so it matches a supplier's country."""

    category = "freight"
    key = "freightos"
    scope_type = "country"
    severity_cap = Decimal("0.5")          # +50% on a freight index ≈ maximum severity


class PortIntelligenceProvider(FeedIntelligenceProvider):
    """Port congestion / vessel delays / route disruption. Sources usually provide
    a pre-scored congestion level (0..1); scoped by country for matching."""

    category = "port"
    key = "port_monitor"
    scope_type = "country"


class CommodityIntelligenceProvider(FeedIntelligenceProvider):
    """Raw-material price movements for tracked commodities. Scoped by commodity;
    matched to items once products carry a commodity tag (dashboard today)."""

    category = "commodity"
    key = "commodity_index"
    scope_type = "commodity"
    tracked_keys = ["steel", "aluminum", "copper", "lithium", "rubber"]
    severity_cap = Decimal("0.4")          # commodities are volatile; +40% ≈ max severity


class TradeIntelligenceProvider(FeedIntelligenceProvider):
    """Tariffs, quotas, customs / trade-policy changes. Scoped by country."""

    category = "trade"
    key = "trade_monitor"
    scope_type = "country"
    severity_cap = Decimal("0.5")
