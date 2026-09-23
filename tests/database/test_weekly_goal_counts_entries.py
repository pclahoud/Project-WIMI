"""A weekly goal counts entries logged, not questions answered (issue #58).

``set_weekly_goal`` stores the goal as ``goal_type = 'weekly_entries'``,
but every progress path used to dispatch it to a counter that sums
``review_sessions.total_questions``. A goal named "entries" therefore
counted questions: logging an entry moved nothing unless the session's
question total happened to move with it, and ``_count_entries_in_period``
-- the only counter that excludes drafts -- was reachable by no goal type
anything creates.

The owner's decision, 2026-09-14, routed ``weekly_entries`` to
``_count_entries_in_period`` at every site. It also kept a
``weekly_questions`` branch counting questions; issue #71 then found that
``user_goals``' CHECK constraint forbids that type, nothing had ever
created one, and the branch was unreachable. Decided 2026-09-15: drop it.
**One weekly goal type, entries logged.**

So what these tests pin is that a weekly goal moves with entries and
*not* with questions answered. One test per dispatch site, because the
sites drift independently -- that is how the bug arose in the first
place:

==================================  =====================================
site                                exercised by
==================================  =====================================
``get_user_goals``                  ``test_get_user_goals_*``
``get_goal_history``                ``test_goal_history_*``
==================================  =====================================

#58 listed two more sites, ``_ensure_goal_period`` and
``update_goal_progress``. Issue #70 removed both: progress is recounted
on every read, so nothing stamps it and there is no notifier to call.
The tests for those two sites went with them.

The seed keeps entries and questions far apart on purpose (2 finished
entries against a 40-question session) so that no assertion below can
pass by coincidence.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from database.user_db import UserDatabase


SESSION_QUESTIONS = 40
FINISHED_ENTRIES = 2
SEEDED_DRAFTS = 1


def _week_bounds() -> tuple[date, date]:
    """The Monday–Sunday window every goal path computes for itself."""
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


def _make_goal(db, goal_type: str, target: int, exam_context_id: int) -> int:
    """Insert an active goal with no ``goal_periods`` row.

    ``set_weekly_goal`` writes its own period row, and these tests want
    the goal on its own.
    """
    cursor = db.execute(
        """
        INSERT INTO user_goals (user_id, goal_type, target_value, exam_context_id)
        VALUES (?, ?, ?, ?)
        """,
        (db.user_id, goal_type, target, exam_context_id),
    )
    db.conn.commit()
    return cursor.lastrowid


@pytest.fixture
def seed(tmp_path):
    """One exam, one 40-question session, 2 finished entries and 1 draft."""
    db = UserDatabase(tmp_path / "weekly_goals.db", user_id=1, username="wg_user")

    exam = db.create_exam_context(
        exam_name="Weekly Goal Exam",
        exam_description="issue #58 — weekly goals count entries",
        hierarchy_levels=["System", "Topic"],
    )
    subject = db.create_subject_node(
        exam_context=exam.exam_name,
        name="WG Renal",
        level_type="Topic",
        exam_weight_low=10,
        exam_weight_high=10,
    )
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=SESSION_QUESTIONS,
        total_incorrect=3,
        session_name="WG session",
        date_encountered=date.today(),
    )

    for _ in range(FINISHED_ENTRIES):
        entry = _log_entry(db, session.id, subject.id)
        assert not entry.is_draft, "seed produced a draft, not a finished entry"
    for _ in range(SEEDED_DRAFTS):
        draft = _log_entry(db, session.id, subject.id, draft=True)
        assert draft.is_draft, "seed produced a finished entry, not a draft"

    db.conn.commit()

    yield {
        "db": db,
        "exam_id": exam.id,
        "subject_id": subject.id,
        "session_id": session.id,
    }
    db.close()


# ============================================== site 1: get_user_goals


@pytest.mark.database
def test_get_user_goals_counts_entries_for_weekly_entries(seed):
    """Site: ``get_user_goals`` — the surface the widget reads."""
    db = seed["db"]
    _make_goal(db, "weekly_entries", 20, seed["exam_id"])

    goal = db.get_user_goals(exam_context_id=seed["exam_id"])[0]

    assert goal["current_value"] == FINISHED_ENTRIES, (
        "a weekly_entries goal reported "
        f"{goal['current_value']} — the session's question total, not the "
        f"{FINISHED_ENTRIES} entries logged. Logging an entry has to move "
        "the goal that is named after entries"
    )


# ============================================== site 2: get_goal_history


@pytest.mark.database
def test_goal_history_counts_entries_for_weekly_entries(seed):
    """Site: ``get_goal_history`` — the per-week fallback count."""
    db = seed["db"]
    _make_goal(db, "weekly_entries", 20, seed["exam_id"])

    this_week = db.get_goal_history(exam_context_id=seed["exam_id"], weeks=4)[0]

    assert this_week["achieved"] == FINISHED_ENTRIES, (
        "the history bars for a weekly_entries goal were drawn from the "
        f"question totals: {this_week!r}"
    )


@pytest.mark.database
def test_set_weekly_goal_creates_an_entry_counting_goal(seed):
    """End to end through the public setter, which is the only creator.

    ``set_weekly_goal`` writes ``goal_type = 'weekly_entries'`` and its
    own period in one call, so this is what a student actually gets.
    """
    db = seed["db"]
    db.set_weekly_goal(target_questions=20, exam_context_id=seed["exam_id"])

    goal = db.get_user_goals(exam_context_id=seed["exam_id"])[0]

    assert goal["goal_type"] == "weekly_entries"
    assert goal["current_value"] == FINISHED_ENTRIES, (
        "the goal a student gets from the Set Goal button still counts "
        f"questions: {goal!r}"
    )


# ============================================ entries, never questions


@pytest.mark.database
def test_a_weekly_goal_tracks_entries_and_ignores_questions_answered(seed):
    """The point of #58, in one test.

    A weekly goal advances when an entry is logged and *not* when a
    session's question count moves without one. Before the fix it did
    exactly the opposite, and there is no longer a second goal type to
    tell the two behaviours apart with: #71 removed ``weekly_questions``,
    so the only evidence that the right counter is wired up is that the
    goal responds to one of these events and not the other.
    """
    db = seed["db"]
    _make_goal(db, "weekly_entries", 20, seed["exam_id"])

    def progress() -> int:
        return db.get_user_goals(exam_context_id=seed["exam_id"])[0]["current_value"]

    assert progress() == FINISHED_ENTRIES, (
        f"the goal did not start at the entries logged: {progress()}"
    )

    # (1) Questions answered move without an entry being logged.
    db.execute(
        "UPDATE review_sessions SET total_questions = ? WHERE id = ?",
        (SESSION_QUESTIONS + 15, seed["session_id"]),
    )
    db.conn.commit()

    assert progress() == FINISHED_ENTRIES, (
        "answering more questions advanced the goal; the student gets "
        "credit for work they have not reflected on"
    )

    # (2) An entry is logged without the question total moving.
    _log_entry(db, seed["session_id"], seed["subject_id"])

    assert progress() == FINISHED_ENTRIES + 1, (
        "logging an entry did not advance the goal — the whole of issue #58"
    )


# ======================================================== drafts (#12)


@pytest.mark.database
def test_drafts_do_not_advance_the_goal_and_are_reported(seed):
    """Issue #12's carve-out, reachable for the first time.

    The exclusion lives in ``_count_entries_in_period``, which nothing
    called until #58 routed ``weekly_entries`` to it. So this assertion
    could not have held before, whatever the counter said.
    """
    db = seed["db"]
    _make_goal(db, "weekly_entries", 20, seed["exam_id"])

    before = db.get_user_goals(exam_context_id=seed["exam_id"])[0]
    assert before["current_value"] == FINISHED_ENTRIES
    assert before["drafts_remaining"] == SEEDED_DRAFTS

    _log_entry(db, seed["session_id"], seed["subject_id"], draft=True)
    after = db.get_user_goals(exam_context_id=seed["exam_id"])[0]

    assert after["current_value"] == FINISHED_ENTRIES, (
        "an unfinished draft advanced the goal; 'log 20 entries this "
        "week' means 20 finished ones"
    )
    assert after["drafts_remaining"] == SEEDED_DRAFTS + 1, (
        "the draft the goal declined to count went unreported, which is "
        "the information gap #12 closed"
    )


@pytest.mark.database
def test_finishing_a_draft_advances_the_goal(seed):
    """"Finishing a draft moves nothing" was the symptom #58 names."""
    db = seed["db"]
    _make_goal(db, "weekly_entries", 20, seed["exam_id"])
    draft = _log_entry(db, seed["session_id"], seed["subject_id"], draft=True)

    db.update_question_entry(draft.id, reflection="I know why now.")
    db.conn.commit()

    goal = db.get_user_goals(exam_context_id=seed["exam_id"])[0]

    assert goal["current_value"] == FINISHED_ENTRIES + 1, (
        "finishing a draft left the weekly goal where it was"
    )
    assert goal["drafts_remaining"] == SEEDED_DRAFTS, (
        "the finished draft is still counted as outstanding: "
        f"{goal['drafts_remaining']}"
    )
