"""Deterministic, explainable advisory briefing — the grounded evidence layer.

This is the heart of Phase 10 and works with **no LLM**: it turns the platform's
real signals (reorder recommendations, supply-chain intelligence signals, supplier
scorecards, demand forecasts) into a ranked list of ``Finding`` objects, each with a
0..1 severity, a plain-language explanation built from the actual numbers, the
structured references that back it (for audit), and a concrete recommended action.

The optional LLM layer (``domain/llm.py``) later narrates these findings; it is given
*only* this evidence and instructed not to invent anything. So whether or not an LLM
is configured, every recommendation traces back to a real, inspectable number.

Pure and dependency-free (reads inputs via ``getattr`` so it works equally with ORM
rows and test doubles); no DB, no network, no framework imports.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
ONE = Decimal("1")
_Q4 = Decimal("0.0001")

# Severity floors below which a signal/score isn't worth surfacing as a finding.
_SIGNAL_FLOOR = Decimal("0.2")
_SUPPLIER_RISK_FLOOR = Decimal("0.5")
_HIGH_RISK = Decimal("0.5")
_LOW_CONFIDENCE = Decimal("0.4")
_EXPEDITE_FLOOR = Decimal("0.7")  # an expedite flag is at least this urgent


def _q4(value: Decimal) -> Decimal:
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


def _dec(value, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value)) if value is not None else Decimal(default)
    except (ArithmeticError, ValueError, TypeError):
        return Decimal(default)


def _clamp(value: Decimal) -> Decimal:
    if value < ZERO:
        return ZERO
    if value > ONE:
        return ONE
    return _q4(value)


@dataclass(frozen=True)
class Finding:
    """One explainable observation the advisor surfaces."""

    category: str                 # reorder | supply_signal | supplier_risk | forecast
    severity: Decimal             # 0..1 priority
    title: str                    # short headline
    detail: str                   # plain-language explanation built from real numbers
    refs: dict                    # structured, auditable references (ids + metric values)
    recommended_action: str | None = None


@dataclass(frozen=True)
class AdvisoryContext:
    """The full grounded picture: ranked findings + headline metrics + a summary line.
    This is exactly what the LLM (if configured) is allowed to narrate."""

    generated_at: dt.datetime
    findings: list[Finding]
    metrics: dict
    summary_line: str = ""


# --------------------------------------------------------------------------- #
# Builders — each turns one real data source into findings (pure, defensive).
# --------------------------------------------------------------------------- #
def findings_from_reorder(recs) -> list[Finding]:
    out: list[Finding] = []
    for r in recs:
        qty = _dec(getattr(r, "recommended_qty", 0))
        if qty <= 0:
            continue
        risk = _clamp(_dec(getattr(r, "risk_score", 0)))
        expedite = bool(getattr(r, "expedite", False))
        cost = _dec(getattr(r, "risk_cost_impact", 0))
        drivers = list(getattr(r, "risk_drivers", None) or [])
        sku = getattr(r, "sku", None) or str(getattr(r, "product_id", "?"))
        severity = max(risk, _EXPEDITE_FLOOR) if expedite else risk

        detail = f"Reorder {qty} units of {sku}."
        if expedite:
            detail += " Expedite advised (risk-driven timing)."
        if risk > 0:
            detail += f" Supply risk {risk}."
        if cost > 0:
            detail += f" Added risk cost ~{cost}."
        if drivers:
            detail += f" Drivers: {', '.join(drivers)}."

        action = f"Raise a PO for {qty} units of {sku}"
        action += " and expedite freight." if expedite else "."

        out.append(
            Finding(
                category="reorder",
                severity=severity,
                title=f"Reorder {sku}" + (" — expedite" if expedite else ""),
                detail=detail,
                refs={
                    "product_id": str(getattr(r, "product_id", "")),
                    "recommended_qty": str(qty),
                    "risk_score": str(risk),
                    "expedite": expedite,
                    "risk_cost_impact": str(cost),
                },
                recommended_action=action,
            )
        )
    return out


def findings_from_signals(signals) -> list[Finding]:
    out: list[Finding] = []
    for s in signals:
        severity = _clamp(_dec(getattr(s, "severity", 0)))
        if severity < _SIGNAL_FLOOR:
            continue
        category = getattr(s, "category", "signal")
        scope_type = getattr(s, "scope_type", None)
        scope_key = getattr(s, "scope_key", None)
        headline = getattr(s, "headline", None) or f"{category} signal"
        trend = getattr(s, "trend", None)

        detail = headline
        if scope_type:
            detail += f" (scope: {scope_type}{f'={scope_key}' if scope_key else ''})."
        if trend:
            detail += f" Trend: {trend}."
        out.append(
            Finding(
                category="supply_signal",
                severity=severity,
                title=f"{category.capitalize()} signal: {headline}",
                detail=detail,
                refs={
                    "category": str(category),
                    "scope_type": str(scope_type or ""),
                    "scope_key": str(scope_key or ""),
                    "severity": str(severity),
                    "source": str(getattr(s, "source", "") or ""),
                },
                recommended_action="Review exposed SKUs/suppliers; consider buffer stock or alternate sourcing.",
            )
        )
    return out


def findings_from_supplier_scores(scores) -> list[Finding]:
    out: list[Finding] = []
    for s in scores:
        risk = _clamp(_dec(getattr(s, "risk_score", 0)))
        grade = getattr(s, "grade", None)
        poor_grade = isinstance(grade, str) and grade.upper() in {"D", "F"}
        if risk < _SUPPLIER_RISK_FLOOR and not poor_grade:
            continue
        supplier = getattr(s, "supplier_name", None) or str(getattr(s, "supplier_id", "?"))
        detail = f"Supplier {supplier} scored risk {risk}"
        detail += f", grade {grade}." if grade else "."
        out.append(
            Finding(
                category="supplier_risk",
                severity=max(risk, Decimal("0.6") if poor_grade else ZERO),
                title=f"At-risk supplier: {supplier}" + (f" ({grade})" if grade else ""),
                detail=detail,
                refs={
                    "supplier_id": str(getattr(s, "supplier_id", "")),
                    "risk_score": str(risk),
                    "grade": str(grade or ""),
                },
                recommended_action="Diversify sourcing or add lead-time buffer for this supplier's SKUs.",
            )
        )
    return out


def findings_from_forecasts(forecasts) -> list[Finding]:
    """A single aggregate finding when a notable share of the latest forecasts are
    high-risk or low-confidence — one signal, not per-SKU noise."""
    total = 0
    high_risk = 0
    low_conf = 0
    for f in forecasts:
        total += 1
        if _dec(getattr(f, "risk_score", 0)) >= _HIGH_RISK:
            high_risk += 1
        if _dec(getattr(f, "confidence", 1)) < _LOW_CONFIDENCE:
            low_conf += 1
    if total == 0 or (high_risk == 0 and low_conf == 0):
        return []
    flagged = max(high_risk, low_conf)
    severity = _clamp(Decimal(flagged) / Decimal(total))
    detail = (
        f"{high_risk}/{total} latest forecasts are high supply-risk and "
        f"{low_conf}/{total} are low-confidence — demand planning is exposed."
    )
    return [
        Finding(
            category="forecast",
            severity=severity,
            title="Forecast exposure",
            detail=detail,
            refs={"forecasts": total, "high_risk": high_risk, "low_confidence": low_conf},
            recommended_action="Tighten review on flagged SKUs; prefer Croston/seasonal where demand is irregular.",
        )
    ]


# Container fill below which a shipment is worth flagging as a consolidation
# opportunity; container findings are an efficiency concern, so their severity is
# capped below operational risks (stockout/expedite).
_CONTAINER_FILL_FLOOR = Decimal("0.85")
_CONTAINER_MAX_SEVERITY = Decimal("0.5")


def finding_from_container_usage(
    *,
    label: str,
    container_code: str,
    containers_needed: int,
    fill: Decimal,
    top_off_cartons: int,
) -> Finding | None:
    """Surface an under-utilised shipment as a (capped-severity) consolidation
    opportunity. ``fill`` is how full the binding dimension is (0..1). Returns None
    when there's nothing to ship or the container is already well filled. Pure: the
    caller (service) computes the plan with the container domain and passes
    primitives, so this stays decoupled from container types."""
    if containers_needed <= 0 or fill >= _CONTAINER_FILL_FLOOR:
        return None
    severity = min(_CONTAINER_MAX_SEVERITY, _clamp(ONE - fill))
    detail = (
        f"{label}: pending reorders ship as {containers_needed}×{container_code} "
        f"at {_q4(fill * 100)}% fill."
    )
    if top_off_cartons > 0:
        detail += f" ~{top_off_cartons} more cartons fit at no extra container."
    return Finding(
        category="container",
        severity=severity,
        title=f"Container under-utilised: {label}",
        detail=detail,
        refs={
            "container": container_code,
            "containers_needed": containers_needed,
            "fill": str(_q4(fill)),
            "top_off_cartons": top_off_cartons,
        },
        recommended_action="Consolidate shipments or top off to a fuller container before booking freight.",
    )


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def rank_findings(findings: list[Finding], *, limit: int = 12) -> list[Finding]:
    """Highest severity first (stable), capped to ``limit``."""
    ranked = sorted(findings, key=lambda f: f.severity, reverse=True)
    return ranked[:limit] if limit and limit > 0 else ranked


# Words in a question that point at a finding category — lets the deterministic
# advisor answer "which suppliers are risky?" / "what should I order?" without an LLM.
_QUESTION_KEYWORDS = {
    "reorder": {"order", "reorder", "buy", "purchase", "restock", "po", "stock", "stockout", "expedite"},
    "supplier_risk": {"supplier", "suppliers", "vendor", "vendors", "sourcing"},
    "supply_signal": {"signal", "signals", "risk", "risks", "disruption", "port", "tariff", "geopolitical", "commodity"},
    "forecast": {"forecast", "forecasts", "demand", "seasonal", "trend", "confidence"},
    "container": {"container", "containers", "ship", "shipping", "freight", "load", "consolidate", "fill", "carton", "cartons"},
}
_STOPWORDS = {
    "the", "a", "an", "what", "which", "should", "do", "is", "are", "my", "to", "of",
    "for", "how", "can", "me", "on", "and", "or", "this", "week", "now", "any", "we",
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS and len(t) > 1}


def select_relevant(context: AdvisoryContext, question: str, *, limit: int = 8) -> list[Finding]:
    """Findings most relevant to a free-text question, by category keyword + token
    overlap (deterministic, no LLM). Falls back to the general ranking when the
    question matches nothing — so the answer is never empty when findings exist."""
    q = _tokens(question or "")
    if not q:
        return rank_findings(context.findings, limit=limit)
    scored: list[tuple[int, Finding]] = []
    for f in context.findings:
        score = 2 if (q & _QUESTION_KEYWORDS.get(f.category, set())) else 0
        score += len(q & _tokens(f.title + " " + f.detail))
        if score > 0:
            scored.append((score, f))
    if not scored:
        return rank_findings(context.findings, limit=limit)
    scored.sort(key=lambda sf: (sf[0], sf[1].severity), reverse=True)
    return [f for _, f in scored[:limit]]


def build_context(
    *,
    reorder=(),
    signals=(),
    supplier_scores=(),
    forecasts=(),
    container_findings=(),
    now: dt.datetime | None = None,
    limit: int = 12,
) -> AdvisoryContext:
    """Assemble all real signals into a ranked, explainable ``AdvisoryContext``.

    ``container_findings`` are pre-built (the service computes shipment plans with the
    container domain); the other inputs are raw rows turned into findings here."""
    reorder = list(reorder)
    signals = list(signals)
    supplier_scores = list(supplier_scores)
    forecasts = list(forecasts)
    container_findings = list(container_findings)

    findings = (
        findings_from_reorder(reorder)
        + findings_from_signals(signals)
        + findings_from_supplier_scores(supplier_scores)
        + findings_from_forecasts(forecasts)
        + container_findings
    )
    expedite_count = sum(1 for r in reorder if bool(getattr(r, "expedite", False)))
    metrics = {
        "reorder_pending": len(reorder),
        "reorder_expedite": expedite_count,
        "active_signals": len(signals),
        "supplier_scores": len(supplier_scores),
        "forecasts": len(forecasts),
        "container_findings": len(container_findings),
        "findings_total": len(findings),
    }
    ranked = rank_findings(findings, limit=limit)
    summary = (
        f"{metrics['reorder_pending']} pending reorder(s) "
        f"({expedite_count} expedite), {len(signals)} active supply signal(s), "
        f"{len(supplier_scores)} supplier scorecard(s); {len(findings)} finding(s) surfaced."
    )
    return AdvisoryContext(
        generated_at=now or dt.datetime.now(dt.timezone.utc),
        findings=ranked,
        metrics=metrics,
        summary_line=summary,
    )
