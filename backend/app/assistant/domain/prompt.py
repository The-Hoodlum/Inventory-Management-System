"""Dynamic, tenant-driven system prompt (pure + testable).

The core platform is industry-agnostic: the assistant's identity (name, company,
industry, currency) and any custom instructions come from tenant configuration, not
from hard-coded business specifics. ``ASSISTANT_RULES`` holds only generic tool-usage
and formatting guidance — no industry, product type, country, currency, or branch names.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

ASSISTANT_RULES = (
    "Guidelines:\n"
    "- 'Branch' means a warehouse/location; pass its name to a tool's `branch` argument, or omit "
    "it for all branches.\n"
    "- Most tools already break their results down by branch in ONE call — prefer a single call "
    "over calling the same tool once per branch.\n"
    "- Revenue figures are ESTIMATES (units x selling price); always call them 'estimated'.\n"
    "- Some capabilities (e.g. assembly/build tracking) may not exist; if a tool says something "
    "isn't tracked, say so plainly instead of guessing.\n"
    "- Keep replies short and WhatsApp-friendly: a one-line headline with a relevant emoji, then "
    "compact '- <Branch>: <number>' bullets; end a per-branch list with a '*Total:* <n>' line. "
    "Bold key numbers with *single asterisks*. No tables, no markdown headings.\n"
    "- Do not assume a specific industry or product type beyond what the data shows."
)


@dataclass
class TenantConfig:
    """The slice of tenant settings the assistant needs to shape its persona."""

    company_name: str | None = None
    brand_name: str | None = None
    industry: str | None = None
    currency: str = "USD"
    assistant_name: str | None = None
    assistant_prompt: str | None = None


def build_system_prompt(config: TenantConfig, today: dt.date) -> str:
    """Compose the system prompt from generic rules + this tenant's identity."""
    name = config.assistant_name or "the inventory assistant"
    company = config.company_name or "this business"
    industry = f", a {config.industry} business," if config.industry else ""
    lines = [
        f"You are {name}, the assistant for {company}{industry} helping staff with inventory, "
        "sales, and procurement. Answer using ONLY the provided tools — never invent stock, "
        "sales, or prices; if a tool returns nothing, say so briefly.",
    ]
    if config.assistant_prompt and config.assistant_prompt.strip():
        lines.append(config.assistant_prompt.strip())
    lines.append(ASSISTANT_RULES)
    lines.append(f"Show all monetary amounts in {config.currency} (the tenant's currency).")
    lines.append(
        f"Today's date is {today.isoformat()} ({today:%A}). Use it for 'today', 'yesterday', "
        "and any relative date the user gives."
    )
    return "\n".join(lines)
