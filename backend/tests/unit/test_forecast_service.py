"""Unit tests for ForecastService using in-memory fakes (no database)."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.forecast.domain.exceptions import InvalidForecastInput
from app.forecast.domain.models import DemandPoint
from app.forecast.schemas import ForecastRunRequest
from app.forecast.service import ForecastService

D = Decimal


class FakeForecastRepo:
    def __init__(self, active_product_ids=None):
        self.saved: list = []
        self._by_id: dict = {}
        self._active = active_product_ids or []

    async def save(self, **fields):
        rec = SimpleNamespace(
            id=uuid.uuid4(), generated_at=dt.datetime.now(dt.timezone.utc), **fields
        )
        self.saved.append(rec)
        self._by_id[rec.id] = rec
        return rec

    async def get(self, forecast_id):
        return self._by_id.get(forecast_id)

    async def list(self, **kwargs):
        return list(self.saved), len(self.saved)

    async def list_active_product_ids(self):
        return list(self._active)

    async def latest_per_pair(self):
        return list(self.saved)

    async def count_all(self):
        return len(self.saved)


class FakeDemandRepo:
    def __init__(self, series_map=None):
        self.series_map = series_map or {}

    async def daily_series(self, *, product_id, warehouse_id, start_date, end_date):
        return self.series_map.get((product_id, warehouse_id), [])


def _steady_series(end_day: dt.date, days: int, qty: str) -> list[DemandPoint]:
    return [DemandPoint(day=end_day - dt.timedelta(days=i), quantity=D(qty)) for i in range(days)]


async def test_run_single_product_persists_and_audits(fake_audit_repo):
    wh = uuid.uuid4()
    product = uuid.uuid4()
    today = dt.date.today()
    demand = FakeDemandRepo({(product, wh): _steady_series(today, 10, "10")})
    repo = FakeForecastRepo()
    svc = ForecastService(repo, demand, fake_audit_repo)

    resp = await svc.run(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=ForecastRunRequest(warehouse_id=wh, product_id=product, window_days=10),
        ip=None,
    )

    assert resp.generated == 1
    assert resp.method == "moving_average"
    f = resp.forecasts[0]
    assert f.daily_demand == D("10.0000")
    assert f.adjusted_daily_demand == D("10.0000")  # no signals -> equal to base
    assert f.observations == 10 and f.days_with_demand == 10
    assert f.forecast_date == today + dt.timedelta(days=1)
    assert len(repo.saved) == 1
    assert any(e["action"] == "forecast.run" for e in fake_audit_repo.entries)


async def test_run_bulk_forecasts_every_active_product(fake_audit_repo):
    wh = uuid.uuid4()
    p1, p2 = uuid.uuid4(), uuid.uuid4()
    today = dt.date.today()
    demand = FakeDemandRepo({
        (p1, wh): _steady_series(today, 30, "4"),
        (p2, wh): _steady_series(today, 30, "7"),
    })
    repo = FakeForecastRepo(active_product_ids=[p1, p2])
    svc = ForecastService(repo, demand, fake_audit_repo)

    resp = await svc.run(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=ForecastRunRequest(warehouse_id=wh, window_days=30),  # no product_id -> bulk
        ip=None,
    )
    assert resp.generated == 2
    dailies = {f.product_id: f.daily_demand for f in resp.forecasts}
    assert dailies[p1] == D("4.0000")
    assert dailies[p2] == D("7.0000")


async def test_run_unknown_method_raises(fake_audit_repo):
    svc = ForecastService(FakeForecastRepo(), FakeDemandRepo(), fake_audit_repo)
    with pytest.raises(InvalidForecastInput):
        await svc.run(
            tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
            req=ForecastRunRequest(warehouse_id=uuid.uuid4(), product_id=uuid.uuid4(), method="nope"),
            ip=None,
        )


async def test_accuracy_compares_forecast_to_actuals(fake_audit_repo):
    wh, product = uuid.uuid4(), uuid.uuid4()
    today = dt.date.today()
    forecast_date = today - dt.timedelta(days=5)
    # actuals for the 3 elapsed horizon days: 10, 8, 12
    actuals = [
        DemandPoint(day=forecast_date, quantity=D("10")),
        DemandPoint(day=forecast_date + dt.timedelta(days=1), quantity=D("8")),
        DemandPoint(day=forecast_date + dt.timedelta(days=2), quantity=D("12")),
    ]
    demand = FakeDemandRepo({(product, wh): actuals})
    repo = FakeForecastRepo()
    saved = await repo.save(
        tenant_id=uuid.uuid4(), product_id=product, warehouse_id=wh, method="moving_average",
        window_days=90, horizon_days=3, forecast_date=forecast_date,
        daily_demand=D("10"), adjusted_daily_demand=D("10"), std_dev_daily=D("0"),
        confidence=D("0.8"), risk_score=D("0"), observations=90, days_with_demand=80,
        total_demand=D("900"), params={}, generated_by=uuid.uuid4(),
    )
    svc = ForecastService(repo, demand, fake_audit_repo)

    acc = await svc.accuracy(saved.id)
    assert acc.evaluated_days == 3
    assert acc.mae == D("1.3333")     # |0| + |2| + |2| over 3
    assert acc.bias == D("0.0000")    # (0 + 2 - 2) / 3


async def test_summary_aggregates_latest_forecasts(fake_audit_repo):
    wh = uuid.uuid4()
    repo = FakeForecastRepo()
    for conf, risk, method in [("0.9", "0.1", "moving_average"), ("0.5", "0.6", "exponential_smoothing")]:
        await repo.save(
            tenant_id=uuid.uuid4(), product_id=uuid.uuid4(), warehouse_id=wh, method=method,
            window_days=90, horizon_days=30, forecast_date=dt.date.today(),
            daily_demand=D("5"), adjusted_daily_demand=D("5"), std_dev_daily=D("1"),
            confidence=D(conf), risk_score=D(risk), observations=90, days_with_demand=80,
            total_demand=D("450"), params={}, generated_by=uuid.uuid4(),
        )
    svc = ForecastService(repo, FakeDemandRepo(), fake_audit_repo)

    summary = await svc.summary()
    assert summary.pairs_forecasted == 2
    assert summary.total_forecasts == 2
    assert summary.avg_confidence == D("0.7000")
    assert summary.high_risk_count == 1               # risk 0.6 >= 0.5
    assert summary.by_method == {"moving_average": 1, "exponential_smoothing": 1}


def test_providers_lists_builtins_and_auto(fake_audit_repo):
    svc = ForecastService(FakeForecastRepo(), FakeDemandRepo(), fake_audit_repo)
    keys = {p.key for p in svc.providers()}
    assert {"moving_average", "exponential_smoothing", "croston", "seasonal", "auto"} <= keys


def _intermittent(end_day: dt.date) -> list[DemandPoint]:
    # demand of 10 every 5th day over a 30-day window -> intermittent
    return [DemandPoint(day=end_day - dt.timedelta(days=k), quantity=D("10")) for k in (0, 5, 10, 15, 20, 25)]


async def test_run_auto_selects_method_per_product(fake_audit_repo):
    wh = uuid.uuid4()
    steady_p, intermittent_p = uuid.uuid4(), uuid.uuid4()
    today = dt.date.today()
    demand = FakeDemandRepo({
        (steady_p, wh): _steady_series(today, 30, "5"),   # smooth -> moving_average
        (intermittent_p, wh): _intermittent(today),       # sparse -> croston
    })
    repo = FakeForecastRepo(active_product_ids=[steady_p, intermittent_p])
    svc = ForecastService(repo, demand, fake_audit_repo)

    resp = await svc.run(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        req=ForecastRunRequest(warehouse_id=wh, method="auto", window_days=30),
        ip=None,
    )
    assert resp.method == "auto"
    methods = {f.product_id: f.method for f in resp.forecasts}
    assert methods[steady_p] == "moving_average"
    assert methods[intermittent_p] == "croston"


async def test_analyze_demand_returns_detected_pattern(fake_audit_repo):
    wh, product = uuid.uuid4(), uuid.uuid4()
    today = dt.date.today()
    demand = FakeDemandRepo({(product, wh): _intermittent(today)})
    svc = ForecastService(FakeForecastRepo(), demand, fake_audit_repo)

    resp = await svc.analyze_demand(product_id=product, warehouse_id=wh, window_days=30)
    assert resp.observations == 30
    assert resp.days_with_demand == 6
    assert resp.classification == "intermittent"
    assert resp.suggested_demand_type == "intermittent"
    assert resp.suggested_method == "croston"
    assert resp.drivers  # non-empty explanation
