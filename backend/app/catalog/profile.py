"""Product Intelligence Profile — the shared, pure product view the engines read.

This is the substrate that lets the forecast, risk, procurement, and intelligence
engines reason about *what a product is*, not just its prices and pack sizes. It
is a dependency-free value object (no SQLAlchemy, no framework) built from a
``Product`` row, plus two pure helpers:

  vulnerability(profile)        how much product structure amplifies supply risk
                                (critical + single-sourced + non-substitutable
                                items suffer more from the same external shock).

  suggested_forecast_method()   maps the product's demand character to a forecast
                                provider key, so the engine can default sensibly
                                when the caller doesn't pick a method.

Carton dimensions reuse the existing ``volume_per_carton`` (m³) /
``weight_per_carton`` (kg) columns — exposed here under the container-optimization
names — rather than duplicating them.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

ONE = Decimal("1")
_Q4 = Decimal("0.0001")

# Vulnerability weights — additive nudges to a base amplifier of 1.0. Tunable.
_CRITICALITY = {"low": Decimal("0"), "medium": Decimal("0"), "high": Decimal("0.15"), "critical": Decimal("0.30")}
_SUBSTITUTABILITY = {"none": Decimal("0.20"), "low": Decimal("0.10"), "medium": Decimal("0"), "high": Decimal("-0.05")}
_DEPENDENCY = {"single": Decimal("0.15"), "dual": Decimal("0.05"), "multi": Decimal("0")}
_STRATEGIC = Decimal("0.15")          # a strategic item suffers more from the same shock
_ALTERNATE_SUPPLIER = Decimal("-0.10")  # a qualified second source mitigates supply risk

_AMP_MIN = Decimal("0.75")
_AMP_MAX = Decimal("1.75")

# Demand character -> forecast provider key. Mirrors patterns.suggested_method_for
# (the measured counterpart): intermittent/lumpy demand -> Croston, seasonal ->
# the seasonal decomposition provider.
_DEMAND_METHOD = {
    "smooth": "moving_average",
    "erratic": "exponential_smoothing",
    "intermittent": "croston",
    "lumpy": "croston",
    "seasonal": "seasonal",
}


def _q(value: Decimal) -> Decimal:
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ProductProfile:
    """Decision-relevant product attributes, normalised for the engines."""

    commodity_tags: tuple[str, ...] = ()
    country_of_origin: str | None = None
    transport_mode: str | None = None
    criticality: str = "medium"
    supplier_dependency: str | None = None
    demand_type: str | None = None
    substitutability: str | None = None
    strategic_item: bool = False
    alternate_supplier_available: bool = False
    units_per_carton: int = 1
    moq: int = 0
    lead_time_days: int = 30
    carton_volume_m3: Decimal | None = None
    carton_weight_kg: Decimal | None = None

    @classmethod
    def from_product(cls, product) -> ProductProfile:
        tags = getattr(product, "commodity_tags", None) or []
        return cls(
            commodity_tags=tuple(str(t) for t in tags),
            country_of_origin=getattr(product, "country_of_origin", None),
            transport_mode=getattr(product, "transport_mode", None),
            criticality=getattr(product, "criticality", None) or "medium",
            supplier_dependency=getattr(product, "supplier_dependency", None),
            demand_type=getattr(product, "demand_type", None),
            substitutability=getattr(product, "substitutability", None),
            strategic_item=bool(getattr(product, "strategic_item", False)),
            alternate_supplier_available=bool(getattr(product, "alternate_supplier_available", False)),
            units_per_carton=int(getattr(product, "units_per_carton", 1) or 1),
            moq=int(getattr(product, "moq", 0) or 0),
            lead_time_days=int(getattr(product, "lead_time_days", 30) or 30),
            carton_volume_m3=getattr(product, "volume_per_carton", None),
            carton_weight_kg=getattr(product, "weight_per_carton", None),
        )


def vulnerability(profile: ProductProfile) -> tuple[Decimal, list[str]]:
    """Return (risk_amplifier, drivers).

    The amplifier multiplies signal-driven supply risk: a critical, single-sourced,
    non-substitutable item is hit harder by the same freight spike or tariff than a
    substitutable commodity. It is the identity (1.0) for an ordinary item, so items
    with no profile data are unaffected. Clamped to a sane band.
    """
    adjustment = Decimal("0")
    drivers: list[str] = []

    crit = (profile.criticality or "medium").lower()
    if crit in _CRITICALITY and _CRITICALITY[crit] != 0:
        adjustment += _CRITICALITY[crit]
        drivers.append(f"criticality={crit}")

    sub = (profile.substitutability or "").lower()
    if sub in _SUBSTITUTABILITY and _SUBSTITUTABILITY[sub] != 0:
        adjustment += _SUBSTITUTABILITY[sub]
        if _SUBSTITUTABILITY[sub] > 0:
            drivers.append(f"substitutability={sub}")

    dep = (profile.supplier_dependency or "").lower()
    if dep in _DEPENDENCY and _DEPENDENCY[dep] != 0:
        adjustment += _DEPENDENCY[dep]
        drivers.append(f"sourcing={dep}")

    if profile.strategic_item:
        adjustment += _STRATEGIC
        drivers.append("strategic_item")

    if profile.alternate_supplier_available:
        adjustment += _ALTERNATE_SUPPLIER
        drivers.append("alternate_supplier_available")

    amp = ONE + adjustment
    if amp < _AMP_MIN:
        amp = _AMP_MIN
    if amp > _AMP_MAX:
        amp = _AMP_MAX
    return _q(amp), drivers


def suggested_forecast_method(demand_type: str | None) -> str | None:
    """Provider key suited to a product's demand character, or None for the default."""
    if not demand_type:
        return None
    return _DEMAND_METHOD.get(demand_type.lower())
