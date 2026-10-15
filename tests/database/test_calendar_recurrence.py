"""The weekly recurrence subset (#778 decision 2): parse, canonicalise, expand.

Pure functions over local dates; no database. COUNT is counted from the
series start, not from the drawn range, and BYDAY defaults to the start's
weekday. Every refusal is a sentence (RecurrenceRuleError).
"""
from __future__ import annotations

from datetime import date

import pytest

from database.domains._calendar_recurrence import (
    RecurrenceRuleError,
    WeeklyRule,
    expand_weekly,
    parse_rrule,
)

TUE = date(2026, 10, 13)   # a Tuesday


@pytest.mark.unit
def test_parse_minimal_and_canonical_form():
    rule = parse_rrule("FREQ=WEEKLY")
    assert rule == WeeklyRule()
    assert rule.to_rrule(TUE) == "FREQ=WEEKLY;BYDAY=TU"


@pytest.mark.unit
def test_parse_full_form_sorts_days_and_keeps_bounds():
    rule = parse_rrule("freq=weekly;interval=2;byday=TH,MO;until=20261231")
    assert rule.interval == 2 and rule.by_day == (0, 3) and rule.until == date(2026, 12, 31)
    assert rule.to_rrule(TUE) == "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH;UNTIL=20261231"


@pytest.mark.unit
@pytest.mark.parametrize("bad", [
    "", "FREQ=DAILY", "FREQ=WEEKLY;BYDAY=XX", "FREQ=WEEKLY;INTERVAL=0", "FREQ=WEEKLY;INTERVAL=99",
    "FREQ=WEEKLY;UNTIL=2026-12-31", "FREQ=WEEKLY;UNTIL=20261399", "FREQ=WEEKLY;COUNT=0",
    "FREQ=WEEKLY;COUNT=5;UNTIL=20261231", "FREQ=WEEKLY;BYMONTH=1", "FREQ=WEEKLY;FREQ=WEEKLY", "WEEKLY",
])
def test_rules_outside_the_subset_are_refused_with_a_sentence(bad):
    with pytest.raises(RecurrenceRuleError) as exc:
        parse_rrule(bad)
    assert str(exc.value) and "Traceback" not in str(exc.value)


@pytest.mark.unit
def test_expand_defaults_to_the_start_weekday():
    rule = parse_rrule("FREQ=WEEKLY")
    days = expand_weekly(TUE, rule, date(2026, 10, 1), date(2026, 11, 10))
    assert days == [date(2026, 10, 13), date(2026, 10, 20), date(2026, 10, 27), date(2026, 11, 3), date(2026, 11, 10)]
    assert all(d.weekday() == 1 for d in days)


@pytest.mark.unit
def test_expand_byday_skips_days_before_the_start_in_the_first_week():
    rule = parse_rrule("FREQ=WEEKLY;BYDAY=MO,TH")
    days = expand_weekly(TUE, rule, date(2026, 10, 12), date(2026, 10, 25))
    # Monday 12 Oct is before the Tuesday start and is not an occurrence.
    assert days == [date(2026, 10, 15), date(2026, 10, 19), date(2026, 10, 22)]


@pytest.mark.unit
def test_count_is_from_the_series_start_not_the_range():
    rule = parse_rrule("FREQ=WEEKLY;BYDAY=TU;COUNT=3")
    whole = expand_weekly(TUE, rule, date(2026, 1, 1), date(2027, 1, 1))
    assert whole == [date(2026, 10, 13), date(2026, 10, 20), date(2026, 10, 27)]
    later_window = expand_weekly(TUE, rule, date(2026, 10, 25), date(2026, 12, 31))
    assert later_window == [date(2026, 10, 27)]


@pytest.mark.unit
def test_until_is_inclusive_and_interval_skips_weeks():
    rule = parse_rrule("FREQ=WEEKLY;INTERVAL=2;BYDAY=TU;UNTIL=20261110")
    days = expand_weekly(TUE, rule, date(2026, 10, 1), date(2026, 12, 31))
    assert days == [date(2026, 10, 13), date(2026, 10, 27), date(2026, 11, 10)]


@pytest.mark.unit
def test_open_ended_series_is_bounded_by_the_range_only():
    rule = parse_rrule("FREQ=WEEKLY;BYDAY=SA,SU")
    days = expand_weekly(TUE, rule, date(2027, 6, 1), date(2027, 6, 14))
    assert days == [date(2027, 6, 5), date(2027, 6, 6), date(2027, 6, 12), date(2027, 6, 13)]


@pytest.mark.unit
def test_a_reversed_range_is_refused():
    with pytest.raises(ValueError):
        expand_weekly(TUE, WeeklyRule(), date(2026, 10, 20), date(2026, 10, 13))
