"""TenantSettingsService: editing the USD->billing rate writes a dedicated
old->new audit entry; unrelated edits (or a no-op rate) do not."""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.tenant import TenantSettingsUpdate
from app.services.tenant_service import TenantSettingsService


def _tenant(fx: str) -> SimpleNamespace:
    return SimpleNamespace(
        name="ACME", brand_name=None, industry=None, base_currency="USD",
        fx_rate=Decimal(fx), country=None, timezone="UTC", logo_url=None,
        branding_colors={}, assistant_name=None, assistant_prompt=None, feature_flags={},
    )


def _service(before: SimpleNamespace, after: SimpleNamespace):
    tenants = SimpleNamespace(
        get=AsyncMock(return_value=before),
        update=AsyncMock(return_value=after),
    )
    audit = SimpleNamespace(add=AsyncMock())
    return TenantSettingsService(tenants, audit), audit


def _fx_audits(audit) -> list[dict]:
    return [c.kwargs for c in audit.add.await_args_list if c.kwargs.get("action") == "tenant.fx_rate.update"]


@pytest.mark.asyncio
async def test_rate_change_writes_old_new_audit():
    tid, actor = uuid.uuid4(), uuid.uuid4()
    svc, audit = _service(_tenant("20"), _tenant("25.5"))
    await svc.update_settings(tid, TenantSettingsUpdate(fx_rate=Decimal("25.5")), actor_id=actor)
    fx = _fx_audits(audit)
    assert len(fx) == 1
    assert fx[0]["changes"] == {"old": "20", "new": "25.5"}
    assert fx[0]["user_id"] == actor and fx[0]["entity_type"] == "tenant"


@pytest.mark.asyncio
async def test_unrelated_edit_does_not_write_fx_audit():
    svc, audit = _service(_tenant("20"), _tenant("20"))
    await svc.update_settings(uuid.uuid4(), TenantSettingsUpdate(company_name="New Co"), actor_id=uuid.uuid4())
    assert _fx_audits(audit) == []


@pytest.mark.asyncio
async def test_noop_rate_write_does_not_audit_a_change():
    # Submitting the same rate mustn't fabricate a change record.
    svc, audit = _service(_tenant("20"), _tenant("20"))
    await svc.update_settings(uuid.uuid4(), TenantSettingsUpdate(fx_rate=Decimal("20")), actor_id=uuid.uuid4())
    assert _fx_audits(audit) == []
