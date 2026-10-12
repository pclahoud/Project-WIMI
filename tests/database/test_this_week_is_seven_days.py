"""Issue #530 - This Week and last week are two equal, non-overlapping 7-day windows.

``get_analytics_overview`` counted This Week as ``date_encountered >=
today - 7`` with no upper bound -- eight days, today-7 through today --
against last week's ``[today-14, today-7)``, seven days. An entry dated
exactly seven days ago therefore counted as *this* week, and the change
badge was pushed upward every day.

The student manual (``docs/manual/41_reading_the_analytics.md``) defines
This Week as "the last seven days -- a rolling window on the session's
Date Encountered", with the badge "the difference against the seven days
before that". So the windows are:

    this week   today-6  .. today       (7 days)
    last week   today-13 .. today-7     (7 days)

Every day from today-15 to today gets one entry, then the two counts are
read off and each boundary day is checked to land in exactly one window
(or neither, outside them). The backend's clock is substituted and the
whole thing is run for every weekday, because "rolling" means the answer
must not depend on which day the suite runs.
"""
from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import database.domains.analytics as analytics
from database import MasterDatabase, UserDatabase


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(
            username="wk530", display_name="Week 530", user_types=["student"],
        )
        db = UserDatabase(
            db_path=master.ensure_user_database(user.id),
            user_id=user.id, username=user.username,
        )
        yield db
        db.close()
        master.close()


def _freeze(monkeypatch, today: date) -> None:
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(today.year, today.month, today.day, 12, 0, 0)

    # get_analytics_overview re-imports datetime inside the function body,
    # so the module attribute is not enough: patch the class the import
    # statement resolves to as well.
    monkeypatch.setattr(analytics, "datetime", _Clock)
    import datetime as dt_module
    monkeypatch.setattr(dt_module, "datetime", _Clock)


def _seed(db, exam_id: int, when: date, n: int = 1) -> None:
    session = db.create_review_session(
        exam_context_id=exam_id, total_questions=n, total_incorrect=n,
        session_name=f"wk530 {when}", date_encountered=when,
    )
    for _ in range(n):
        db.create_question_entry(
            review_session_id=session.id, user_answer="A", correct_answer="B",
        )
    db.conn.commit()


TODAYS = [date(2026, 10, 4) + timedelta(days=k) for k in range(7)]


@pytest.mark.database
@pytest.mark.parametrize("today", TODAYS, ids=lambda d: f"{d:%a}")
def test_each_day_lands_in_exactly_the_window_the_manual_names(user_db, monkeypatch, today):
    exam_id = user_db.create_exam_context(exam_name="WK530", exam_description="").id
    _freeze(monkeypatch, today)

    # One entry per day, each also in its own exam so a day's membership can
    # be probed alone. Every mismatch is collected before asserting, so a
    # failure names every misplaced day rather than the first one.
    wrong = []
    for back in range(0, 16):
        day = today - timedelta(days=back)
        solo = user_db.create_exam_context(exam_name=f"WK530 {back}", exam_description="").id
        _seed(user_db, solo, day)
        _seed(user_db, exam_id, day)
        if back <= 6:
            want = (1, 0)
        elif back <= 13:
            want = (0, 1)
        else:
            want = (0, 0)
        ov = user_db.get_analytics_overview(solo)
        got = (ov["this_week"], ov["last_week"])
        if got != want:
            wrong.append(f"{day} ({back} days back): got {got}, want {want}")
    assert not wrong, (
        f"today={today:%a %Y-%m-%d}: (this_week, last_week) misplaced "
        f"{wrong}. #530: This Week is today-6..today, last week today-13..today-7."
    )

    ov = user_db.get_analytics_overview(exam_id)
    assert ov["this_week"] == 7 and ov["last_week"] == 7, ov
    assert ov["week_change"] == 0, ov


@pytest.mark.database
def test_the_issue_fixture_reads_one_against_one(user_db, monkeypatch):
    """#530's own measurement: one entry each on today, today-7, today-14.

    On master this read this_week=2, last_week=1, week_change=1.
    """
    today = date(2026, 10, 7)
    _freeze(monkeypatch, today)
    exam_id = user_db.create_exam_context(exam_name="WK530b", exam_description="").id
    for back in (0, 7, 14):
        _seed(user_db, exam_id, today - timedelta(days=back))
    ov = user_db.get_analytics_overview(exam_id)
    assert (ov["this_week"], ov["last_week"], ov["week_change"]) == (1, 1, 0), ov


@pytest.mark.database
def test_a_future_dated_session_is_not_in_the_last_seven_days(user_db, monkeypatch):
    """This Week now has an upper bound, so a session dated tomorrow is in neither window."""
    today = date(2026, 10, 7)
    _freeze(monkeypatch, today)
    exam_id = user_db.create_exam_context(exam_name="WK530c", exam_description="").id
    _seed(user_db, exam_id, today + timedelta(days=1))
    ov = user_db.get_analytics_overview(exam_id)
    assert (ov["this_week"], ov["last_week"]) == (0, 0), ov
    assert ov["total_entries"] == 1, ov   # control: the entry exists
