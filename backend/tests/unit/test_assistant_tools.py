"""The tool catalog the model sees — shape and allow-list."""
from __future__ import annotations

from app.assistant.domain.tools import SYSTEM_PROMPT, TOOL_NAMES, TOOL_SPECS

EXPECTED = {
    "get_stock_level", "get_motorcycle_stock", "get_low_stock_items",
    "get_reorder_recommendations", "get_inventory_valuation", "get_purchase_orders",
    "get_sales_report", "get_sales_between_dates", "get_top_selling_items",
    "get_fast_moving_items", "get_branch_summary", "get_assembly_status",
    # added in Wave B
    "get_stock_movements", "get_top_selling_motorcycles", "get_slow_moving_items",
    "get_pending_purchase_requests", "get_branch_performance", "get_daily_summary",
    # propose-only reorder (read-only)
    "create_reorder_proposal",
}


def test_catalog_matches_allow_list():
    assert TOOL_NAMES == EXPECTED
    assert len(TOOL_SPECS) == len(EXPECTED)


def test_every_spec_is_a_well_formed_function():
    for spec in TOOL_SPECS:
        assert spec["type"] == "function"
        fn = spec["function"]
        assert fn["name"] in EXPECTED
        params = fn["parameters"]
        assert params["type"] == "object"
        assert params["additionalProperties"] is False
        for req in params["required"]:
            assert req in params["properties"]


def test_required_args_where_expected():
    by_name = {s["function"]["name"]: s["function"]["parameters"] for s in TOOL_SPECS}
    assert by_name["get_stock_level"]["required"] == ["item_name"]
    assert by_name["get_motorcycle_stock"]["required"] == ["model"]
    assert set(by_name["get_sales_between_dates"]["required"]) == {"start_date", "end_date"}
    assert by_name["get_low_stock_items"]["required"] == []


def test_system_prompt_grounds_the_model():
    lower = SYSTEM_PROMPT.lower()
    assert "branch" in lower
    assert "estimate" in lower  # revenue must be framed as an estimate
    assert "provided tools" in lower  # answer only from tools
    assert "whatsapp" in lower  # formatting guidance present
