"""Unit tests for the order-request from->to schema + transfer-type classification."""
from __future__ import annotations

import uuid

import pytest

from app.order_requests.domain import status as S
from app.order_requests.schemas import OrderRequestCreate

SRC = uuid.uuid4()
DST = uuid.uuid4()
PID = uuid.uuid4()


def _line():
    return {"product_id": PID, "requested_qty": 2}


def test_transfer_types_are_the_managed_moves():
    assert S.TRANSFER_TYPES == {S.BRANCH_TRANSFER, S.INTERNAL_TRANSFER}


def test_explicit_source_and_destination_are_captured():
    c = OrderRequestCreate(
        source_location_id=SRC, destination_location_id=DST,
        purpose="branch_transfer", comments="rebalance", lines=[_line()],
    )
    assert c.source_location_id == SRC and c.destination_location_id == DST
    # legacy columns mirror the explicit fields (the DB stores these)
    assert c.branch_id == SRC and c.destination_branch_id == DST


def test_legacy_branch_id_alias_still_accepted():
    c = OrderRequestCreate(branch_id=SRC, purpose="shelf_replenishment", lines=[_line()])
    assert c.source_location_id == SRC and c.destination_location_id is None


def test_source_is_required():
    with pytest.raises(ValueError):
        OrderRequestCreate(purpose="shelf_replenishment", lines=[_line()])


def test_source_and_destination_must_differ():
    with pytest.raises(ValueError):
        OrderRequestCreate(
            source_location_id=SRC, destination_location_id=SRC,
            purpose="shelf_replenishment", lines=[_line()],
        )


def test_managed_transfer_needs_a_reason_but_a_restock_does_not():
    with pytest.raises(ValueError):
        OrderRequestCreate(
            source_location_id=SRC, destination_location_id=DST,
            purpose="branch_transfer", lines=[_line()],  # no comments
        )
    # a routine restock to a destination needs no reason
    ok = OrderRequestCreate(
        source_location_id=SRC, destination_location_id=DST,
        purpose="shelf_replenishment", lines=[_line()],
    )
    assert ok.destination_location_id == DST
