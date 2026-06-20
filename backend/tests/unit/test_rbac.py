"""Unit tests for the RBAC permission check."""
from __future__ import annotations

import pytest

from app.api.v1.deps import ensure_permission
from app.core.exceptions import PermissionDeniedError
from app.core.permissions import P


def test_allows_when_permission_present():
    # Should not raise.
    ensure_permission({P.PRODUCT_READ, P.PRODUCT_CREATE}, P.PRODUCT_READ)


def test_denies_when_permission_absent():
    with pytest.raises(PermissionDeniedError):
        ensure_permission({P.PRODUCT_READ}, P.PRODUCT_DELETE)


def test_denies_on_empty_permission_set():
    with pytest.raises(PermissionDeniedError):
        ensure_permission(set(), P.INVENTORY_RECEIVE)
