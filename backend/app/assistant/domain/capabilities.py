"""Role-based tool access for the assistant (pure, testable).

Two orthogonal controls gate the assistant:
  * TOOLS   — which functions a user's role may call (this module).
  * BRANCH  — which warehouses they may see (``user_warehouse_access``; a
              Branch Manager is restricted by being granted a single branch).

Most roles are *unrestricted* at the tool level (Admin, Branch Manager, the
operational managers, Viewer) — they may call every read tool; their reach is
limited by branch grants, not by tool. Only a few front-line roles get a reduced
tool set. Names are intersected with the live ``TOOL_NAMES`` so referencing a
not-yet-added tool here is harmless.
"""
from __future__ import annotations

from app.assistant.domain.tools import TOOL_NAMES

# Capability groups (by intent) — industry-agnostic tool names.
_STOCK = {"get_stock_level"}
_SALES = {
    "get_sales_report", "get_sales_between_dates", "get_top_selling_items", "get_daily_summary",
}
_ITEM_LOOKUP = {"get_stock_level", "get_stock_movements"}
_SERVICE = {"get_assembly_status"}
_REQUESTS = {"create_order_request"}  # raise a requisition (also permission-gated at dispatch)

# Roles with a DELIBERATELY reduced tool set. Any role NOT listed here is
# unrestricted (full tool access), so existing system roles keep working.
RESTRICTED_ROLE_TOOLS: dict[str, set[str]] = {
    "Cashier": _STOCK | _SALES | _REQUESTS,  # stock + sales + raise order requests
    "Mechanic": _ITEM_LOOKUP | _SERVICE,     # item/parts lookup + service info only
}

# Write tools require a permission (not just role visibility) — enforced in the service.
WRITE_TOOL_PERMISSION: dict[str, str] = {
    "create_order_request": "order_request.create",
}


def allowed_tools(roles: list[str] | None) -> frozenset[str]:
    """Tool names this set of roles may call. No roles -> nothing. Any unrestricted
    role -> everything (admin/manager wins). Otherwise the union of the restricted
    roles' sets, intersected with the tools that actually exist."""
    role_set = [r for r in (roles or []) if r]
    if not role_set:
        return frozenset()
    if any(r not in RESTRICTED_ROLE_TOOLS for r in role_set):
        return TOOL_NAMES
    union: set[str] = set()
    for r in role_set:
        union |= RESTRICTED_ROLE_TOOLS[r]
    return frozenset(union & TOOL_NAMES)
