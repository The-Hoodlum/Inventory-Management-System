"""Forecast-vs-actual accuracy metrics (pure functions, ``Decimal`` math).

Given pairs of (forecast, actual) demand, compute the standard error measures
used to judge and compare forecasting methods over time:

  MAE   mean absolute error            mean(|f - a|)              units
  BIAS  mean error (signed)            mean(f - a)                units  (+ = over-forecast)
  RMSE  root mean squared error        sqrt(mean((f - a)^2))      units
  MAPE  mean absolute percentage error mean(|f - a| / a)  over a > 0   fraction (0.10 = 10%)

MAPE only averages over periods with non-zero actuals (it is undefined when the
actual is zero); ``mape_points`` reports how many pairs contributed so callers
can judge its reliability. All metrics are ``None`` when there are no usable
inputs, never a misleading zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
_Q4 = Decimal("0.0001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class AccuracyResult:
    n: int                       # number of (forecast, actual) pairs
    mae: Decimal | None
    bias: Decimal | None
    rmse: Decimal | None
    mape: Decimal | None         # fraction; None if no non-zero actuals
    mape_points: int             # pairs that contributed to MAPE


def forecast_accuracy(pairs: list[tuple[Decimal, Decimal]]) -> AccuracyResult:
    """Aggregate accuracy metrics over (forecast, actual) pairs."""
    n = len(pairs)
    if n == 0:
        return AccuracyResult(n=0, mae=None, bias=None, rmse=None, mape=None, mape_points=0)

    abs_err = ZERO
    signed_err = ZERO
    sq_err = ZERO
    pct_err = ZERO
    pct_points = 0

    for f, a in pairs:
        f = Decimal(f)
        a = Decimal(a)
        err = f - a
        abs_err += abs(err)
        signed_err += err
        sq_err += err * err
        if a > 0:
            pct_err += abs(err) / a
            pct_points += 1

    n_dec = Decimal(n)
    mape = _q(pct_err / Decimal(pct_points)) if pct_points else None
    return AccuracyResult(
        n=n,
        mae=_q(abs_err / n_dec),
        bias=_q(signed_err / n_dec),
        rmse=_q((sq_err / n_dec).sqrt()),
        mape=mape,
        mape_points=pct_points,
    )
