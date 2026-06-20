"""Unit tests for forecast-vs-actual accuracy metrics."""
from __future__ import annotations

from decimal import Decimal

from app.forecast.domain.accuracy import forecast_accuracy

D = Decimal


def test_no_pairs_returns_all_none():
    r = forecast_accuracy([])
    assert r.n == 0
    assert r.mae is None and r.bias is None and r.rmse is None and r.mape is None
    assert r.mape_points == 0


def test_perfect_forecast_has_zero_error():
    r = forecast_accuracy([(D("10"), D("10")), (D("5"), D("5"))])
    assert r.mae == D("0.0000")
    assert r.bias == D("0.0000")
    assert r.rmse == D("0.0000")
    assert r.mape == D("0.0000")
    assert r.mape_points == 2


def test_known_errors():
    # errors: +2, -4  -> |e|: 2,4 (MAE 3) ; signed: -2/2 = -1 (under-forecast)
    # squared: 4,16 -> mean 10 -> rmse sqrt(10) ~ 3.1623
    # MAPE: 2/8 + 4/4 = 0.25 + 1.0 = 1.25 / 2 = 0.625
    pairs = [(D("10"), D("8")), (D("0"), D("4"))]
    r = forecast_accuracy(pairs)
    assert r.mae == D("3.0000")
    assert r.bias == D("-1.0000")
    assert r.rmse == D("3.1623")
    assert r.mape == D("0.6250")
    assert r.mape_points == 2


def test_mape_skips_zero_actuals():
    # second pair has actual 0 -> excluded from MAPE but counted elsewhere
    pairs = [(D("12"), D("10")), (D("3"), D("0"))]
    r = forecast_accuracy(pairs)
    assert r.n == 2
    assert r.mape_points == 1
    assert r.mape == D("0.2000")  # |12-10|/10 = 0.2 over the single usable pair


def test_mape_none_when_all_actuals_zero():
    r = forecast_accuracy([(D("3"), D("0")), (D("1"), D("0"))])
    assert r.mape is None
    assert r.mape_points == 0
    assert r.mae == D("2.0000")  # other metrics still computed
