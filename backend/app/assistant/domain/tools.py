"""OpenAI function-calling tool specs for the assistant.

Pure data: the JSON schemas the model sees. Tool *execution* lives in the
service/repository (DB-bound). ``TOOL_NAMES`` is the allow-list the service dispatches
against — the model can call nothing else. These tools are INDUSTRY-AGNOSTIC; the
business persona/currency come from tenant config via ``domain/prompt.py``.
"""
from __future__ import annotations

_BRANCH = {
    "branch": {
        "type": "string",
        "description": "Branch/warehouse name. Omit for all branches.",
    }
}


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


TOOL_SPECS: list[dict] = [
    _fn("get_stock_level",
        "On-hand and available stock for items whose name/SKU matches a search term (works for any "
        "product or model), broken down by branch.",
        {"item_name": {"type": "string", "description": "Item name, model, or SKU to search for."}, **_BRANCH},
        ["item_name"]),
    _fn("get_low_stock_items",
        "Items at or below their reorder point across ALL branches in ONE call (each item is "
        "tagged with its branch). Pass `branch` only to narrow to a single branch.",
        {**_BRANCH}),
    _fn("get_reorder_recommendations",
        "Current pending reorder recommendations (what to reorder and how much).",
        {**_BRANCH}),
    _fn("get_inventory_valuation",
        "Inventory valuation at cost (sum of on-hand quantity x cost price) per branch and overall.",
        {**_BRANCH}),
    _fn("get_purchase_orders",
        "Purchase orders, optionally filtered by status (draft, pending_approval, approved, sent, received, cancelled).",
        {"status": {"type": "string", "description": "PO status filter; omit for all."}, **_BRANCH}),
    _fn("get_sales_report",
        "Sales summary for a single day: units sold, ESTIMATED revenue (qty x selling price), top item, best branch.",
        {"date": {"type": "string", "description": "Date as YYYY-MM-DD. Omit or 'today' for today."}, **_BRANCH}),
    _fn("get_sales_between_dates",
        "Sales summary between two dates (inclusive): units sold, estimated revenue, top item, best branch.",
        {"start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
         "end_date": {"type": "string", "description": "End date YYYY-MM-DD."}, **_BRANCH},
        ["start_date", "end_date"]),
    _fn("get_top_selling_items",
        "Top-selling items by units over a date range (defaults to the last 30 days), optionally "
        "limited to one product category (e.g. a category name relevant to this business).",
        {"start_date": {"type": "string", "description": "Start date YYYY-MM-DD (optional)."},
         "end_date": {"type": "string", "description": "End date YYYY-MM-DD (optional)."},
         "category": {"type": "string", "description": "Optional product category name to filter by."},
         "limit": {"type": "integer", "description": "How many items to return (default 10)."}, **_BRANCH}),
    _fn("get_fast_moving_items",
        "Fastest-moving items by units over a recent window (default last 30 days).",
        {"days": {"type": "integer", "description": "Look-back window in days (default 30)."}, **_BRANCH}),
    _fn("get_branch_summary",
        "Daily branch summary: stock lines held, units sold and estimated revenue that day, low-stock count.",
        {"date": {"type": "string", "description": "Date YYYY-MM-DD. Omit or 'today' for today."}, **_BRANCH}),
    _fn("get_stock_movements",
        "Recent stock movements (receipts, issues, adjustments, transfers): what moved, when, and why. "
        "Optionally filter by item and/or branch.",
        {"item_name": {"type": "string", "description": "Item name or SKU to filter by (optional)."},
         "days": {"type": "integer", "description": "Look-back window in days (default 7)."}, **_BRANCH}),
    _fn("get_slow_moving_items",
        "Slow-moving items: in stock but with the fewest units sold over a recent window (default 30 days).",
        {"days": {"type": "integer", "description": "Look-back window in days (default 30)."},
         "limit": {"type": "integer", "description": "How many to return (default 10)."}, **_BRANCH}),
    _fn("get_pending_purchase_requests",
        "Purchase orders awaiting action (status draft or pending_approval) — the approval queue.",
        {**_BRANCH}),
    _fn("get_branch_performance",
        "Compare branches over a date range in ONE call: units sold, estimated revenue, stock value, "
        "and low-stock count per branch (default last 30 days).",
        {"start_date": {"type": "string", "description": "Start date YYYY-MM-DD (optional)."},
         "end_date": {"type": "string", "description": "End date YYYY-MM-DD (optional)."}}),
    _fn("get_daily_summary",
        "One-shot daily snapshot: units sold, estimated revenue, top item, low-stock count and pending "
        "purchase requests, broken down by branch — all in a single call.",
        {"date": {"type": "string", "description": "Date YYYY-MM-DD. Omit or 'today' for today."}, **_BRANCH}),
    _fn("create_reorder_proposal",
        "Propose what to reorder for a branch (READ-ONLY — creates nothing). For items at/below "
        "reorder point it suggests an order quantity rounded to full cartons, with estimated cost, "
        "supplier, and lead time; factors in reorder point, safety stock, MOQ, and carton size.",
        {**_BRANCH}),
    _fn("get_assembly_status",
        "Assembly/build status of products. (Assembly is NOT tracked in this system.)",
        {**_BRANCH}),
]

TOOL_NAMES: frozenset[str] = frozenset(t["function"]["name"] for t in TOOL_SPECS)
