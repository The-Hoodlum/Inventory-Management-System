"""Deterministic forecast-confidence score (pure; no ML, fully auditable).

Confidence answers: *how much should a human trust this forecast?* It is a value
in [0, 1] combining two intuitive, independent factors:

  sufficiency   Do we have enough history? Ramps linearly from 0 to 1 as the
                number of observed days approaches ``target_observations``.

  stability     Is demand steady or erratic? Derived from the coefficient of
                variation (CV = std / mean): steady demand (low CV) -> ~1,
                volatile/intermittent demand (high CV) -> ->0, via 1 / (1 + CV).

        confidence = sufficiency x stability

A series with no demand signal (mean <= 0) has zero confidence — there is nothing
to forecast. The score is intentionally conservative: short history or spiky
demand both pull it down, which is exactly when a planner should apply judgement.

Kept dependency-free (its own mean/std) so it cannot create an import cycle with
``methods`` and stays trivially unit-testable.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
ONE = Decimal("1")
_Q4 = Decimal("0.0001")

DEFAULT_TARGET_OBSERVATIONS = 60  # ~2 months of daily history for full sufficiency


def _mean(series: list[Decimal]) -> Decimal:
    if not series:
        return ZERO
    return sum(series, ZERO) / Decimal(len(series))


def _population_std(series: list[Decimal], m: Decimal) -> Decimal:
    n = len(series)
    if n == 0:
        return ZERO
    var = sum(((x - m) * (x - m) for x in series), ZERO) / Decimal(n)
    if var < 0:
        var = ZERO
    return var.sqrt()


def forecast_confidence(
    series: list[Decimal], *, target_observations: int = DEFAULT_TARGET_OBSERVATIONS
) -> Decimal:
    """Return a confidence score in [0, 1], quantised to 4 dp."""
    n = len(series)
    if n == 0:
        return ZERO
    m = _mean(series)
    if m <= 0:
        return ZERO  # no demand signal to forecast

    target = Decimal(target_observations if target_observations > 0 else 1)
    sufficiency = min(ONE, Decimal(n) / target)

    cv = _population_std(series, m) / m
    stability = ONE / (ONE + cv)

    score = sufficiency * stability
    if score < 0:
        score = ZERO
    if score > 1:
        score = ONE
    return score.quantize(_Q4, rounding=ROUND_HALF_UP)
