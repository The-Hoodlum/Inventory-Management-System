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
    _fn("get_stock_movements",
        "Recent stock movements (receipts, issues, adjustments, transfers): what moved, when, and why. "
        "Optionally filter by item and/or branch.",
        {"item_name": {"type": "string", "description": "Item name or SKU to filter by (optional)."},
         "days": {"type": "integer", "description": "Look-back window in days (default 7)."}, **_BRANCH}),
    _fn("get_top_selling_motorcycles",
        "Top-selling MOTORCYCLES (category 'Motorcycles') by units over a date range (default last 30 days).",
        {"start_date": {"type": "string", "description": "Start date YYYY-MM-DD (optional)."},
         "end_date": {"type": "string", "description": "End date YYYY-MM-DD (optional)."},
         "limit": {"type": "integer", "description": "How many to return (default 10)."}, **_BRANCH}),
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
    _fn("get_assembly_status",
        "Motorcycle assembly status. (Assembly is not yet tracked in this system.)",
        {**_BRANCH}),
]

TOOL_NAMES: frozenset[str] = frozenset(t["function"]["name"] for t in TOOL_SPECS)

SYSTEM_PROMPT = (
    "You are the assistant for a motorcycle and spare-parts business with multiple branches "
    "(e.g. Lusaka, Ndola, Solwezi). Staff message you over WhatsApp. Answer ONLY from the "
    "provided tools — never invent stock, sales, or prices; if a tool returns nothing, say so "
    "in one short line.\n"
    "GROUNDING:\n"
    "- 'Branch' = a warehouse. Pass its name to a tool's `branch` argument, or omit it for all branches.\n"
    "- Most tools already break their results down by branch in ONE call. Prefer a single call "
    "with no `branch` over calling the same tool once per branch.\n"
    "- Use the date given as today for 'today'; for other dates use YYYY-MM-DD.\n"
    "- Revenue is an ESTIMATE (units x selling price) — always call it 'estimated', never booked revenue.\n"
    "- The system does not track assembly, and does not split motorcycles vs spare parts unless an "
    "item's name makes it obvious. Don't fabricate those.\n"
    "WHATSAPP STYLE — keep it short (aim for under ~8 lines):\n"
    "- Start with a one-line headline that includes a relevant emoji, then compact bullets.\n"
    "- Bullet format: '- <Branch>: <number>'. Make key numbers bold with *single asterisks* (WhatsApp bold).\n"
    "- When you list per-branch numbers, end with a '*Total:* <n>' line.\n"
    "- Use emojis sparingly and appropriately: motorcycle, wrench for parts, package for stock, "
    "warning for low/reorder, red circle for out-of-stock, money for sales/revenue, chart for reports.\n"
    "- Use the currency code the tools return. No tables, no markdown headings (#)."
)
