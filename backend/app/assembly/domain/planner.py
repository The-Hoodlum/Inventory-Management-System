"""The assembly planner — a pure, deterministic function (no DB, unit-tested).

It does NOT predict demand and invents no numbers: it counts CURRENT stock and applies a
configurable target/threshold per model+colour. For each model/colour(/variant) combo:

  * ``assembled``   — sellable units on hand (lifecycle status 'assembled')
  * ``unassembled`` — raw units on hand you can build FROM (status 'unassembled')

Rules:
  * A combo is THIN when ``assembled <= threshold`` (default threshold 1 catches
    "only one left" / none).
  * A thin combo WITH unassembled units to build from becomes a RECOMMENDATION to
    assemble ``min(target - assembled, unassembled)`` — never more than you can build.
  * A thin combo with NO unassembled units is a GAP ("low, nothing to assemble from") —
    an implicit purchase/import signal, kept separate from assemble recommendations.
  * A combo above the threshold is not flagged at all.

DEMAND IS OUT OF SCOPE. Ranking here is deterministic (thinnest first). A future
demand-weighted layer can re-rank ``recommendations`` without changing this rule — that is
the only intended seam; none of it is built here.
"""
from __future__ import annotations

from dataclasses import dataclass

# Sensible global defaults when a tenant hasn't configured a model/colour target.
DEFAULT_TARGET_ASSEMBLED = 2
DEFAULT_THRESHOLD = 1


@dataclass(frozen=True)
class ComboInput:
    assembled: int
    unassembled: int
    target: int
    threshold: int


@dataclass(frozen=True)
class ComboOutcome:
    recommended_qty: int          # units to assemble now (0 for gaps / non-actionable)
    is_recommendation: bool       # thin AND buildable AND qty > 0
    is_gap: bool                  # thin but nothing unassembled to build from
    reason: str


def plan_combo(c: ComboInput) -> ComboOutcome:
    """Classify one model/colour(/variant) combo from its current counts + config."""
    if c.assembled > c.threshold:
        return ComboOutcome(
            recommended_qty=0, is_recommendation=False, is_gap=False,
            reason=f"{c.assembled} assembled — above the keep-threshold of {c.threshold}",
        )
    # Thin on assembled stock from here down.
    if c.unassembled <= 0:
        return ComboOutcome(
            recommended_qty=0, is_recommendation=False, is_gap=True,
            reason=(
                f"Only {c.assembled} assembled and no unassembled units to build from "
                "— purchase / import needed"
            ),
        )
    qty = min(c.target - c.assembled, c.unassembled)
    if qty <= 0:
        # Thin by threshold but the target is already met (threshold >= target config);
        # nothing to build, and there ARE unassembled units, so it is not a gap either.
        return ComboOutcome(
            recommended_qty=0, is_recommendation=False, is_gap=False,
            reason=f"{c.assembled} assembled already meets the target of {c.target}",
        )
    return ComboOutcome(
        recommended_qty=qty, is_recommendation=True, is_gap=False,
        reason=(
            f"{c.assembled} assembled (<= {c.threshold}); assemble {qty} toward a target of "
            f"{c.target}" + (f" — capped by {c.unassembled} unassembled on hand"
                             if qty == c.unassembled else "")
        ),
    )
