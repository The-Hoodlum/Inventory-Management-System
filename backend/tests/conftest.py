"""Shared pytest fixtures and in-memory fakes.

These let the service layer be unit-tested without a database: the repositories
are replaced by lightweight fakes, and inventory rows are plain namespaces. The
services compute availability locally, so no DB-generated columns are needed.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest


class _FakeSession:
    async def flush(self) -> None:  # services call repo.session.flush()
        return None


class FakeAuditRepo:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def add(self, **kwargs: Any):
        self.entries.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4(), **kwargs)


class FakeProductRepo:
    """Full fake for ProductService tests."""

    model = None

    def __init__(self) -> None:
        self.session = _FakeSession()
        self._by_id: dict[uuid.UUID, Any] = {}
        self._by_sku: dict[str, Any] = {}

    def _store(self, p: Any) -> None:
        self._by_id[p.id] = p
        self._by_sku[p.sku] = p

    async def get(self, product_id: uuid.UUID):
        p = self._by_id.get(product_id)
        if p is not None and getattr(p, "deleted_at", None) is not None:
            return None
        return p

    async def get_by_sku(self, sku: str):
        p = self._by_sku.get(sku)
        if p is not None and getattr(p, "deleted_at", None) is not None:
            return None
        return p

    async def add(self, product: Any):
        if getattr(product, "id", None) is None:
            product.id = uuid.uuid4()
        self._store(product)
        return product

    async def list(self, **kwargs: Any):
        items = [p for p in self._by_id.values() if getattr(p, "deleted_at", None) is None]
        return items, len(items)


class FakeLookup:
    """Minimal repo exposing only ``get`` — for product/warehouse existence checks."""

    def __init__(self, known_ids: set[uuid.UUID]) -> None:
        self._known = set(known_ids)

    async def get(self, entity_id: uuid.UUID):
        return SimpleNamespace(id=entity_id) if entity_id in self._known else None


class FakeInventoryRepo:
    def __init__(self) -> None:
        self._rows: dict[tuple[uuid.UUID, uuid.UUID], Any] = {}
        self.movements: list[Any] = []

    def seed(self, product_id, warehouse_id, on_hand, reserved=0, damaged=0, version=0, tenant_id=None):
        inv = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id or uuid.uuid4(),
            product_id=product_id,
            warehouse_id=warehouse_id,
            qty_on_hand=Decimal(str(on_hand)),
            qty_reserved=Decimal(str(reserved)),
            qty_damaged=Decimal(str(damaged)),
            version=version,
        )
        self._rows[(product_id, warehouse_id)] = inv
        return inv

    async def get(self, product_id, warehouse_id):
        return self._rows.get((product_id, warehouse_id))

    async def get_for_update(self, product_id, warehouse_id):
        return self._rows.get((product_id, warehouse_id))

    async def create(self, tenant_id, product_id, warehouse_id):
        inv = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            qty_on_hand=Decimal("0"),
            qty_reserved=Decimal("0"),
            qty_damaged=Decimal("0"),
            version=0,
        )
        self._rows[(product_id, warehouse_id)] = inv
        return inv

    async def add_movement(self, **fields: Any):
        mv = SimpleNamespace(id=uuid.uuid4(), **fields)
        self.movements.append(mv)
        return mv

    async def list_inventory(self, **kwargs: Any):
        rows = list(self._rows.values())
        return rows, len(rows)

    async def list_movements(self, **kwargs: Any):
        return list(self.movements), len(self.movements)


# --------------------------------- fixtures --------------------------------- #
@pytest.fixture
def ids() -> SimpleNamespace:
    return SimpleNamespace(
        tenant=uuid.uuid4(),
        user=uuid.uuid4(),
        p1=uuid.uuid4(),
        wh1=uuid.uuid4(),
        wh2=uuid.uuid4(),
    )


@pytest.fixture
def fake_audit_repo() -> FakeAuditRepo:
    return FakeAuditRepo()


@pytest.fixture
def fake_product_repo() -> FakeProductRepo:
    return FakeProductRepo()


@pytest.fixture
def fake_inventory_repo() -> FakeInventoryRepo:
    return FakeInventoryRepo()


@pytest.fixture
def inv_service(fake_inventory_repo, fake_audit_repo, ids):
    from app.services.inventory_service import InventoryService

    products = FakeLookup({ids.p1})
    warehouses = FakeLookup({ids.wh1, ids.wh2})
    return InventoryService(fake_inventory_repo, products, warehouses, fake_audit_repo)
