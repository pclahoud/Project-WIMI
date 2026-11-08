"""The whole-exam import's first-axis answer at the bridge (#605 Wave 2).

``importSubjectHierarchyWithChoice(int, str, str)`` carries the student's
answer to *"Move your existing subjects into an axis?"* beside the file,
never inside it: a file must not be able to carry a student's answer. The
two-argument ``importSubjectHierarchy`` is unchanged, and a choice key written
into the file reaches neither slot.
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


def _file(**extra):
    data = {"dimensions": [
        {"name": "System", "display_order": 1,
         "root_nodes": [{"name": "Cardiovascular", "id": "s1"}]},
        {"name": "Task", "display_order": 2,
         "root_nodes": [{"name": "Diagnosis", "id": "t1"}]},
    ]}
    data.update(extra)
    return json.dumps(data)


def _outside(bridge):
    return sorted(r["name"] for r in bridge.user_db.fetchall(
        "SELECT name FROM subject_nodes WHERE dimension_id IS NULL "
        "AND status = 'active'"))


def test_the_preview_carries_the_offer(bridge, plain):
    exam_id, cardio, renal = plain
    payload = json.loads(bridge.previewSubjectHierarchyImport(exam_id, _file()))
    assert payload["success"] is True, payload
    offer = payload["data"]["first_axis_offer"]
    assert offer["axes"] == [{"index": 0, "name": "System"},
                             {"index": 1, "name": "Task"}]
    assert [r["subject_id"] for r in offer["roots"]] == [cardio, renal]


def test_the_choice_slot_moves_and_reports_it_apart_from_counts(bridge, plain):
    exam_id, cardio, renal = plain
    choice = {"action": "move", "assignments": [
        {"subject_id": cardio, "axis": 0}, {"subject_id": renal, "axis": 1}]}
    payload = json.loads(bridge.importSubjectHierarchyWithChoice(
        exam_id, _file(), json.dumps(choice)))
    assert payload["success"] is True, payload
    data = payload["data"]
    assert data["moved_existing"]["moved"] == 3
    assert [a["name"] for a in data["moved_existing"]["by_axis"]] == [
        "System", "Task"]
    assert data["counts"]["added"] == 2
    assert _outside(bridge) == []


def test_a_null_choice_is_the_plain_import(bridge, plain):
    exam_id, _, _ = plain
    payload = json.loads(bridge.importSubjectHierarchyWithChoice(
        exam_id, _file(), "null"))
    assert payload["success"] is True, payload
    assert payload["data"]["moved_existing"] is None
    assert _outside(bridge) == ["AFib", "Cardio", "Renal"]


def test_the_two_argument_slot_is_unchanged(bridge, plain):
    exam_id, _, _ = plain
    payload = json.loads(bridge.importSubjectHierarchy(exam_id, _file()))
    assert payload["success"] is True, payload
    assert payload["data"]["moved_existing"] is None
    assert _outside(bridge) == ["AFib", "Cardio", "Renal"]


@pytest.mark.parametrize("key", ["existing_subjects", "choice",
                                 "first_axis_choice"])
def test_a_choice_written_into_the_file_is_ignored(bridge, plain, key):
    """A file must not be able to carry a student's answer."""
    exam_id, cardio, renal = plain
    planted = {"action": "move", "assignments": [
        {"subject_id": cardio, "axis": 0}, {"subject_id": renal, "axis": 0}]}
    for call in (
        lambda: bridge.importSubjectHierarchy(exam_id, _file(**{key: planted})),
        lambda: bridge.importSubjectHierarchyWithChoice(
            exam_id, _file(**{key: planted}), ""),
    ):
        payload = json.loads(call())
        assert payload["success"] is True, payload
        assert payload["data"]["moved_existing"] is None
        assert _outside(bridge) == ["AFib", "Cardio", "Renal"]


def test_a_refused_move_is_success_false_and_imports_nothing(bridge, plain):
    exam_id, cardio, renal = plain
    bridge.user_db.execute(
        "UPDATE subject_nodes SET import_id = 's1' WHERE id = ?", (cardio,))
    bridge.user_db.conn.commit()
    choice = {"action": "move", "assignments": [
        {"subject_id": cardio, "axis": 0}]}
    payload = json.loads(bridge.importSubjectHierarchyWithChoice(
        exam_id, _file(), json.dumps(choice)))
    assert payload["success"] is False
    assert "Nothing was saved." in payload["error"]
    assert bridge.user_db.get_exam_dimensions(exam_id) == []


@pytest.mark.parametrize("raw", ["{not json", "[1]", "\"move\""])
def test_an_unreadable_choice_is_refused(bridge, plain, raw):
    exam_id, _, _ = plain
    payload = json.loads(bridge.importSubjectHierarchyWithChoice(
        exam_id, _file(), raw))
    assert payload["success"] is False
    assert payload["error"].startswith("Nothing was saved.")
    assert bridge.user_db.get_exam_dimensions(exam_id) == []


def test_a_choice_on_a_single_tree_file_is_refused(bridge, plain):
    exam_id, _, _ = plain
    payload = json.loads(bridge.importSubjectHierarchyWithChoice(
        exam_id, json.dumps({"root_nodes": [{"name": "New"}]}),
        json.dumps({"action": "aside"})))
    assert payload["success"] is False
    assert payload["error"].startswith("Nothing was saved.")
    assert "New" not in _outside(bridge)
