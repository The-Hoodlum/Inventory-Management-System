"""The LLM seam for the advisor — interface, an inert default, and a grounded
prompt builder.

Mirrors the intelligence ``ExternalSource`` pattern: the advisor always works
deterministically; an LLM is an *optional* enrichment behind config. With none
configured, ``NullLLMProvider`` returns no narrative and the API still serves the
deterministic briefing.

``build_advisory_prompt`` is pure and unit-tested. It hands the model *only* the
deterministic findings and instructs it to narrate them without inventing numbers —
this is how "every recommendation is explainable / no fabricated data" is enforced
at the prompt boundary.
"""
from __future__ import annotations

import abc

from app.advisor.domain.briefing import AdvisoryContext

_SYSTEM = (
    "You are a supply-chain analyst for a procurement platform. You will be given a "
    "set of FINDINGS that were computed deterministically from the tenant's real data "
    "(reorder recommendations, supply-chain signals, supplier scorecards, demand "
    "forecasts). Rules:\n"
    "1. Use ONLY the findings provided. Never invent SKUs, suppliers, numbers, or risks.\n"
    "2. Prioritise by the given severity and explain the 'so what' for a buyer.\n"
    "3. Reference findings by their title when you make a recommendation.\n"
    "4. If the question cannot be answered from the findings, say so plainly.\n"
    "Be concise and action-oriented."
)


def serialize_findings(context: AdvisoryContext) -> str:
    """Render the context as the deterministic evidence block for the model."""
    lines = [f"SUMMARY: {context.summary_line}", "", "FINDINGS (highest priority first):"]
    if not context.findings:
        lines.append("  (none — nothing actionable right now)")
    for i, f in enumerate(context.findings, 1):
        lines.append(
            f"  {i}. [{f.category}] {f.title} (severity {f.severity})\n"
            f"     {f.detail}"
            + (f"\n     Suggested: {f.recommended_action}" if f.recommended_action else "")
        )
    return "\n".join(lines)


def build_advisory_prompt(context: AdvisoryContext, question: str | None = None) -> tuple[str, str]:
    """Return ``(system, user)`` prompts grounding the model in the findings only."""
    ask = (question or "Give me today's supply-chain briefing: what should I act on and why?").strip()
    user = f"{serialize_findings(context)}\n\nQUESTION: {ask}"
    return _SYSTEM, user


class LLMProvider(abc.ABC):
    """An optional narrator over a grounded ``AdvisoryContext``."""

    enabled: bool = False

    @abc.abstractmethod
    async def narrate(self, context: AdvisoryContext, question: str | None = None) -> str | None:
        """Return a natural-language narrative, or None to abstain."""


class NullLLMProvider(LLMProvider):
    """Inert provider used when no LLM is configured — the deterministic default."""

    enabled = False

    async def narrate(self, context: AdvisoryContext, question: str | None = None) -> str | None:
        return None
