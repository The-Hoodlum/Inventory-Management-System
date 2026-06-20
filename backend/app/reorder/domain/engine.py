"""The reorder calculation engine — the core IP, expressed as a pure function.

    reorder_point (ROP)   = avg_daily_demand x lead_time + safety_stock
    order_up_to_level (S) = avg_daily_demand x (lead_time + review_period) + safety_stock
    inventory_position(IP)= available_stock + on_order
    reorder when          IP <= ROP
    raw order quantity    = max(0, S - IP)
    final order quantity  = full-carton rounding + MOQ enforcement

Manual overrides for reorder point and safety stock take precedence over the
formulas when supplied on the policy.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.reorder.domain.exceptions import InvalidPolicyError
from app.reorder.domain.models import (
    ONE,
    DemandStatistics,
    ReorderPolicy,
    ReorderResult,
    RiskAdjustment,
    StockPosition,
)
from app.reorder.domain.risk import should_expedite
from app.reorder.domain.rounding import enforce_order_quantity
from app.reorder.domain.safety_stock import compute_safety_stock

_Q4 = Decimal("0.0001")


def _q(value: Decimal) -> Decimal:
    """Quantise to 4 dp for stable, comparable output."""
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


def compute_reorder(
    policy: ReorderPolicy,
    demand: DemandStatistics,
    stock: StockPosition,
    risk: RiskAdjustment | None = None,
) -> ReorderResult:
    if policy.units_per_carton < 1:
        raise InvalidPolicyError("units_per_carton must be >= 1")

    risk = risk or RiskAdjustment()  # identity adjustment ⇒ unchanged behaviour

    # Demand and lead time, lifted by risk (factors default to no-op).
    add = demand.avg_daily * risk.demand_factor
    effective_lead = policy.lead_time_days + risk.lead_time_extra_days

    # Safety stock (method-dependent; override wins), then risk buffer on top.
    safety_stock_base, ss_method = compute_safety_stock(policy, demand)
    safety_stock = safety_stock_base * risk.safety_stock_multiplier

    # Reorder point. A manual override is a floor; risk adds the lead-time and
    # safety-stock increments on top of it.
    if policy.reorder_point_override is not None:
        reorder_point = (
            policy.reorder_point_override
            + add * risk.lead_time_extra_days
            + (safety_stock - safety_stock_base)
        )
    else:
        reorder_point = add * effective_lead + safety_stock

    # Order-up-to level. Never let S fall below the reorder point.
    order_up_to = add * (effective_lead + policy.review_period_days) + safety_stock
    if order_up_to < reorder_point:
        order_up_to = reorder_point

    inventory_position = stock.inventory_position
    should_reorder = inventory_position <= reorder_point

    raw = (order_up_to - inventory_position) if should_reorder else Decimal("0")
    if raw < 0:
        raw = Decimal("0")

    oq = enforce_order_quantity(raw, policy.units_per_carton, policy.moq)

    reason = _build_reason(
        should_reorder=should_reorder,
        inventory_position=inventory_position,
        reorder_point=reorder_point,
        order_up_to=order_up_to,
        oq_raw=raw,
        recommended_units=oq.recommended_units,
        cartons=oq.cartons,
        units_per_carton=policy.units_per_carton,
        applied_moq=oq.applied_moq,
        moq=policy.moq,
    )

    expedite = bool(risk.is_material and should_reorder and should_expedite(risk.risk_score))
    if risk.is_material:
        reason = f"{reason} {_risk_clause(risk, effective_lead)}"

    return ReorderResult(
        avg_daily_demand=_q(add),
        avg_monthly_sales=_q(demand.avg_monthly),
        std_dev_daily=_q(demand.std_dev_daily),
        lead_time_days=_q(policy.lead_time_days),
        review_period_days=_q(policy.review_period_days),
        units_per_carton=policy.units_per_carton,
        moq=policy.moq,
        safety_stock=_q(safety_stock),
        safety_stock_method=ss_method,
        reorder_point=_q(reorder_point),
        order_up_to_level=_q(order_up_to),
        on_hand=_q(stock.on_hand),
        reserved=_q(stock.reserved),
        available=_q(stock.available),
        on_order=_q(stock.on_order),
        inventory_position=_q(inventory_position),
        should_reorder=should_reorder,
        raw_order_qty=_q(raw),
        recommended_units=oq.recommended_units,
        recommended_cartons=oq.cartons,
        applied_moq=oq.applied_moq,
        reason=reason,
        risk_applied=risk.is_material,
        risk_score=_q(risk.risk_score),
        effective_lead_time_days=_q(effective_lead),
        safety_stock_multiplier=_q(risk.safety_stock_multiplier),
        expedite=expedite,
        risk_drivers=list(risk.drivers),
    )


def _risk_clause(risk: RiskAdjustment, effective_lead: Decimal) -> str:
    parts: list[str] = [f"Risk {_q(risk.risk_score)}:"]
    if risk.safety_stock_multiplier != ONE:
        parts.append(f"safety stock x{_q(risk.safety_stock_multiplier)}")
    if risk.lead_time_extra_days != Decimal("0"):
        parts.append(f"lead +{_q(risk.lead_time_extra_days)}d (->{_q(effective_lead)}d)")
    if risk.demand_factor != ONE:
        parts.append(f"demand x{_q(risk.demand_factor)}")
    clause = " ".join(parts)
    if risk.drivers:
        clause += " [" + "; ".join(risk.drivers[:3]) + "]"
    return clause + " Order earlier to cover added supply risk."


def _build_reason(
    *,
    should_reorder: bool,
    inventory_position: Decimal,
    reorder_point: Decimal,
    order_up_to: Decimal,
    oq_raw: Decimal,
    recommended_units: int,
    cartons: int,
    units_per_carton: int,
    applied_moq: bool,
    moq: int,
) -> str:
    ip = _q(inventory_position)
    rop = _q(reorder_point)
    if not should_reorder:
        return (
            f"No order: inventory position {ip} is above the reorder point {rop}."
        )
    if recommended_units == 0:
        return (
            f"At the reorder point (position {ip} <= ROP {rop}) but the order-up-to "
            f"gap is zero; nothing to order."
        )
    parts = [
        f"Inventory position {ip} <= reorder point {rop}.",
        f"Target up to {_q(order_up_to)} (gap {_q(oq_raw)}).",
        f"Rounded up to {recommended_units} units = {cartons} carton(s) of {units_per_carton}.",
    ]
    if applied_moq:
        parts.append(f"Raised to MOQ {moq} (kept to whole cartons).")
    return " ".join(parts)
