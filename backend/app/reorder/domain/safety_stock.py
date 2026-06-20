"""Safety-stock calculation methods.

Two methods are supported:

  days_cover   SS = average_daily_demand x safety_days
               Simple, intuitive buffer expressed as N days of average demand.

  statistical  SS = z(service_level) x sigma_daily x sqrt(lead_time_days)
               Buffers against demand variability over the lead time, sized to a
               target service level (probability of not stocking out per cycle).
"""
from __future__ import annotations

import statistics
from decimal import Decimal

from app.reorder.domain.models import DemandStatistics, ReorderPolicy, SafetyStockMethod

ZERO = Decimal("0")


def z_for_service_level(service_level: Decimal | float) -> Decimal:
    """Inverse standard-normal CDF (z-score) for a service level in (0.5, 1)."""
    sl = float(service_level)
    sl = min(max(sl, 0.5), 0.999999)  # clamp to a sane, finite range
    z = statistics.NormalDist().inv_cdf(sl)
    return Decimal(str(round(z, 4)))


def safety_stock_days_cover(avg_daily: Decimal, safety_days: Decimal) -> Decimal:
    return avg_daily * safety_days


def safety_stock_statistical(
    std_dev_daily: Decimal, lead_time_days: Decimal, service_level: Decimal
) -> Decimal:
    if lead_time_days <= 0 or std_dev_daily <= 0:
        return ZERO
    z = z_for_service_level(service_level)
    return z * std_dev_daily * lead_time_days.sqrt()


def compute_safety_stock(
    policy: ReorderPolicy, demand: DemandStatistics
) -> tuple[Decimal, str]:
    """Return (safety_stock, method_label). A manual override always wins."""
    if policy.safety_stock_override is not None:
        return policy.safety_stock_override, "override"
    if policy.method is SafetyStockMethod.STATISTICAL:
        z = z_for_service_level(policy.service_level)
        ss = safety_stock_statistical(
            demand.std_dev_daily, policy.lead_time_days, policy.service_level
        )
        return ss, f"statistical(service_level={policy.service_level}, z={z})"
    ss = safety_stock_days_cover(demand.avg_daily, policy.safety_days)
    return ss, f"days_cover(safety_days={policy.safety_days})"
