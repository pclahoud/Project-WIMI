"""Create and update agree on what finishes an entry (#462).

An entry is complete when it has a user answer, a correct answer, a
reflection, an explanation and at least one primary subject. That is
``QuestionEntry.get_missing_required_fields`` plus the primary-subject check,
the rule the entry form's required markers and ``validateForm()`` tell the
student. ``create_question_entry`` used to restate a subset inline (no
answers), so an entry written in the natural order -- the reflections and a
subject first, the answers later -- was stored complete on its first autosave
and flipped to draft on the next.

The session's ``entries_completed`` follows the entry both ways: up on a
draft-to-complete transition, and down on complete-to-draft, which the update
path never did.
"""
from __future__ import annotations

from datetime import date

import pytest

from database.user_db import UserDatabase

FULL = dict(user_answer="A", correct_answer="B", reflection="<p>R</p>",
            explanation="<p>E</p>")


@pytest.fixture
def world(tmp_path):
    db = UserDatabase(str(tmp_path / "completion.db"), user_id=1, username="c")
    exam = db.create_exam_context(exam_name="Completion", exam_description="")
    subj = db.create_subject_node(exam_context=exam.exam_name, name="Cardiology",
                                  level_type="System")
    session = db.create_review_session(
        exam_context_id=exam.id, session_name="S", date_encountered=date.today(),
        total_questions=10, total_incorrect=5)
    yield {"db": db, "session": session, "subj": subj}
    db.close()


def _completed(db, session_id):
    return db.get_review_session(session_id).entries_completed


@pytest.mark.parametrize("blank", ["user_answer", "correct_answer", "reflection", "explanation"])
def test_create_without_a_required_field_is_a_draft(world, blank):
    db, s = world["db"], world["session"]
    fields = {**FULL, blank: ""}
    entry = db.create_question_entry(review_session_id=s.id,
                                     primary_subject_ids=[world["subj"].id], **fields)
    assert entry.is_draft is True, f"created complete with no {blank}"
    assert blank in (entry.draft_missing_fields or []), entry.draft_missing_fields
    assert _completed(db, s.id) == 0


def test_create_without_a_primary_subject_is_a_draft(world):
    db, s = world["db"], world["session"]
    entry = db.create_question_entry(review_session_id=s.id, **FULL)
    assert entry.is_draft is True
    assert "primary_subjects" in (entry.draft_missing_fields or [])
    assert _completed(db, s.id) == 0


def test_create_with_everything_is_complete_and_counted(world):
    db, s = world["db"], world["session"]
    entry = db.create_question_entry(review_session_id=s.id,
                                     primary_subject_ids=[world["subj"].id], **FULL)
    assert entry.is_draft is False
    assert not entry.draft_missing_fields
    assert _completed(db, s.id) == 1


def test_the_issues_reproduction_no_longer_flips(world):
    """#462's measurement: reflections and a subject, no answers, then an
    update touching nothing material. Before the fix: complete, then draft,
    and the session still counting one finished entry."""
    db, s = world["db"], world["session"]
    entry = db.create_question_entry(
        review_session_id=s.id, user_answer="", correct_answer="",
        reflection="<p>R</p>", explanation="<p>E</p>",
        primary_subject_ids=[world["subj"].id])
    assert entry.is_draft is True
    db.update_question_entry(entry.id, question_id="Q1")
    assert db.get_question_entry(entry.id).is_draft is True
    assert _completed(db, s.id) == 0


def test_create_and_update_derive_the_same_missing_fields(world):
    db, s = world["db"], world["session"]
    entry = db.create_question_entry(review_session_id=s.id, user_answer="",
                                     correct_answer="B", reflection="", explanation="<p>E</p>")
    created = sorted(entry.draft_missing_fields or [])
    db.update_question_entry(entry.id, question_id="Q1")
    updated = sorted(db.get_question_entry(entry.id).draft_missing_fields or [])
    assert created == updated == sorted(["user_answer", "reflection", "primary_subjects"])


def test_complete_to_draft_decrements_and_back_increments(world):
    db, s = world["db"], world["session"]
    entry = db.create_question_entry(review_session_id=s.id,
                                     primary_subject_ids=[world["subj"].id], **FULL)
    assert _completed(db, s.id) == 1

    db.update_question_entry(entry.id, user_answer="")
    assert db.get_question_entry(entry.id).is_draft is True
    assert _completed(db, s.id) == 0, "complete to draft must take the entry back off the count"

    db.update_question_entry(entry.id, user_answer="A")
    assert db.get_question_entry(entry.id).is_draft is False
    assert _completed(db, s.id) == 1

    # A save that changes nothing material moves nothing.
    db.update_question_entry(entry.id, question_id="Q2")
    assert _completed(db, s.id) == 1


def test_the_count_never_goes_below_zero(world):
    db, s = world["db"], world["session"]
    entry = db.create_question_entry(review_session_id=s.id,
                                     primary_subject_ids=[world["subj"].id], **FULL)
    db.execute("UPDATE review_sessions SET entries_completed = 0 WHERE id = ?", (s.id,))
    db.conn.commit()
    db.update_question_entry(entry.id, reflection="")
    assert _completed(db, s.id) == 0


def test_a_completed_session_reopens_when_an_entry_becomes_a_draft(world):
    """A session is completed only while every entry in it is finished
    (#714): an entry that drops back to a draft reopens it, so its card
    offers Continue rather than Review."""
    db, s = world["db"], world["session"]
    entry = db.create_question_entry(review_session_id=s.id,
                                     primary_subject_ids=[world["subj"].id], **FULL)
    db.update_review_session(s.id, session_status="completed")
    assert db.get_review_session(s.id).session_status == "completed"

    db.update_question_entry(entry.id, explanation="")

    session = db.get_review_session(s.id)
    assert session.session_status == "in_progress"
    assert session.completed_at is None
