"""A goal's week is the student's week, not UTC's (#296).

`question_entries.created_at` is written by SQLite's `CURRENT_TIMESTAMP` and is
**UTC**. A goal's window comes from `datetime.now().date()` and is **local**.
Comparing one against the other loses entries for the hours when the two
calendars disagree.

Why this file forces the disagreement instead of waiting for it
---------------------------------------------------------------
The defect was observed on 2026-10-04 at 22:11 local / 02:11 UTC, when twelve
goals tests failed on untouched `master` having passed that morning. On
`America/New_York` the daily window is 20:00 to midnight -- four hours in
twenty-four -- and the *weekly* one is those four hours **on a Sunday**, about
2.4% of the week. Every platform baseline this project holds was taken outside
it, which is why none of them carried those twelve.

So a test that simply calls the counter proves nothing for 97.6% of the week.
This one picks a timezone from the current UTC hour so that local and UTC
**always** disagree, exactly as #286 does for the frontend with
`Emulation.setTimezoneOverride`:

* before 11:00 UTC, `Pacific/Pago_Pago` (UTC-11) puts local *yesterday*;
* from 11:00 UTC, `Pacific/Kiritimati` (UTC+14) puts local *tomorrow*.

Both are DST-free, so the offset is a constant and the choice cannot be wrong
by an hour twice a year.

**And it fails hard if the two coincide.** Without that, a change to the
selection logic could silently make every assertion a tautology -- which is
#121's lesson, applied to a clock.

This file is POSIX-only, and that is a limit of the technique
--------------------------------------------------------------
`time.tzset()` **does not exist on Windows**, and there is no substitute. The
fixture needs SQLite's `'localtime'` modifier to move, and `'localtime'` reads
the C library's cached zone -- which on POSIX is what `tzset()` reloads from
`TZ`, and on Windows comes from the operating system's own timezone setting
that no environment variable in this process can change. So there is no
in-process way to force the disagreement there; the only lever is a
machine-wide setting that needs administrator rights and would affect
everything else running.

Measured on Windows machine B, Python 3.14.4, at `af4db38`: all three tests
errored at setup with `AttributeError: module 'time' has no attribute
'tzset'`. The defect was mine -- this file was written on Linux for #296 and
nothing in it was platform-aware.

**The product fix is unaffected.** `DATE(qe.created_at, 'localtime')` in
`src/database/domains/goals.py` is platform-independent SQL and is exercised
by this file on Linux and macOS, which is two of the three platforms. What
Windows loses is the regression guard, not the fix, and a skip that says so is
better than a test that cannot run pretending otherwise.

The skip keys on **`hasattr(time, 'tzset')`, never on `sys.platform`**. It is
the capability the fixture actually needs, so the day a Python release grows
an equivalent on Windows -- or the day someone runs this under a POSIX layer
there -- these tests run again with no edit. Same reasoning as #187's
deep-folder probe: measure the capability, and name the cause in the message.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from database.user_db import UserDatabase

#: POSIX-only, and checked as a capability rather than as a platform name --
#: see the module docstring. `time.tzset()` is the only in-process way to move
#: what SQLite's `'localtime'` modifier reads, and Windows does not have it.
requires_tzset = pytest.mark.skipif(
    not hasattr(time, "tzset"),
    reason=(
        "time.tzset() is POSIX-only, and it is the only in-process way to move "
        "what SQLite's 'localtime' modifier reads. On Windows the zone comes "
        "from an OS setting no environment variable in this process can "
        "change, so the UTC/local disagreement these tests need cannot be "
        "forced. #296's product fix is platform-independent SQL and is "
        "exercised here on Linux and macOS (#365 for the measurement)."
    ),
)

#: Module-level, not three decorators. Every test here needs the fixture, so a
#: fourth one added later must not be able to arrive without the skip -- which
#: is exactly how this file reached Windows as three setup errors.
pytestmark = requires_tzset


def _divergent_zone() -> tuple[str, str]:
    """A DST-free zone whose calendar date differs from UTC's right now."""
    if datetime.now(timezone.utc).hour < 11:
        return "Pacific/Pago_Pago", "behind"
    return "Pacific/Kiritimati", "ahead"


@pytest.fixture
def divergent_timezone():
    """Run the test with local time on a different calendar day from UTC.

    Restores both the variable and the C library's cached zone, because
    `time.tzset()` is what SQLite's `'localtime'` modifier actually reads --
    setting `TZ` alone changes Python and leaves SQLite on the old zone, which
    would make this file pass against the unfixed code.
    """
    zone, direction = _divergent_zone()
    previous = os.environ.get("TZ")
    os.environ["TZ"] = zone
    time.tzset()

    local_today = datetime.now().date()
    utc_today = datetime.now(timezone.utc).date()
    if local_today == utc_today:
        pytest.fail(
            f"{zone} was chosen to put local time {direction} of UTC, but both "
            f"read {local_today}. Every assertion below would hold trivially. "
            f"Fix the zone selection rather than relaxing this check (#121)."
        )

    try:
        yield zone, local_today, utc_today
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


def _week_of(day: date) -> tuple[date, date]:
    """Monday-to-Sunday, the window `set_weekly_goal` uses."""
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def _log_entry(db, exam_id: int, subject_id: int, *, draft: bool = False) -> int:
    """Log one entry, finished or draft, dated now.

    `create_question_entry` derives `is_draft` rather than taking it:

        is_draft = not (reflection and explanation and primary_subject_ids)

    so an entry is finished only when all three are present. Omitting any of
    them silently produces a draft -- which is how the first version of this
    file ended up asserting a finished count against three drafts.
    """
    session = db.create_review_session(
        exam_context_id=exam_id, total_questions=1, total_incorrect=1,
        date_encountered=datetime.now().date())
    if draft:
        entry = db.create_question_entry(
            review_session_id=session.id, user_answer="a", correct_answer="b")
    else:
        entry = db.create_question_entry(
            review_session_id=session.id, user_answer="a", correct_answer="b",
            reflection="I misread the stem.",
            explanation="The low bicarbonate makes it a metabolic acidosis.",
            primary_subject_ids=[subject_id])
    assert bool(entry.is_draft) is draft, (
        f"fixture produced is_draft={entry.is_draft}, wanted {draft} -- "
        f"create_question_entry derives it from the fields supplied")
    return entry.id


@pytest.fixture
def user_db(tmp_path):
    """A real UserDatabase, matching the other goal tests' construction."""
    db = UserDatabase(tmp_path / "goal_window.db", user_id=1, username="gw_user")
    yield db
    db.close()


@pytest.fixture
def exam_id(user_db):
    return user_db.create_exam_context(exam_name="Window Test").id


@pytest.fixture
def subject_id(user_db, exam_id):
    """A primary subject, without which every entry is derived as a draft."""
    return user_db.create_subject_node(
        exam_context="Window Test", name="Acid-Base", level_type="Topic").id


def test_an_entry_counts_in_the_students_week_not_utcs(
        user_db, exam_id, subject_id, divergent_timezone):
    """The defect, directly.

    An entry logged now must count in the week that contains *the student's*
    today. Against the unfixed code the entry's UTC date falls outside that
    window and the count is 0.
    """
    zone, local_today, utc_today = divergent_timezone
    start, end = _week_of(local_today)

    _log_entry(user_db, exam_id, subject_id)

    counted = user_db._count_entries_in_period(start, end, exam_id)
    assert counted == 1, (
        f"an entry logged at {datetime.now():%H:%M} in {zone} (local "
        f"{local_today}, UTC {utc_today}) did not count in the student's own "
        f"week {start}..{end}. The window is local and `created_at` is UTC, so "
        f"the comparison needs DATE(created_at, 'localtime') -- #296")


def test_a_draft_is_reported_in_the_same_week_it_was_started(
        user_db, exam_id, subject_id, divergent_timezone):
    """`_count_drafts_in_period` is the exact complement and must agree.

    If only the finished counter converted, an entry logged in the disagreeing
    hours would be missing from both numbers -- not counted as progress and not
    reported as an outstanding draft -- so the student would be told nothing at
    all about work they had just done.
    """
    _, local_today, _ = divergent_timezone
    start, end = _week_of(local_today)

    _log_entry(user_db, exam_id, subject_id, draft=True)

    assert user_db._count_drafts_in_period(start, end, exam_id) == 1, (
        "a draft started today is absent from 'N drafts remaining' -- the two "
        "counters must use the same calendar or an entry falls through both")
    assert user_db._count_entries_in_period(start, end, exam_id) == 0, (
        "a draft must not count as finished progress (#12's goals carve-out)")


def test_the_week_boundary_is_the_expensive_case(
        user_db, exam_id, subject_id, divergent_timezone):
    """A Sunday-evening entry belongs to the week that is ending.

    The daily disagreement costs a day; on the last day of the week it costs a
    whole week, and #70 recounts live rather than storing progress, so nothing
    ever corrects it. This asserts the entry is in the week containing the
    student's today and NOT in the next one.
    """
    _, local_today, _ = divergent_timezone
    start, end = _week_of(local_today)
    next_start, next_end = _week_of(local_today + timedelta(days=7))

    _log_entry(user_db, exam_id, subject_id)

    assert user_db._count_entries_in_period(start, end, exam_id) == 1
    assert user_db._count_entries_in_period(next_start, next_end, exam_id) == 0, (
        "the entry leaked into next week -- this is the Sunday-night case, "
        "where the cost is a whole goal period rather than a day")
