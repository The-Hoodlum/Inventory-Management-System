"""OpenAI function-calling tool specs + system prompt for the assistant.

Pure data: the JSON schemas the model sees, and the grounding system prompt. Tool
*execution* lives in the service/repository (DB-bound). ``TOOL_NAMES`` is the
allow-list the service dispatches against — the model can call nothing else.
"""
from __future__ import annotations

_BRANCH = {
    "branch": {
        "type": "string",
        "description": "Branch/warehouse name (e.g. Lusaka, Ndola, Solwezi). Omit for all branches.",
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
        "On-hand and available stock for items whose name/SKU matches a search term, broken down by branch.",
        {"item_name": {"type": "string", "description": "Item name or SKU to search for, e.g. 'spark plug'."}, **_BRANCH},
        ["item_name"]),
    _fn("get_motorcycle_stock",
        "Available stock for a motorcycle model (matches product name/SKU), broken down by branch.",
        {"model": {"type": "string", "description": "Model name, e.g. 'HLX 150' or 'RTR 200'."}, **_BRANCH},
        ["model"]),
    _fn("get_low_stock_items",
        "Items at or below their reorder point (low stock), optionally for one branch.",
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
        "Top-selling items by units over a date range (defaults to the last 30 days).",
        {"start_date": {"type": "string", "description": "Start date YYYY-MM-DD (optional)."},
         "end_date": {"type": "string", "description": "End date YYYY-MM-DD (optional)."},
         "limit": {"type": "integer", "description": "How many items to return (default 10)."}, **_BRANCH}),
    _fn("get_fast_moving_items",
        "Fastest-moving items by units over a recent window (default last 30 days).",
        {"days": {"type": "integer", "description": "Look-back window in days (default 30)."}, **_BRANCH}),
    _fn("get_branch_summary",
        "Daily branch summary: stock lines held, units sold and estimated revenue that day, low-stock count.",
        {"date": {"type": "string", "description": "Date YYYY-MM-DD. Omit or 'today' for today."}, **_BRANCH}),
    _fn("get_assembly_status",
        "Motorcycle assembly status. (Assembly is not yet tracked in this system.)",
        {**_BRANCH}),
]

TOOL_NAMES: frozenset[str] = frozenset(t["function"]["name"] for t in TOOL_SPECS)

SYSTEM_PROMPT = (
    "You are the assistant for an inventory, sales, and procurement platform used by a "
    "motorcycle and spare-parts business with multiple branches (e.g. Lusaka, Ndola, "
    "Solwezi). Answer staff questions using ONLY the provided tools — never invent or "
    "estimate stock, sales, or prices yourself; if a tool returns no data, say so plainly.\n"
    "Rules:\n"
    "1. 'Branch' means a warehouse; pass the branch name to a tool's `branch` argument, or "
    "omit it for all branches.\n"
    "2. For 'today' pass the date the tools report as today; for other dates use YYYY-MM-DD.\n"
    "3. Revenue from the sales tools is an ESTIMATE (units x selling price) — call it "
    "'estimated' and never present it as booked revenue.\n"
    "4. The system does not distinguish motorcycles from spare parts unless an item's name "
    "makes it obvious, and it does not track assembly — don't fabricate those splits.\n"
    "5. Keep replies short and WhatsApp-friendly: a one-line headline, then compact bullet "
    "lines (branch: number). Use the currency code the tools return."
)
