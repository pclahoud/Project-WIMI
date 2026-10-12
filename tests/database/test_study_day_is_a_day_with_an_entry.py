"""Issue #531 - every streak in WIMI counts a day only if an entry was logged on it.

Owner's decision, 2026-10-07 (#531): *a study day is a day with at least
one entry. A review session started with nothing logged does not count.*

Before this there were two definitions. ``_calculate_streak_info`` (the
analytics streak card, the heatmap payload and Quick Analytics' STREAK
stat via ``getStreakInfo``) counted dates that have entries.
``get_study_streak`` (Patterns & Insights on the dashboard and Quick
Analytics' Top Insight, the plugin API and the MCP tool) counted **any
review-session date**. So with entries yesterday and the day before and a
session started today with nothing in it, one said "3 days, safe" and the
other "2 days, at risk" -- and the at-risk insight never fired.

``get_study_streak`` now reads the one definition, so the assertions here
are on every backend surface at once, against the same fixture.

Days are the student's local calendar days (#286): the backend reads
``datetime.now()``, which the test substitutes, and the session dates are
written by Python from that same clock.
"""
from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import database.domains.analytics_advanced as analytics_advanced
from database import MasterDatabase, UserDatabase

TODAY = date(2026, 10, 7)


@pytest.fixture
def user_db(monkeypatch):
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(TODAY.year, TODAY.month, TODAY.day, 12, 0, 0)

    monkeypatch.setattr(analytics_advanced, "datetime", _Clock)
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(
            username="st531", display_name="Streak 531", user_types=["student"],
        )
        db = UserDatabase(
            db_path=master.ensure_user_database(user.id),
            user_id=user.id, username=user.username,
        )
        yield db
        db.close()
        master.close()


def _session(db, exam_id: int, when: date, entries: int) -> None:
    s = db.create_review_session(
        exam_context_id=exam_id, total_questions=max(entries, 1), total_incorrect=entries,
        session_name=f"st531 {when}", date_encountered=when,
    )
    for _ in range(entries):
        db.create_question_entry(
            review_session_id=s.id, user_answer="A", correct_answer="B",
        )
    db.conn.commit()


@pytest.fixture
def exam_id(user_db):
    """Entries yesterday and the day before; a session today with nothing logged."""
    exam = user_db.create_exam_context(exam_name="ST531", exam_description="").id
    _session(user_db, exam, TODAY - timedelta(days=2), entries=1)
    _session(user_db, exam, TODAY - timedelta(days=1), entries=2)
    _session(user_db, exam, TODAY, entries=0)
    # Precondition, so a fixture that failed to create today's empty session
    # cannot make the assertions below pass for the wrong reason.
    rows = user_db.fetchall(
        "SELECT rs.date_encountered AS d, COUNT(qe.id) AS n FROM review_sessions rs "
        "LEFT JOIN question_entries qe ON qe.review_session_id = rs.id "
        "WHERE rs.exam_context_id = ? GROUP BY rs.id ORDER BY d",
        (exam,),
    )
    assert [(str(r["d"])[:10], r["n"]) for r in rows] == [
        ((TODAY - timedelta(days=2)).isoformat(), 1),
        ((TODAY - timedelta(days=1)).isoformat(), 2),
        (TODAY.isoformat(), 0),
    ]
    return exam


@pytest.mark.database
@pytest.mark.parametrize("scope", ["exam", "all"])
def test_every_streak_surface_agrees(user_db, exam_id, scope):
    ec = exam_id if scope == "exam" else None

    study = user_db.get_study_streak(ec)          # insights, plugin API, MCP
    info = user_db.get_streak_info(ec)            # Quick Analytics STREAK stat
    heat = user_db.get_activity_heatmap(ec)       # analytics streak card

    assert study["current_streak"] == 2, (
        f"get_study_streak counted {study['current_streak']} days; today has a "
        f"session but no entry, so it is not a study day (#531)"
    )
    assert study["streak_at_risk"] is True, study
    assert study["last_entry_date"] == (TODAY - timedelta(days=1)).isoformat(), study
    assert study["days_since_last_entry"] == 1, study

    assert info["current_streak"] == heat["current_streak"] == study["current_streak"]
    assert info["longest_streak"] == heat["longest_streak"] == study["longest_streak"] == 2
    assert info["streak_at_risk"] is study["streak_at_risk"] is True
    assert info["is_active_today"] is False


@pytest.mark.database
def test_the_at_risk_insight_fires_and_names_an_entry(user_db, exam_id):
    insights = user_db.get_patterns_and_insights(exam_id, limit=5)
    at_risk = [i for i in insights if i["type"] == "STREAK_AT_RISK"]
    assert at_risk, f"no STREAK_AT_RISK insight among {[i['type'] for i in insights]}"
    assert at_risk[0]["title"] == "2-day streak at risk!"
    # A session does not keep a streak alive, so the advice must not say it does.
    assert "session" not in at_risk[0]["actionable"].lower(), at_risk[0]["actionable"]
    assert "entry" in at_risk[0]["actionable"].lower(), at_risk[0]["actionable"]


@pytest.mark.database
def test_logging_an_entry_today_makes_today_count(user_db, exam_id):
    """Positive control: the same fixture plus one entry today is a 3-day streak, safe."""
    _session(user_db, exam_id, TODAY, entries=1)
    study = user_db.get_study_streak(exam_id)
    info = user_db.get_streak_info(exam_id)
    assert study["current_streak"] == info["current_streak"] == 3
    assert study["streak_at_risk"] is info["streak_at_risk"] is False
    assert study["days_since_last_entry"] == 0
    assert study["last_entry_date"] == TODAY.isoformat()


@pytest.mark.database
def test_no_entries_at_all_is_no_streak_even_with_sessions(user_db):
    exam = user_db.create_exam_context(exam_name="ST531 empty", exam_description="").id
    _session(user_db, exam, TODAY, entries=0)
    _session(user_db, exam, TODAY - timedelta(days=1), entries=0)
    study = user_db.get_study_streak(exam)
    assert study == {
        "current_streak": 0,
        "longest_streak": 0,
        "streak_at_risk": False,
        "last_entry_date": None,
        "days_since_last_entry": None,
    }
