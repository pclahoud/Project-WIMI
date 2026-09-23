"""A weekly goal's progress is live, not a stamp from the day it was set (#70).

``get_user_goals`` used to return the **stored** ``goal_periods.achieved_value``
whenever a period row existed for the current week, and only fall back to a
live count when there was none. ``set_weekly_goal`` writes that period row
through ``_ensure_goal_period``, so the achievement was stamped at the moment
the goal was created and never moved again:

    after set_weekly_goal:               1
    after logging 2 more entries:        1     <-- expected 3
    after re-saving the goal:            1     <-- expected 3
    after explicit update_goal_progress: 3

``update_goal_progress`` was the intended notifier -- its docstring said
"Called when a new entry is created or review session is completed" -- and it
had **no callers anywhere in the repo**. The goal was therefore accurate in
every week except the one the student actually set it in, which is the week
they are most likely to watch it.

The fix (issue #70): progress is **computed from the entries every time it is
read**. ``goal_periods`` keeps the per-week ``target_value`` -- genuine history
that nothing else records -- and stops being consulted for achievement. No
write path has to remember to notify anything, so this class of staleness
cannot come back; a notifier that every future caller must remember is exactly
what went missing here.

These tests pin the *reading* end of that. The counter each goal type reads is
issue #58's business and lives in ``test_weekly_goal_counts_entries.py``.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from database.user_db import UserDatabase


SESSION_QUESTIONS = 40
SEEDED_ENTRIES = 1
TARGET = 20


def _week_bounds() -> tuple[date, date]:
    """The Monday-Sunday window every goal path computes for itself."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    return week_start, week_start + timedelta(days=6)


def _log_entry(db, session_id: int, subject_id: int, *, draft: bool = False):
    """Log one entry. Omitting the reflection is what makes it a draft."""
    return db.create_question_entry(
        review_session_id=session_id,
        user_answer="A",
        correct_answer="B",
        perceived_difficulty=3,
        reflection=None if draft else "I misread the stem.",
        explanation="Preload versus afterload.",
        primary_subject_ids=[subject_id],
    )


def _period_rows(db) -> list[dict]:
    return [dict(r) for r in db.fetchall("SELECT * FROM goal_periods ORDER BY id")]


@pytest.fixture
def seed(tmp_path):
    """One exam, one 40-question session and a single finished entry.

    Entries and questions are kept far apart on purpose so no assertion
    below can pass by reading the wrong counter.
    """
    db = UserDatabase(tmp_path / "live_goals.db", user_id=1, username="lg_user")

    exam = db.create_exam_context(
        exam_name="Live Goal Exam",
        exam_description="issue #70 — goal progress must not freeze",
        hierarchy_levels=["System", "Topic"],
    )
    subject = db.create_subject_node(
        exam_context=exam.exam_name,
        name="LG Cardio",
        level_type="Topic",
        exam_weight_low=10,
        exam_weight_high=10,
    )
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=SESSION_QUESTIONS,
        total_incorrect=3,
        session_name="LG session",
        date_encountered=date.today(),
    )

    for _ in range(SEEDED_ENTRIES):
        entry = _log_entry(db, session.id, subject.id)
        assert not entry.is_draft, "seed produced a draft, not a finished entry"

    db.conn.commit()

    yield {
        "db": db,
        "exam_id": exam.id,
        "subject_id": subject.id,
        "session_id": session.id,
    }
    db.close()


def _progress(db, exam_id: int) -> int:
    return db.get_user_goals(exam_context_id=exam_id)[0]["current_value"]


@pytest.mark.database
def test_progress_advances_in_the_week_the_goal_was_set(seed):
    """The reproduction from issue #70, verbatim.

    ``set_weekly_goal`` stamps the week's period row on creation, so
    before the fix every reading below returned the 1 entry that existed
    at that instant.
    """
    db, exam_id = seed["db"], seed["exam_id"]
    db.set_weekly_goal(target_questions=TARGET, exam_context_id=exam_id)

    assert _progress(db, exam_id) == SEEDED_ENTRIES

    _log_entry(db, seed["session_id"], seed["subject_id"])
    _log_entry(db, seed["session_id"], seed["subject_id"])

    assert _progress(db, exam_id) == SEEDED_ENTRIES + 2, (
        "the weekly goal froze at the value stamped when it was set. Two "
        "more entries were logged in the same week and the card would "
        "have shown neither until the following Monday — the week the "
        "student is most likely to be watching it (issue #70)"
    )


@pytest.mark.database
def test_resaving_the_goal_does_not_unfreeze_it_because_nothing_is_frozen(seed):
    """Re-saving was the only workaround, and it did not work either.

    ``_ensure_goal_period``'s existing-period branch updates
    ``target_value`` and leaves ``achieved_value`` alone, so a student
    who re-saved the goal to "refresh" it still saw the stale number.
    Progress is read live now, so the value is right before and after.
    """
    db, exam_id = seed["db"], seed["exam_id"]
    db.set_weekly_goal(target_questions=TARGET, exam_context_id=exam_id)
    _log_entry(db, seed["session_id"], seed["subject_id"])

    before = _progress(db, exam_id)
    db.set_weekly_goal(target_questions=TARGET + 5, exam_context_id=exam_id)
    after = db.get_user_goals(exam_context_id=exam_id)[0]

    assert before == SEEDED_ENTRIES + 1, f"progress was stale before the re-save: {before}"
    assert after["current_value"] == SEEDED_ENTRIES + 1, (
        f"re-saving the goal changed its progress: {after!r}"
    )
    assert after["target_value"] == TARGET + 5, (
        "re-saving did not update the target it was called to change"
    )


@pytest.mark.database
def test_a_stale_stored_period_cannot_win_over_the_live_count(seed):
    """The structural half of the fix.

    Any stored ``achieved_value`` for the current week is a number
    written at some earlier instant. Real databases already hold stale
    ones, written before this fix; forging an absurd value here proves
    the read path no longer consults them at all rather than merely
    keeping them fresh by some new notifier.
    """
    db, exam_id = seed["db"], seed["exam_id"]
    db.set_weekly_goal(target_questions=TARGET, exam_context_id=exam_id)

    db.execute("UPDATE goal_periods SET achieved_value = 999, is_complete = TRUE")
    db.conn.commit()

    goal = db.get_user_goals(exam_context_id=exam_id)[0]

    assert goal["current_value"] == SEEDED_ENTRIES, (
        "the stored period value reached the student: "
        f"{goal['current_value']}. Progress must be counted from the "
        "entries, not read back from a stamp (issue #70)"
    )
    assert goal["is_complete"] is False, (
        "completion was taken from the stored row rather than derived "
        f"from live progress against the target: {goal!r}"
    )


@pytest.mark.database
def test_goal_history_reports_the_current_week_live(seed):
    """The card is not the only surface; the history bars read the same rows.

    ``get_goal_history`` preferred the stored period exactly as
    ``get_user_goals`` did, so the current week's bar froze with it.
    """
    db, exam_id = seed["db"], seed["exam_id"]
    db.set_weekly_goal(target_questions=TARGET, exam_context_id=exam_id)
    _log_entry(db, seed["session_id"], seed["subject_id"])

    this_week = db.get_goal_history(exam_context_id=exam_id, weeks=4)[0]
    week_start, _ = _week_bounds()

    assert this_week["week_start"] == week_start.isoformat()
    assert this_week["achieved"] == SEEDED_ENTRIES + 1, (
        f"the current week's history bar is still the stamp: {this_week!r}"
    )


@pytest.mark.database
def test_the_stored_target_is_still_per_week_history(seed):
    """What ``goal_periods`` is *for* after the fix.

    The achievement is recomputed, but the target a student had set in a
    given week is not derivable from anything else, so the row remains
    the record of it. A past week keeps the target it was saved with
    even after the goal is raised.
    """
    db, exam_id = seed["db"], seed["exam_id"]
    week_start, week_end = _week_bounds()
    db.set_weekly_goal(target_questions=TARGET, exam_context_id=exam_id)

    goal_id = db.fetchone("SELECT id FROM user_goals")["id"]
    last_week = week_start - timedelta(days=7)
    db.execute(
        "INSERT INTO goal_periods (goal_id, period_start, period_end, "
        "target_value, achieved_value) VALUES (?, ?, ?, ?, ?)",
        (goal_id, last_week.isoformat(),
         (last_week + timedelta(days=6)).isoformat(), 5, 5),
    )
    db.conn.commit()
    db.set_weekly_goal(target_questions=TARGET + 30, exam_context_id=exam_id)

    history = {h["week_start"]: h for h in db.get_goal_history(
        exam_context_id=exam_id, weeks=4)}

    assert history[last_week.isoformat()]["target"] == 5, (
        "raising this week's goal rewrote last week's target; the stored "
        "period is the only record of what the target was then"
    )
    assert history[week_start.isoformat()]["target"] == TARGET + 30
    assert week_end >= date.today()


@pytest.mark.database
def test_reading_goals_does_not_write(seed):
    """Reads stay reads.

    Recomputing on read is only safe if it stays a read: ``get_user_goals``
    is also called by the read-only ``wimi-db`` MCP server
    (``src/mcp_server.py``), which would fail outright on a write. So the
    fix recomputes rather than refreshing the stored row in place.
    """
    db, exam_id = seed["db"], seed["exam_id"]
    db.set_weekly_goal(target_questions=TARGET, exam_context_id=exam_id)
    before = _period_rows(db)

    _log_entry(db, seed["session_id"], seed["subject_id"])
    db.get_user_goals(exam_context_id=exam_id)
    db.get_goal_history(exam_context_id=exam_id, weeks=4)

    assert _period_rows(db) == before, (
        "reading goal progress mutated goal_periods; a read that writes "
        "breaks the read-only MCP server and reintroduces a stamp that "
        "can go stale"
    )
