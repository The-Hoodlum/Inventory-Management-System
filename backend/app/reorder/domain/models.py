"""Value objects (pure data) for the reorder engine.

All quantities are ``Decimal`` to avoid floating-point drift in money/stock math;
counts that must be whole (cartons, units-per-carton, MOQ) are ``int``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

ZERO = Decimal("0")
ONE = Decimal("1")


class SafetyStockMethod(str, Enum):
    DAYS_COVER = "days_cover"      # SS = average daily demand x safety days
    STATISTICAL = "statistical"    # SS = z(service_level) x sigma_daily x sqrt(lead_time)


@dataclass(frozen=True)
class DemandStatistics:
    """Demand characteristics derived from a window of daily sales."""

    avg_daily: Decimal
    std_dev_daily: Decimal
    sample_days: int          # length of the lookback window, in calendar days
    days_with_sales: int      # number of days in the window that had any sales
    total_units: Decimal      # total units sold across the window

    @property
    def avg_monthly(self) -> Decimal:
        # 30-day month for reporting convenience.
        return self.avg_daily * Decimal(30)

    @classmethod
    def from_aggregates(
        cls,
        *,
        total_units: Decimal | int | str,
        sum_of_squares: Decimal | int | str,
        window_days: int,
        days_with_sales: int = 0,
    ) -> DemandStatistics:
        """Build stats from SQL aggregates over the window.

        Missing (zero-sales) days contribute 0 to both the sum and the sum of
        squares, so a zero-filled daily series has:

            mean      = sum / N
            variance  = sum_of_squares / N - mean**2      (population variance)

        where N is the window length in calendar days. This yields the correct
        average daily demand and demand standard deviation without having to
        materialise a row for every zero-sales day.
        """
        n = Decimal(window_days if window_days > 0 else 1)
        total = Decimal(total_units)
        s2 = Decimal(sum_of_squares)
        mean = total / n
        variance = (s2 / n) - (mean * mean)
        if variance < 0:  # guard against tiny negative from rounding
            variance = ZERO
        return cls(
            avg_daily=mean,
            std_dev_daily=variance.sqrt(),
            sample_days=int(window_days),
            days_with_sales=int(days_with_sales),
            total_units=total,
        )

    @classmethod
    def zero(cls, window_days: int) -> DemandStatistics:
        return cls(ZERO, ZERO, int(window_days), 0, ZERO)


@dataclass(frozen=True)
class StockPosition:
    """Current stock for a (product, warehouse)."""

    on_hand: Decimal
    reserved: Decimal = ZERO
    damaged: Decimal = ZERO
    on_order: Decimal = ZERO  # open purchase-order quantity not yet received

    @property
    def available(self) -> Decimal:
        return self.on_hand - self.reserved - self.damaged

    @property
    def inventory_position(self) -> Decimal:
        # What drives the reorder decision: available stock plus what's inbound.
        return self.available + self.on_order


@dataclass(frozen=True)
class RiskAdjustment:
    """How supply-chain risk modifies a reorder calculation. Built by the service
    from intelligence (kept as plain numbers so the pure engine has no dependency
    on the intelligence module). Defaults are the identity (no effect)."""

    risk_score: Decimal = ZERO              # 0..1 overall supply risk
    safety_stock_multiplier: Decimal = ONE  # multiplies baseline safety stock
    lead_time_extra_days: Decimal = ZERO    # added to lead time (delays from port/freight/etc.)
    demand_factor: Decimal = ONE            # multiplies daily demand (usually 1)
    drivers: list[str] = field(default_factory=list)  # which signals contributed

    @property
    def is_material(self) -> bool:
        return (
            self.risk_score > ZERO
            or self.safety_stock_multiplier != ONE
            or self.lead_time_extra_days != ZERO
            or self.demand_factor != ONE
        )


@dataclass(frozen=True)
class ReorderPolicy:
    """Effective ordering policy for a product/supplier combination."""

    units_per_carton: int
    moq: int = 0
    lead_time_days: Decimal = ZERO
    review_period_days: Decimal = ZERO
    safety_days: Decimal = ZERO
    service_level: Decimal = Decimal("0.95")
    method: SafetyStockMethod = SafetyStockMethod.DAYS_COVER
    # Manual overrides (None => compute from formulas).
    reorder_point_override: Decimal | None = None
    safety_stock_override: Decimal | None = None


@dataclass(frozen=True)
class OrderQuantity:
    """Outcome of applying the full-carton and MOQ rules to a raw quantity."""

    raw_units: Decimal       # quantity before rounding (S - inventory position)
    cartoned_units: int      # raw rounded UP to a whole number of cartons
    recommended_units: int   # final units after MOQ enforcement (whole cartons)
    cartons: int             # recommended_units / units_per_carton
    applied_moq: bool        # True if MOQ raised the quantity above the cartoned value


@dataclass(frozen=True)
class ReorderResult:
    """Full, explainable output of the reorder calculation for one line."""

    # demand
    avg_daily_demand: Decimal
    avg_monthly_sales: Decimal
    std_dev_daily: Decimal
    # policy inputs (effective)
    lead_time_days: Decimal
    review_period_days: Decimal
    units_per_carton: int
    moq: int
    # computed levels
    safety_stock: Decimal
    safety_stock_method: str
    reorder_point: Decimal
    order_up_to_level: Decimal
    # position
    on_hand: Decimal
    reserved: Decimal
    available: Decimal
    on_order: Decimal
    inventory_position: Decimal
    # decision
    should_reorder: bool
    raw_order_qty: Decimal
    recommended_units: int
    recommended_cartons: int
    applied_moq: bool
    reason: str
    # Risk overlay (defaults = no risk, so existing callers are unaffected).
    risk_applied: bool = False
    risk_score: Decimal = ZERO
    effective_lead_time_days: Decimal = ZERO
    safety_stock_multiplier: Decimal = ONE
    expedite: bool = False                       # order earlier than usual due to risk
    risk_drivers: list[str] = field(default_factory=list)
