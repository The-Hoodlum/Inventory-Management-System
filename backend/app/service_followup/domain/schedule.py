"""Pure service-schedule maths — standard library only (no DB / pydantic).

A motorcycle's service schedule is an ordered list of STAGES. Each stage's
``interval_days`` is the gap from the *previous* service (the first stage counts from
the sale date). The last stage's interval repeats for every service beyond the list, so
a bike keeps getting "next service" dates for life.

Usage scales the gap: a bike ridden hard wears faster and is due sooner. The multiplier
is applied to the gap in days — ``heavy`` shrinks it, ``light`` stretches it.

"Next due" is computed from the anchor (the last service performed, or the sale date if
none) plus the next stage's usage-scaled gap. Everything here is deterministic and
time-only — no odometer — matching how the shop tracks it.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

# Usage profiles -------------------------------------------------------------- #
LIGHT = "light"
MEDIUM = "medium"
HEAVY = "heavy"
USAGE_PROFILES: tuple[str, ...] = (LIGHT, MEDIUM, HEAVY)

USAGE_LABELS = {
    LIGHT: "Light — commuting",
    MEDIUM: "Medium — delivery",
    HEAVY: "Heavy — rural / farm",
}

# Heavy use -> due sooner (gap * 0.7); light use -> due later (gap * 1.25).
USAGE_MULTIPLIERS: dict[str, float] = {
    LIGHT: 1.25,
    MEDIUM: 1.0,
    HEAVY: 0.7,
}


def normalise_usage(raw: str | None) -> str:
    u = (raw or "").strip().lower()
    return u if u in USAGE_MULTIPLIERS else MEDIUM


# Due-status buckets ---------------------------------------------------------- #
OVERDUE = "overdue"
DUE_SOON = "due_soon"
UPCOMING = "upcoming"

# A service within this many days counts as "due soon" (the call-now list).
DUE_SOON_DAYS = 14


@dataclass(frozen=True)
class Stage:
    sequence: int
    label: str
    interval_days: int


# Standard TVS-style schedule (editable per model in the UI; this is the fallback). Free
# services early, then a recurring paid service. Gaps are from the previous service.
DEFAULT_STAGES: tuple[Stage, ...] = (
    Stage(1, "1st service", 30),    # ~1 month after purchase
    Stage(2, "2nd service", 60),    # ~3 months after purchase
    Stage(3, "3rd service", 90),    # ~6 months after purchase
    Stage(4, "Periodic service", 90),  # then roughly every 3 months, for life
)


def stages_from_config(raw: object) -> list[Stage]:
    """Coerce a stored ``stages`` JSON list into Stage objects, dropping malformed rows
    and re-sequencing 1..n by order. Empty / invalid -> the module default."""
    out: list[Stage] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                interval = int(item.get("interval_days"))
            except (TypeError, ValueError):
                continue
            if interval < 1:
                continue
            # Sequence by OUTPUT position (1..n, contiguous) so stage_for's index math holds
            # even when malformed rows were dropped.
            seq = len(out) + 1
            label = str(item.get("label") or f"Service {seq}").strip() or f"Service {seq}"
            out.append(Stage(sequence=seq, label=label, interval_days=interval))
    return out or list(DEFAULT_STAGES)


def stage_for(stages: list[Stage], sequence: int) -> Stage:
    """The stage for a given 1-based service number; the last stage repeats beyond the
    defined list (with its sequence relabelled to the actual number)."""
    if sequence <= len(stages):
        return stages[sequence - 1]
    last = stages[-1]
    return Stage(sequence=sequence, label=last.label, interval_days=last.interval_days)


@dataclass(frozen=True)
class NextService:
    sequence: int
    label: str
    interval_days: int          # the usage-scaled gap actually applied
    anchor_date: dt.date        # what the gap was measured from (last service or sale)
    due_date: dt.date
    days_until_due: int         # negative when overdue
    status: str                 # overdue / due_soon / upcoming


def scaled_interval(interval_days: int, usage: str) -> int:
    """Apply the usage multiplier to a gap, never returning less than a day."""
    mult = USAGE_MULTIPLIERS[normalise_usage(usage)]
    return max(1, round(interval_days * mult))


def compute_next_service(
    *,
    sale_date: dt.date | None,
    services_done: int,
    last_service_date: dt.date | None,
    usage: str,
    stages: list[Stage],
    today: dt.date,
) -> NextService | None:
    """The next service due for a unit, or None when there's no anchor to count from
    (an un-dated sale). ``services_done`` is how many services are already logged."""
    anchor = last_service_date or sale_date
    if anchor is None:
        return None
    next_seq = services_done + 1
    stage = stage_for(stages, next_seq)
    interval = scaled_interval(stage.interval_days, usage)
    due = anchor + dt.timedelta(days=interval)
    days_until = (due - today).days
    if days_until < 0:
        status = OVERDUE
    elif days_until <= DUE_SOON_DAYS:
        status = DUE_SOON
    else:
        status = UPCOMING
    return NextService(
        sequence=next_seq,
        label=stage.label,
        interval_days=interval,
        anchor_date=anchor,
        due_date=due,
        days_until_due=days_until,
        status=status,
    )
