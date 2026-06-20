"""Container load planning — deterministic, explainable, pure (``Decimal`` math).

Turns a set of order lines (each a number of cartons with a per-carton volume and
weight) into a shipping plan against standard ocean containers: how many containers
are needed, how full they are by volume *and* by weight, which of the two is the
binding constraint, and how much spare capacity is left to "top off" the last box.

Two real constraints bound a container load, and either can bind first:

  volume   Σ(cartons × m³/carton)  vs  the container's usable internal volume
  weight   Σ(cartons × kg/carton)  vs  the container's max payload

Containers needed = max(volume-bound, weight-bound) count — a dense, heavy product
fills out on weight long before volume; a light, bulky one the opposite. The plan
reports both utilisations so the slack is visible, and a fill suggestion turns that
slack into an actionable "you can add ~N more cartons" number (the service layer
maps that back to whole order quantities, respecting MOQ).

This module is the deterministic substrate; it does not read the DB or forecast.
The capacities below are *nominal* industry references and are overridable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
ONE = Decimal("1")
_Q4 = Decimal("0.0001")
_Q6 = Decimal("0.000001")

# Fraction of internal volume that is realistically usable once cartons are stacked
# (shape/voids/dunnage). Tunable; conservative default.
DEFAULT_USABLE_FRACTION = Decimal("0.90")


def _q4(value: Decimal) -> Decimal:
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


def _q6(value: Decimal) -> Decimal:
    return value.quantize(_Q6, rounding=ROUND_HALF_UP)


def _ceil_div(numerator: Decimal, denominator: Decimal) -> int:
    """Ceiling of ``numerator / denominator`` as an int; 0 when nothing is needed."""
    if numerator <= 0 or denominator <= 0:
        return 0
    return int((numerator / denominator).to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class ContainerSpec:
    """A container type's nominal usable internal volume (m³) and max payload (kg)."""

    code: str
    label: str
    internal_volume_m3: Decimal
    max_payload_kg: Decimal


# Standard dry containers (nominal reference figures; override via the API/service).
CONTAINER_20GP = ContainerSpec("20GP", "20ft Standard", Decimal("33.2"), Decimal("28200"))
CONTAINER_40GP = ContainerSpec("40GP", "40ft Standard", Decimal("67.7"), Decimal("26700"))
CONTAINER_40HC = ContainerSpec("40HC", "40ft High Cube", Decimal("76.4"), Decimal("26500"))

STANDARD_CONTAINERS: tuple[ContainerSpec, ...] = (
    CONTAINER_20GP,
    CONTAINER_40GP,
    CONTAINER_40HC,
)
_BY_CODE = {c.code: c for c in STANDARD_CONTAINERS}


def get_container(code: str) -> ContainerSpec:
    spec = _BY_CODE.get(code)
    if spec is None:
        raise ValueError(f"Unknown container '{code}'. Available: {sorted(_BY_CODE)}")
    return spec


@dataclass(frozen=True)
class LoadItem:
    """One order line to ship: ``cartons`` boxes, each of the given volume/weight.

    ``ref`` is an opaque caller label (SKU / product id) carried through for output.
    Cartons are whole units — you cannot ship a fraction of a carton."""

    ref: str
    cartons: int
    volume_per_carton_m3: Decimal
    weight_per_carton_kg: Decimal

    @property
    def volume_m3(self) -> Decimal:
        return self.volume_per_carton_m3 * Decimal(self.cartons)

    @property
    def weight_kg(self) -> Decimal:
        return self.weight_per_carton_kg * Decimal(self.cartons)


@dataclass(frozen=True)
class ContainerPlan:
    """Explainable result of planning a load into one container type."""

    container_code: str
    container_label: str
    containers_needed: int
    total_cartons: int
    total_volume_m3: Decimal
    total_weight_kg: Decimal
    usable_volume_per_container_m3: Decimal   # internal_volume × usable_fraction
    max_payload_per_container_kg: Decimal
    volume_utilization: Decimal               # 0..1 of provided volume capacity used
    weight_utilization: Decimal               # 0..1 of provided payload used
    binding_constraint: str                   # "volume" | "weight" | "none"
    spare_volume_m3: Decimal                  # unused volume across all containers
    spare_weight_kg: Decimal                  # unused payload across all containers
    drivers: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.containers_needed == 0


def aggregate(items: list[LoadItem]) -> tuple[Decimal, Decimal, int]:
    """Return (total_volume_m3, total_weight_kg, total_cartons) over the items."""
    total_v = sum((i.volume_m3 for i in items), ZERO)
    total_w = sum((i.weight_kg for i in items), ZERO)
    total_c = sum(i.cartons for i in items)
    return (total_v, total_w, total_c)


def plan(
    spec: ContainerSpec,
    items: list[LoadItem],
    *,
    usable_fraction: Decimal = DEFAULT_USABLE_FRACTION,
) -> ContainerPlan:
    """Plan ``items`` into containers of one type.

    Containers needed is the larger of the volume-bound and weight-bound counts, so
    the load fits on *both* dimensions. Utilisations are reported against the total
    capacity actually provisioned (``containers_needed`` × per-container capacity).
    """
    usable_volume = spec.internal_volume_m3 * usable_fraction
    payload = spec.max_payload_kg
    total_v, total_w, total_c = aggregate(items)

    if total_c <= 0 or (total_v <= 0 and total_w <= 0):
        return ContainerPlan(
            container_code=spec.code,
            container_label=spec.label,
            containers_needed=0,
            total_cartons=total_c,
            total_volume_m3=_q6(total_v),
            total_weight_kg=_q4(total_w),
            usable_volume_per_container_m3=_q6(usable_volume),
            max_payload_per_container_kg=_q4(payload),
            volume_utilization=ZERO,
            weight_utilization=ZERO,
            binding_constraint="none",
            spare_volume_m3=ZERO,
            spare_weight_kg=ZERO,
            drivers=["no cartons to ship"],
        )

    n_by_volume = _ceil_div(total_v, usable_volume)
    n_by_weight = _ceil_div(total_w, payload)
    containers = max(n_by_volume, n_by_weight, 1)

    if n_by_weight > n_by_volume:
        binding = "weight"
    elif n_by_volume > n_by_weight:
        binding = "volume"
    else:
        # Same count — the dimension that is fuller is the effective constraint.
        binding = "weight" if (total_w / payload) >= (total_v / usable_volume) else "volume"

    provided_volume = usable_volume * Decimal(containers)
    provided_payload = payload * Decimal(containers)
    vol_util = total_v / provided_volume if provided_volume > 0 else ZERO
    wt_util = total_w / provided_payload if provided_payload > 0 else ZERO

    drivers = [
        f"{containers}×{spec.code}",
        f"volume {_q4(vol_util * 100)}% ({_q6(total_v)}/{_q6(provided_volume)} m³)",
        f"weight {_q4(wt_util * 100)}% ({_q4(total_w)}/{_q4(provided_payload)} kg)",
        f"binding={binding}",
    ]

    return ContainerPlan(
        container_code=spec.code,
        container_label=spec.label,
        containers_needed=containers,
        total_cartons=total_c,
        total_volume_m3=_q6(total_v),
        total_weight_kg=_q4(total_w),
        usable_volume_per_container_m3=_q6(usable_volume),
        max_payload_per_container_kg=_q4(payload),
        volume_utilization=_q4(vol_util),
        weight_utilization=_q4(wt_util),
        binding_constraint=binding,
        spare_volume_m3=_q6(provided_volume - total_v),
        spare_weight_kg=_q4(provided_payload - total_w),
        drivers=drivers,
    )


def recommend_container(
    items: list[LoadItem],
    *,
    usable_fraction: Decimal = DEFAULT_USABLE_FRACTION,
    specs: tuple[ContainerSpec, ...] = STANDARD_CONTAINERS,
) -> ContainerPlan:
    """Pick the container type that ships the load best: fewest containers first
    (the dominant cost), then the highest fill on the binding dimension (least
    wasted space). Returns that type's plan; an empty plan when there is nothing
    to ship."""
    plans = [plan(s, items, usable_fraction=usable_fraction) for s in specs]
    non_empty = [p for p in plans if not p.is_empty]
    if not non_empty:
        return plans[0] if plans else plan(STANDARD_CONTAINERS[0], items)

    def _fill_score(p: ContainerPlan) -> Decimal:
        return max(p.volume_utilization, p.weight_utilization)

    non_empty.sort(key=lambda p: (p.containers_needed, -_fill_score(p)))
    return non_empty[0]


def additional_cartons_that_fit(
    plan_result: ContainerPlan,
    *,
    volume_per_carton_m3: Decimal,
    weight_per_carton_kg: Decimal,
) -> int:
    """How many more cartons of a given size fit in the plan's spare capacity
    (whole cartons, bounded by *both* spare volume and spare weight). This is the
    "top off the last container" lever the service turns into an order bump."""
    limits: list[int] = []
    if volume_per_carton_m3 and volume_per_carton_m3 > 0:
        limits.append(int(plan_result.spare_volume_m3 // volume_per_carton_m3))
    if weight_per_carton_kg and weight_per_carton_kg > 0:
        limits.append(int(plan_result.spare_weight_kg // weight_per_carton_kg))
    if not limits:
        return 0
    return max(min(limits), 0)
