"""Unit tests for the pure container load-planning domain."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.container.domain.planning import (
    CONTAINER_20GP,
    LoadItem,
    additional_cartons_that_fit,
    aggregate,
    get_container,
    plan,
    recommend_container,
)

D = Decimal


def _items(ref_qty_vol_wt):
    return [
        LoadItem(ref=r, cartons=c, volume_per_carton_m3=D(v), weight_per_carton_kg=D(w))
        for (r, c, v, w) in ref_qty_vol_wt
    ]


# ------------------------------ specs ------------------------------------- #
def test_get_container_known_and_unknown():
    assert get_container("20GP").label == "20ft Standard"
    with pytest.raises(ValueError):
        get_container("NOPE")


# ------------------------------ aggregate --------------------------------- #
def test_aggregate_sums_volume_weight_and_cartons():
    items = _items([("A", 10, "0.5", "8"), ("B", 5, "0.2", "3")])
    total_v, total_w, total_c = aggregate(items)
    assert total_v == D("6.0")        # 10*0.5 + 5*0.2
    assert total_w == D("95")         # 10*8 + 5*3
    assert total_c == 15


# -------------------------------- plan ------------------------------------ #
def test_plan_empty_load():
    p = plan(CONTAINER_20GP, [])
    assert p.is_empty
    assert p.containers_needed == 0
    assert p.binding_constraint == "none"


def test_plan_volume_bound():
    # 100 light bulky cartons: volume fills out, weight barely registers.
    # 20GP usable = 33.2 * 0.90 = 29.88 m³ ; payload 28200 kg
    p = plan(CONTAINER_20GP, _items([("A", 100, "0.5", "10")]))
    assert p.total_volume_m3 == D("50.000000")
    assert p.total_weight_kg == D("1000.0000")
    assert p.containers_needed == 2                 # ceil(50/29.88)=2 vs ceil(1000/28200)=1
    assert p.binding_constraint == "volume"
    assert p.volume_utilization == D("0.8367")      # 50 / (29.88*2)
    assert p.spare_volume_m3 == D("9.760000")       # 59.76 - 50


def test_plan_weight_bound():
    # 100 dense cartons: weight fills out long before volume.
    p = plan(CONTAINER_20GP, _items([("A", 100, "0.1", "400")]))
    assert p.containers_needed == 2                 # ceil(40000/28200)=2 vs ceil(10/29.88)=1
    assert p.binding_constraint == "weight"
    assert p.weight_utilization == D("0.7092")      # 40000 / (28200*2)


def test_plan_utilizations_are_fractions_in_unit_range():
    p = plan(CONTAINER_20GP, _items([("A", 40, "0.5", "100")]))
    assert D("0") <= p.volume_utilization <= D("1")
    assert D("0") <= p.weight_utilization <= D("1")


# --------------------------- recommend_container -------------------------- #
def test_recommend_small_order_prefers_smallest_container():
    # Fits in one of any type; the 20GP is the fullest (least wasted space).
    p = recommend_container(_items([("A", 20, "0.5", "10")]))
    assert p.container_code == "20GP"
    assert p.containers_needed == 1


def test_recommend_large_order_prefers_fewer_better_filled_containers():
    # Needs 4×20GP but only 2×40GP / 2×40HC; 40GP packs the fullest of the two.
    p = recommend_container(_items([("A", 200, "0.5", "10")]))
    assert p.container_code == "40GP"
    assert p.containers_needed == 2


def test_recommend_empty_is_empty_plan():
    p = recommend_container([])
    assert p.is_empty


# ----------------------- additional_cartons_that_fit ---------------------- #
def test_additional_cartons_bounded_by_spare_volume():
    # From the volume-bound plan: spare volume 9.76 m³, spare weight 55400 kg.
    # 0.5 m³ cartons -> floor(9.76/0.5)=19 fit by volume (weight is not the limit).
    p = plan(CONTAINER_20GP, _items([("A", 100, "0.5", "10")]))
    fit = additional_cartons_that_fit(
        p, volume_per_carton_m3=D("0.5"), weight_per_carton_kg=D("10")
    )
    assert fit == 19


def test_additional_cartons_bounded_by_spare_weight():
    # Weight-bound plan: heavy cartons run out of payload before volume.
    p = plan(CONTAINER_20GP, _items([("A", 100, "0.1", "400")]))
    fit = additional_cartons_that_fit(
        p, volume_per_carton_m3=D("0.1"), weight_per_carton_kg=D("400")
    )
    # spare weight = 56400 - 40000 = 16400 -> floor(16400/400)=41 ;
    # spare volume = 59.76 - 10 = 49.76 -> floor(49.76/0.1)=497 ; min -> 41
    assert fit == 41
