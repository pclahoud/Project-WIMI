"""Session templates (#778, owner decision 10: in v1).

A template is a preset of the fields a plan carries; a plan made from one
copies them and an explicit argument wins. Names are unique per exam over
ACTIVE rows only (a partial unique index, not a table UNIQUE, so archiving
frees the name: #244's lesson), and an exam-less template's name is unique
among exam-less templates.
"""
from __future__ import annotations

import pytest

from database.exceptions import PlannedSessionError
from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    instance = UserDatabase(tmp_path / "tpl.db", user_id=1, username="tpl_user")
    yield instance
    instance.close()


@pytest.fixture
def exam(db):
    return db.create_exam_context(exam_name="Step X")


@pytest.mark.database
def test_create_list_update_archive(db, exam):
    t = db.create_session_template("Morning", exam_context_id=exam.id, default_start_time="08:30",
                                   default_duration_minutes=45, default_questions=20, notes="n")
    assert t["is_active"] == 1 and t["name"] == "Morning"
    assert [x["name"] for x in db.get_session_templates(exam_context_id=exam.id)] == ["Morning"]
    t = db.update_session_template(t["id"], name="Early", default_questions=25)
    assert (t["name"], t["default_questions"], t["default_duration_minutes"]) == ("Early", 25, 45)
    assert db.archive_session_template(t["id"])["is_active"] == 0
    assert db.get_session_templates(exam_context_id=exam.id) == []
    assert len(db.get_session_templates(exam_context_id=exam.id, include_archived=True)) == 1


@pytest.mark.database
def test_names_are_unique_over_active_rows_and_archiving_frees_them(db, exam):
    t = db.create_session_template("Morning", exam_context_id=exam.id)
    with pytest.raises(PlannedSessionError, match="already exists"):
        db.create_session_template("Morning", exam_context_id=exam.id)
    db.archive_session_template(t["id"])
    again = db.create_session_template("Morning", exam_context_id=exam.id)
    assert again["id"] != t["id"]


@pytest.mark.database
def test_exam_less_templates_are_unique_among_themselves(db, exam):
    db.create_session_template("Review")
    with pytest.raises(PlannedSessionError, match="already exists"):
        db.create_session_template("Review")
    # Same name under an exam is a different template.
    db.create_session_template("Review", exam_context_id=exam.id)
    names = [x["exam_context_id"] for x in db.get_session_templates(exam_context_id=exam.id)]
    assert sorted(names, key=lambda v: (v is None, v)) == [exam.id, None]


@pytest.mark.database
@pytest.mark.parametrize("kwargs, fragment", [
    ({"name": "  "}, "needs a name"),
    ({"name": "x", "default_start_time": "8:30"}, "HH:MM"),
    ({"name": "x", "default_duration_minutes": 2000}, "between 1 and 1440"),
    ({"name": "x", "default_questions": 0}, "above zero"),
    ({"name": "x", "exam_context_id": 555}, "not one of this profile's exams"),
])
def test_refusals_are_sentences(db, kwargs, fragment):
    with pytest.raises(PlannedSessionError) as exc:
        db.create_session_template(**kwargs)
    assert fragment in str(exc.value)


@pytest.mark.database
def test_a_plan_from_a_template_copies_defaults_and_an_argument_wins(db, exam):
    bank = db.create_question_source(source_name="Bank", exam_context=exam.exam_name)
    t = db.create_session_template("Morning", exam_context_id=exam.id, question_source_id=bank.id,
                                   default_start_time="08:30", default_duration_minutes=45, default_questions=20)
    p = db.create_planned_session("2026-10-14", template_id=t["id"], planned_questions=30)
    assert p["exam_context_id"] == exam.id and p["question_source_id"] == bank.id
    assert (p["planned_start_time"], p["planned_duration_minutes"], p["planned_questions"]) == ("08:30", 45, 30)
    assert p["title"] == "Morning" and p["template_id"] == t["id"]


@pytest.mark.database
def test_archiving_a_template_leaves_its_plans_linked(db, exam):
    t = db.create_session_template("Morning", exam_context_id=exam.id)
    p = db.create_planned_session("2026-10-14", template_id=t["id"])
    db.archive_session_template(t["id"])
    assert db.get_planned_session(p["id"])["template_id"] == t["id"]


@pytest.mark.database
def test_another_profiles_template_is_invisible(db, exam, tmp_path):
    t = db.create_session_template("Mine", exam_context_id=exam.id)
    other = UserDatabase(tmp_path / "tpl.db", user_id=2, username="other")
    try:
        assert other.get_session_template(t["id"]) is None
        with pytest.raises(PlannedSessionError, match="not one of this profile's templates"):
            other.create_planned_session("2026-10-14", template_id=t["id"])
    finally:
        other.close()
