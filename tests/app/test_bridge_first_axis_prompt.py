"""The first-axis prompt's bridge surface (#605 Wave 1).

``saveExamEdit`` carries the student's answer about the subjects an exam
already has, and reports what moved. A refused move must reach the page as
``success=false`` with the sentence, never as a success over half the work
(#240): the database rolls the new axis back with it, and these check the
slot does not turn that into anything else on the way out.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase

EXAM = "Plain Exam"


@pytest.fixture
def bridge():
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp), error_logger=None)
        master.bootstrap_first_user(username="admin", display_name="Admin")
        user = UserDatabase(db_path=Path(tmp) / "user.db", user_id=1,
                            username="admin")
        yield DatabaseBridge(master_db=master, user_db=user)
        user.close()
        master.close()


@pytest.fixture
def plain(bridge):
    """A Simple exam with Cardio > AFib and Renal, and no axes."""
    db = bridge.user_db
    exam = db.create_exam_context(exam_name=EXAM, exam_description="#605")
    cardio = db.create_subject_node(EXAM, "Cardio", "System").id
    db.create_subject_node(EXAM, "AFib", "Topic", parent_id=cardio)
    renal = db.create_subject_node(EXAM, "Renal", "System").id
    db.conn.commit()
    return exam.id, cardio, renal


def _save(bridge, exam_id, **payload):
    payload.setdefault("settings", {})
    payload.setdefault("length", None)
    return json.loads(bridge.saveExamEdit(exam_id, json.dumps(payload)))


def _new(*names):
    return [{"id": None, "name": n, "description": "", "is_required": True,
             "allow_multiple": False} for n in names]


def test_the_preview_slot_answers_on_an_exam_with_no_axes(bridge, plain):
    exam_id, cardio, renal = plain
    payload = json.loads(bridge.getExistingSubjectsForFirstAxis(exam_id))
    assert payload["success"] is True, payload
    data = payload["data"]
    assert data["has_active_axis"] is False
    assert data["subject_count"] == 3
    assert [r["subject_id"] for r in data["roots"]] == [cardio, renal]


def test_save_exam_edit_passes_the_move_through(bridge, plain):
    exam_id, cardio, renal = plain
    payload = _save(bridge, exam_id, dimensions=_new("System", "Task"),
                    first_axis=True,
                    existing_subjects={"action": "move", "assignments": [
                        {"subject_id": cardio, "axis": 0},
                        {"subject_id": renal, "axis": 1}]})
    assert payload["success"] is True, payload
    system, task = payload["data"]["dimension_ids"]
    assert payload["data"]["moved_existing"] == {
        "action": "move", "moved": 3,
        "by_axis": [{"axis_id": system, "name": "System", "moved": 2},
                    {"axis_id": task, "name": "Task", "moved": 1}]}


def test_save_exam_edit_without_a_question_reports_none(bridge, plain):
    exam_id, _cardio, _renal = plain
    payload = _save(bridge, exam_id, dimensions=None)
    assert payload["success"] is True, payload
    assert payload["data"]["moved_existing"] is None


def test_a_failed_move_is_success_false_and_saves_nothing(bridge, plain, monkeypatch):
    exam_id, cardio, _renal = plain
    monkeypatch.setattr(bridge.user_db, "move_subjects_into_axis",
                        lambda ids, dim: {"success": False,
                                          "error": "That axis no longer exists."})
    payload = _save(bridge, exam_id, settings={"exam_name": "Renamed"},
                    dimensions=_new("System"), first_axis=True,
                    existing_subjects={"action": "move", "assignments": [
                        {"subject_id": cardio, "axis": 0}]})
    assert payload["success"] is False
    assert payload["error"].startswith("Nothing was saved."), payload["error"]
    assert "That axis no longer exists." in payload["error"]
    assert bridge.user_db.get_exam_dimensions(exam_id) == []
    name = bridge.user_db.fetchone(
        "SELECT exam_name FROM exam_contexts WHERE id = ?", (exam_id,))["exam_name"]
    assert name == EXAM, "a refused move still saved the exam's details"


def test_an_exam_that_gained_an_axis_since_is_refused(bridge, plain):
    exam_id, _cardio, _renal = plain
    bridge.user_db.create_dimension(exam_id=exam_id, name="Other", display_order=1)
    bridge.user_db.conn.commit()
    payload = _save(bridge, exam_id, dimensions=_new("System"), first_axis=True)
    assert payload["success"] is False
    assert "gained an axis since" in payload["error"], payload["error"]
