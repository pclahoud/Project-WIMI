"""Issue #529 - the activity heatmap's first day must be a Sunday.

``heatmap_chart.js`` places day ``i`` of the payload in row ``i % 7`` and
labels rows 1, 3 and 5 "Mon", "Wed", "Fri" -- so it assumes ``days[0]`` is a
Sunday. ``get_activity_heatmap`` computed
``this_sunday - timedelta(weeks=15, days=6)``, which is always a **Monday**,
so every label sat one row off, every day, for every student.

The backend reads "today" from ``datetime.now()`` in its own module, so the
test substitutes that clock and runs the arithmetic for every weekday of a
week (and across a month and a year boundary) instead of whatever weekday
the suite happens to run on. A test that only ran today would check one
seventh of the cases.

Also asserted, because they read the same payload: the window still ends
today, still spans 16 week-columns, and the streak fields are unchanged by
the choice of start day.
"""
from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import database.domains.analytics_advanced as analytics_advanced
from database import MasterDatabase, UserDatabase


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(
            username="hm529", display_name="Heatmap 529", user_types=["student"],
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

    monkeypatch.setattr(analytics_advanced, "datetime", _Clock)


def _seed_entry(db, when: date) -> None:
    """One entry on ``when``, through the real write paths."""
    exam = db.create_exam_context(exam_name=f"HM529 {when}", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name="hm529", date_encountered=when,
    )
    db.create_question_entry(
        review_session_id=session.id, user_answer="A", correct_answer="B",
    )
    db.conn.commit()


# A full week (Sunday 2026-10-04 .. Saturday 2026-10-10) plus a month and a
# year boundary. Each is a "today" the heatmap is computed against.
TODAYS = [date(2026, 10, 4) + timedelta(days=k) for k in range(7)] + [
    date(2026, 3, 1),    # a Sunday on the 1st
    date(2027, 1, 2),    # a Saturday just after New Year
]


@pytest.mark.database
@pytest.mark.parametrize("today", TODAYS, ids=lambda d: f"{d.isoformat()}-{d:%a}")
def test_first_day_is_a_sunday_and_window_ends_today(user_db, monkeypatch, today):
    _freeze(monkeypatch, today)
    hm = user_db.get_activity_heatmap(weeks=16)
    days = hm["days"]

    first = date.fromisoformat(days[0]["date"])
    # date.weekday(): Monday=0 .. Sunday=6
    assert first.weekday() == 6, (
        f"today={today:%a %Y-%m-%d}: the heatmap starts on {first:%a %Y-%m-%d}; "
        f"the chart puts days[0] in the row it labels as Sunday (#529)"
    )
    assert hm["start_date"] == days[0]["date"]
    assert hm["week_start"] == "sunday"

    # Row i%7 holds the weekday the chart's labels claim, for every square.
    for i, d in enumerate(days):
        wd = (date.fromisoformat(d["date"]).weekday() + 1) % 7   # Sunday=0
        assert wd == i % 7, (i, d["date"])

    # The window still ends today, with no gaps, and spans 16 columns.
    assert days[-1]["date"] == today.isoformat() == hm["end_date"]
    for a, b in zip(days, days[1:]):
        assert date.fromisoformat(b["date"]) - date.fromisoformat(a["date"]) == timedelta(days=1)
    assert -(-len(days) // 7) == 16
    assert hm["total_days"] == len(days)


@pytest.mark.database
def test_streak_fields_are_unaffected_by_the_start_day(user_db, monkeypatch):
    """The streak is computed from all entries, not from the window."""
    today = date(2026, 10, 7)
    _freeze(monkeypatch, today)
    for back in (0, 1, 2, 10, 11):
        _seed_entry(user_db, today - timedelta(days=back))

    hm = user_db.get_activity_heatmap(weeks=16)
    info = user_db.get_streak_info()

    assert hm["current_streak"] == info["current_streak"] == 3
    assert hm["longest_streak"] == info["longest_streak"] == 3
    assert hm["total_active_days"] == 5
    counts = {d["date"]: d["count"] for d in hm["days"]}
    assert counts[today.isoformat()] == 1
    assert counts[(today - timedelta(days=11)).isoformat()] == 1
