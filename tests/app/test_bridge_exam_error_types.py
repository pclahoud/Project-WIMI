"""Bridge tests for #888's slots: an exam's list of error types.

``addTagToExam``, ``removeTagFromExam``, ``getTagsNotOnExam`` and the two
registered arities of ``deleteTag``. The domain is covered in
``tests/database/test_universal_error_types.py``; these hold the JSON
contract, the TagError -> success=false mapping and the no-user_db guards.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase

A, B = "Exam A", "Exam B"


@pytest.fixture
def env(tmp_path: Path):
    master = MasterDatabase(data_dir=tmp_path / "master", error_logger=None)
    master.bootstrap_first_user(username="test_admin", display_name="Test Admin")
    db = UserDatabase(db_path=tmp_path / "user.db", user_id=1, username="test_user")
    exams = {name: db.create_exam_context(exam_name=name) for name in (A, B)}
    group = db.create_tag_group(A, "Habits")
    x = db.create_hierarchical_tag(A, "X", group.id)
    yield DatabaseBridge(master_db=master, user_db=db), db, exams, group, x
    db.close()
    master.close()


@pytest.fixture
def bridge_no_user(tmp_path: Path):
    master = MasterDatabase(data_dir=tmp_path / "master", error_logger=None)
    yield DatabaseBridge(master_db=master, user_db=None)
    master.close()


def _ok(response: str):
    payload = json.loads(response)
    assert payload["success"] is True, payload.get("error")
    return payload.get("data")


def _err(response: str) -> str:
    payload = json.loads(response)
    assert payload["success"] is False, "expected an error"
    assert "data" not in payload
    return payload["error"]


def _names(bridge, exam):
    out = []
    for node in _ok(bridge.getTagHierarchy(exam)):
        out.append(node["name"])
        out.extend(c["name"] for c in node["children"])
    return out


def test_the_hierarchy_carries_the_counts_the_modal_needs(env):
    bridge, *_ = env
    node = _ok(bridge.getTagHierarchy(A))[0]["children"][0]
    assert {"other_exam_count", "entry_count_all", "usage_count"} <= set(node)
    assert node["other_exam_count"] == 0


def test_get_tags_not_on_exam_then_add(env):
    bridge, db, exams, group, x = env
    tree = _ok(bridge.getTagsNotOnExam(B))
    assert [(n["id"], [c["id"] for c in n["children"]]) for n in tree] == [
        (group.id, [x.id])]
    assert _names(bridge, B) == []

    data = _ok(bridge.addTagToExam(B, x.id))

    assert data == {"id": x.id, "name": "X", "is_group": False, "added": 2}
    assert _names(bridge, B) == ["Habits", "X"]
    assert _ok(bridge.getTagsNotOnExam(B)) == []


def test_remove_from_this_exam_keeps_entries(env):
    bridge, db, exams, group, x = env
    _ok(bridge.addTagToExam(B, x.id))
    session = db.create_review_session(exam_context_id=exams[B].id,
                                       total_questions=1, total_incorrect=1,
                                       date_encountered=date.today())
    entry = db.create_question_entry(session.id, "a", "b", tag_ids=[x.id])

    data = _ok(bridge.removeTagFromExam(B, x.id))

    assert data["removed"] == 1 and data["entries_keeping"] == 1
    assert "X" not in _names(bridge, B)
    assert db.fetchone("SELECT 1 FROM entry_tags WHERE question_entry_id = ?"
                       " AND tag_id = ?", (entry.id, x.id))


def test_remove_what_the_exam_does_not_offer_is_a_sentence(env):
    bridge, db, exams, group, x = env
    assert _err(bridge.removeTagFromExam(B, x.id)) == '"X" is not offered on this exam.'


def test_an_unknown_exam_is_a_sentence(env):
    bridge, db, exams, group, x = env
    for response in (bridge.addTagToExam("Nope", x.id),
                     bridge.removeTagFromExam("Nope", x.id),
                     bridge.getTagsNotOnExam("Nope")):
        assert _err(response) == 'There is no exam called "Nope".'


def test_delete_tag_two_arities(env):
    """deleteTag(int) and deleteTag(int, str) are both registered, as
    deleteSubjectNode's two are; each applies decision 4b its own way."""
    bridge, db, exams, group, x = env
    _ok(bridge.addTagToExam(B, x.id))

    assert "still offered on" in _err(bridge.deleteTag(x.id))
    assert 'still offered on "Exam B"' in _err(bridge.deleteTag(x.id, A))
    assert db.get_tag(x.id) is not None

    _ok(bridge.removeTagFromExam(B, x.id))
    assert 'still offered on "Exam A"' in _err(bridge.deleteTag(x.id, B))
    data = _ok(bridge.deleteTag(x.id, A))
    assert data == {"id": x.id, "name": "X", "affected_entries": 0}
    assert db.get_tag(x.id) is None


def test_the_one_argument_form_still_deletes_a_type_one_exam_lists(env):
    bridge, db, exams, group, x = env
    assert _ok(bridge.deleteTag(x.id))["name"] == "X"


def test_both_arities_are_registered():
    """QWebChannel resolves by argument count; both must exist on the slot."""
    meta = DatabaseBridge.staticMetaObject
    signatures = {bytes(meta.method(i).methodSignature()).decode()
                  for i in range(meta.methodCount())}
    assert {"deleteTag(int)", "deleteTag(int,QString)",
            "addTagToExam(QString,int)", "removeTagFromExam(QString,int)",
            "getTagsNotOnExam(QString)"} <= signatures


@pytest.mark.parametrize("call", [
    lambda b: b.addTagToExam(A, 1),
    lambda b: b.removeTagFromExam(A, 1),
    lambda b: b.getTagsNotOnExam(A),
    lambda b: b.deleteTag(1, A),
    lambda b: b.deleteTag(1),
])
def test_no_user_db_guard(bridge_no_user, call):
    assert _err(call(bridge_no_user)) == "No user database connected"
