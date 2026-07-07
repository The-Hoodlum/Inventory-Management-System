"""Unit tests for the server-side branch-scope resolver (the Lusaka-sees-Solwezi boundary)."""
from __future__ import annotations

import uuid

import pytest

from app.api.v1.deps import CurrentUser, resolve_branch_scope, resolve_warehouse_scope
from app.core.exceptions import PermissionDeniedError

LUSAKA = uuid.uuid4()
SOLWEZI = uuid.uuid4()
NDOLA = uuid.uuid4()


def _user(branch_ids) -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@x", full_name="U",
        branch_ids=frozenset(branch_ids),
    )


def test_unrestricted_user_sees_all_or_the_requested_branch():
    admin = _user([])           # no grants = all branches
    assert admin.all_branches is True
    assert resolve_branch_scope(admin, None) is None          # no filter -> all
    assert resolve_branch_scope(admin, LUSAKA) == [LUSAKA]    # honour a specific pick


def test_scoped_user_with_no_filter_is_confined_to_their_branches():
    lusaka_user = _user([LUSAKA])
    assert resolve_branch_scope(lusaka_user, None) == [LUSAKA]  # NEVER None (never all)
    multi = _user([LUSAKA, NDOLA])
    assert set(resolve_branch_scope(multi, None)) == {LUSAKA, NDOLA}


def test_scoped_user_may_pick_their_own_branch():
    lusaka_user = _user([LUSAKA])
    assert resolve_branch_scope(lusaka_user, LUSAKA) == [LUSAKA]


def test_scoped_user_is_rejected_for_another_branch():
    lusaka_user = _user([LUSAKA])
    with pytest.raises(PermissionDeniedError):
        resolve_branch_scope(lusaka_user, SOLWEZI)   # the core bug: must be rejected


# --- warehouse-scope resolver (inventory/movements) --- #
WH_LUSAKA = uuid.uuid4()
WH_SOLWEZI = uuid.uuid4()


class _FakeWarehouses:
    """Only WH_LUSAKA belongs to the LUSAKA branch."""

    async def ids_in_branches(self, branch_ids):
        return {WH_LUSAKA} if LUSAKA in set(branch_ids) else set()


async def test_warehouse_scope_unrestricted_user():
    admin = _user([])
    assert await resolve_warehouse_scope(admin, None, _FakeWarehouses()) is None
    assert await resolve_warehouse_scope(admin, WH_SOLWEZI, _FakeWarehouses()) == [WH_SOLWEZI]


async def test_warehouse_scope_confines_and_rejects():
    lusaka_user = _user([LUSAKA])
    # no filter -> only the user's branch warehouses
    assert await resolve_warehouse_scope(lusaka_user, None, _FakeWarehouses()) == [WH_LUSAKA]
    # their own warehouse is allowed
    assert await resolve_warehouse_scope(lusaka_user, WH_LUSAKA, _FakeWarehouses()) == [WH_LUSAKA]
    # a warehouse in another branch is rejected
    with pytest.raises(PermissionDeniedError):
        await resolve_warehouse_scope(lusaka_user, WH_SOLWEZI, _FakeWarehouses())
