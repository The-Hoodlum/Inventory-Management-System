"""Role-based tool access (pure)."""
from __future__ import annotations

from app.assistant.domain.capabilities import allowed_tools
from app.assistant.domain.tools import TOOL_NAMES


def test_admin_gets_everything():
    assert allowed_tools(["Admin"]) == TOOL_NAMES


def test_unrestricted_role_gets_everything():
    # Branch Manager / managers / Viewer are unrestricted at the tool level.
    assert allowed_tools(["Branch Manager"]) == TOOL_NAMES
    assert allowed_tools(["Warehouse Manager"]) == TOOL_NAMES


def test_no_roles_gets_nothing():
    assert allowed_tools([]) == frozenset()
    assert allowed_tools(None) == frozenset()


def test_cashier_is_stock_and_sales_only():
    tools = allowed_tools(["Cashier"])
    assert "get_stock_level" in tools
    assert "get_sales_report" in tools
    assert "get_inventory_valuation" not in tools
    assert "get_reorder_recommendations" not in tools
    assert tools <= TOOL_NAMES  # never exposes a non-existent tool


def test_mechanic_is_parts_and_service_only():
    tools = allowed_tools(["Mechanic"])
    assert "get_stock_level" in tools
    assert "get_assembly_status" in tools
    assert "get_sales_report" not in tools
    assert "get_inventory_valuation" not in tools


def test_admin_overrides_restricted_when_combined():
    # If a user somehow has both, the unrestricted role wins.
    assert allowed_tools(["Cashier", "Admin"]) == TOOL_NAMES
