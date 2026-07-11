"""Service follow-up schedule maths (pure domain).

Guarantees: usage scales the gap (heavy sooner, light later), "next due" counts from the
last service (or sale) plus the next stage's scaled gap, the last stage repeats beyond the
defined list, the due-status buckets are right, and an un-dated sale yields no next service.
"""
from __future__ import annotations

import datetime as dt

from app.service_followup.domain import schedule as S

TODAY = dt.date(2026, 7, 11)


def test_usage_multiplier_scales_gap_heavy_sooner_light_later():
    assert S.scaled_interval(100, S.MEDIUM) == 100
    assert S.scaled_interval(100, S.HEAVY) == 70
    assert S.scaled_interval(100, S.LIGHT) == 125
    # Never below a day, even for a tiny gap under heavy use.
    assert S.scaled_interval(1, S.HEAVY) == 1


def test_normalise_usage_defaults_to_medium():
    assert S.normalise_usage(None) == S.MEDIUM
    assert S.normalise_usage("bogus") == S.MEDIUM
    assert S.normalise_usage(" Heavy ") == S.HEAVY


def test_first_service_counts_from_sale_date():
    sale = dt.date(2026, 7, 1)
    nxt = S.compute_next_service(
        sale_date=sale, services_done=0, last_service_date=None,
        usage=S.MEDIUM, stages=list(S.DEFAULT_STAGES), today=TODAY,
    )
    # DEFAULT_STAGES[0] is 30 days from the sale.
    assert nxt is not None
    assert nxt.sequence == 1
    assert nxt.due_date == sale + dt.timedelta(days=30)
    assert nxt.days_until_due == (nxt.due_date - TODAY).days


def test_next_service_counts_from_last_service():
    last = dt.date(2026, 7, 5)
    nxt = S.compute_next_service(
        sale_date=dt.date(2026, 1, 1), services_done=1, last_service_date=last,
        usage=S.MEDIUM, stages=list(S.DEFAULT_STAGES), today=TODAY,
    )
    # Second service: 60-day gap from the last service, not from the sale.
    assert nxt.sequence == 2
    assert nxt.due_date == last + dt.timedelta(days=60)


def test_last_stage_repeats_beyond_defined_list():
    stages = [S.Stage(1, "A", 30), S.Stage(2, "B", 90)]
    # 5th service -> reuses stage B (90-day gap), relabelled to sequence 5.
    stage = S.stage_for(stages, 5)
    assert stage.sequence == 5
    assert stage.interval_days == 90
    assert stage.label == "B"


def test_status_buckets_overdue_due_soon_upcoming():
    stages = [S.Stage(1, "A", 10)]
    # Anchor far in the past -> overdue.
    overdue = S.compute_next_service(
        sale_date=TODAY - dt.timedelta(days=60), services_done=0, last_service_date=None,
        usage=S.MEDIUM, stages=stages, today=TODAY,
    )
    assert overdue.status == S.OVERDUE and overdue.days_until_due < 0
    # Due within the window -> due_soon.
    soon = S.compute_next_service(
        sale_date=TODAY - dt.timedelta(days=5), services_done=0, last_service_date=None,
        usage=S.MEDIUM, stages=stages, today=TODAY,
    )
    assert soon.status == S.DUE_SOON
    # Far out -> upcoming.
    later = S.compute_next_service(
        sale_date=TODAY, services_done=0, last_service_date=None,
        usage=S.MEDIUM, stages=[S.Stage(1, "A", 90)], today=TODAY,
    )
    assert later.status == S.UPCOMING


def test_no_anchor_yields_no_next_service():
    assert S.compute_next_service(
        sale_date=None, services_done=0, last_service_date=None,
        usage=S.MEDIUM, stages=list(S.DEFAULT_STAGES), today=TODAY,
    ) is None


def test_stages_from_config_coerces_and_falls_back():
    # Malformed rows dropped, valid ones re-sequenced.
    stages = S.stages_from_config([
        {"label": "First", "interval_days": 30},
        {"label": "bad", "interval_days": "oops"},
        {"label": "Third", "interval_days": 90},
    ])
    assert [s.sequence for s in stages] == [1, 2]
    assert [s.interval_days for s in stages] == [30, 90]
    # Empty / non-list -> module default.
    assert S.stages_from_config([]) == list(S.DEFAULT_STAGES)
    assert S.stages_from_config(None) == list(S.DEFAULT_STAGES)
