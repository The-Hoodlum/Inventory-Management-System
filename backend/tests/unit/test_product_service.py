"""Unit tests for ProductService using in-memory fakes (no DB)."""
from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.schemas.product import ProductCreate, ProductUpdate
from app.services.product_service import ProductService


@pytest.fixture
def svc(fake_product_repo, fake_audit_repo):
    return ProductService(fake_product_repo, fake_audit_repo)


async def test_create_product_writes_audit(svc, fake_audit_repo):
    tid, uid = uuid.uuid4(), uuid.uuid4()
    product = await svc.create(
        tenant_id=tid, user_id=uid, data=ProductCreate(sku="SKU-1", name="Widget")
    )
    assert product.sku == "SKU-1"
    assert product.id is not None
    assert any(
        e["action"] == "create" and e["entity_type"] == "product"
        for e in fake_audit_repo.entries
    )


async def test_create_duplicate_sku_conflicts(svc):
    tid, uid = uuid.uuid4(), uuid.uuid4()
    await svc.create(tenant_id=tid, user_id=uid, data=ProductCreate(sku="DUP", name="A"))
    with pytest.raises(ConflictError):
        await svc.create(tenant_id=tid, user_id=uid, data=ProductCreate(sku="DUP", name="B"))


async def test_get_missing_raises_not_found(svc):
    with pytest.raises(NotFoundError):
        await svc.get(uuid.uuid4())


async def test_update_missing_raises_not_found(svc):
    with pytest.raises(NotFoundError):
        await svc.update(
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            data=ProductUpdate(name="X"),
        )


async def test_update_changes_fields_and_audits(svc, fake_audit_repo):
    tid, uid = uuid.uuid4(), uuid.uuid4()
    product = await svc.create(tenant_id=tid, user_id=uid, data=ProductCreate(sku="S", name="Old"))
    updated = await svc.update(
        tenant_id=tid, user_id=uid, product_id=product.id, data=ProductUpdate(name="New")
    )
    assert updated.name == "New"
    assert any(e["action"] == "update" for e in fake_audit_repo.entries)


async def test_soft_delete_audits(svc, fake_audit_repo):
    tid, uid = uuid.uuid4(), uuid.uuid4()
    product = await svc.create(tenant_id=tid, user_id=uid, data=ProductCreate(sku="S", name="N"))
    await svc.delete(tenant_id=tid, user_id=uid, product_id=product.id)
    assert product.deleted_at is not None
    assert any(e["action"] == "delete" for e in fake_audit_repo.entries)
