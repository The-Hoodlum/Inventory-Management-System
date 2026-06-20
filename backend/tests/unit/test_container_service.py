"""Unit tests for ContainerService using an in-memory fake repository."""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.container.schemas import (
    ContainerPlanRequest,
    PlanLineInput,
    RecommendationPlanRequest,
)
from app.container.service import ContainerService
from app.core.exceptions import BusinessRuleError

D = Decimal


def _product(*, sku, vol, wt, upc=1, moq=0):
    return SimpleNamespace(
        id=uuid.uuid4(), sku=sku,
        volume_per_carton=(D(vol) if vol is not None else None),
        weight_per_carton=(D(wt) if wt is not None else None),
        units_per_carton=upc, moq=moq,
    )


def _rec(product_id, *, cartons, qty):
    return SimpleNamespace(
        id=uuid.uuid4(), product_id=product_id,
        recommended_cartons=cartons, recommended_qty=D(qty),
    )


class FakeContainerRepo:
    def __init__(self, products, recommendations=None):
        self._p = {p.id: p for p in products}
        self._recs = {r.id: r for r in (recommendations or [])}

    async def load_products(self, ids):
        return {i: self._p[i] for i in ids if i in self._p}

    async def load_recommendations(self, ids):
        return [self._recs[i] for i in ids if i in self._recs]


def _svc(products):
    return ContainerService(FakeContainerRepo(products))


def test_containers_lists_standard_specs():
    svc = _svc([])
    codes = {c.code for c in svc.containers()}
    assert {"20GP", "40GP", "40HC"} == codes


async def test_plan_explicit_container_volume_bound():
    p = _product(sku="BULKY", vol="0.5", wt="10")
    svc = _svc([p])
    resp = await svc.plan(
        req=ContainerPlanRequest(
            lines=[PlanLineInput(product_id=p.id, cartons=100)], container_code="20GP"
        )
    )
    assert resp.container_code == "20GP"
    assert resp.containers_needed == 2
    assert resp.binding_constraint == "volume"
    assert resp.total_volume_m3 == D("50.000000")
    assert resp.lines[0].sku == "BULKY"
    assert resp.lines[0].cartons == 100


async def test_plan_converts_units_to_whole_cartons():
    p = _product(sku="U", vol="0.1", wt="2", upc=10)
    svc = _svc([p])
    resp = await svc.plan(
        req=ContainerPlanRequest(lines=[PlanLineInput(product_id=p.id, units=95)])
    )
    # ceil(95 / 10) = 10 cartons
    assert resp.lines[0].cartons == 10


async def test_plan_recommends_smallest_container_for_small_order():
    p = _product(sku="S", vol="0.5", wt="10")
    svc = _svc([p])
    resp = await svc.plan(
        req=ContainerPlanRequest(lines=[PlanLineInput(product_id=p.id, cartons=20)])
    )
    assert resp.container_code == "20GP"
    assert resp.containers_needed == 1


async def test_plan_skips_products_without_dimensions():
    good = _product(sku="GOOD", vol="0.5", wt="10")
    bad = _product(sku="NODIMS", vol=None, wt=None)
    svc = _svc([good, bad])
    resp = await svc.plan(
        req=ContainerPlanRequest(
            lines=[
                PlanLineInput(product_id=good.id, cartons=10),
                PlanLineInput(product_id=bad.id, cartons=10),
            ]
        )
    )
    assert resp.skipped_product_ids == [bad.id]
    assert len(resp.lines) == 1


async def test_plan_raises_when_no_plannable_lines():
    bad = _product(sku="NODIMS", vol=None, wt=None)
    svc = _svc([bad])
    with pytest.raises(BusinessRuleError):
        await svc.plan(
            req=ContainerPlanRequest(lines=[PlanLineInput(product_id=bad.id, cartons=5)])
        )


async def test_plan_from_recommendations_uses_recommended_cartons():
    p = _product(sku="R", vol="0.5", wt="10")
    rec = _rec(p.id, cartons=100, qty="5000")
    svc = ContainerService(FakeContainerRepo([p], recommendations=[rec]))
    resp = await svc.plan_from_recommendations(
        req=RecommendationPlanRequest(recommendation_ids=[rec.id], container_code="20GP")
    )
    assert resp.lines[0].sku == "R"
    assert resp.lines[0].cartons == 100
    assert resp.containers_needed == 2          # 100 * 0.5 = 50 m³ -> 2 × 20GP


async def test_plan_from_recommendations_falls_back_to_qty_over_units_per_carton():
    p = _product(sku="F", vol="0.5", wt="10", upc=10)
    rec = _rec(p.id, cartons=0, qty="95")       # no carton count -> derive from qty
    svc = ContainerService(FakeContainerRepo([p], recommendations=[rec]))
    resp = await svc.plan_from_recommendations(
        req=RecommendationPlanRequest(recommendation_ids=[rec.id])
    )
    assert resp.lines[0].cartons == 10          # ceil(95 / 10)


async def test_plan_top_off_reports_spare_capacity_with_moq_note():
    p = _product(sku="TOP", vol="0.5", wt="10", upc=4, moq=1000)
    svc = _svc([p])
    resp = await svc.plan(
        req=ContainerPlanRequest(
            lines=[PlanLineInput(product_id=p.id, cartons=100)], container_code="20GP"
        )
    )
    assert resp.top_off is not None
    assert resp.top_off.sku == "TOP"
    assert resp.top_off.additional_cartons == 19      # spare volume 9.76 / 0.5
    assert resp.top_off.additional_units == 76        # 19 * 4
    assert resp.top_off.moq_shortfall == 924          # 1000 - 76
