"""``getEntriesPaginated`` and ``getTagsForFilter`` carry the #898 filters.

Plain-method bridge tests, no QApplication. ``data`` is read with ``.get``
because ``serialize_response`` omits it rather than sending null.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from app.bridge import DatabaseBridge
from database.user_db import UserDatabase


@pytest.fixture
def setup(tmp_path):
    db = UserDatabase(tmp_path / "browse_bridge.db", user_id=1, username="b")
    exam = db.create_exam_context(
        exam_name="BB Exam", exam_description="#898",
        hierarchy_levels=["System", "Topic"])
    root = db.create_subject_node(
        exam_context=exam.exam_name, name="BB Root", level_type="System")
    other = db.create_subject_node(
        exam_context=exam.exam_name, name="BB Other", level_type="System")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=9, total_incorrect=9,
        session_name="BB", date_encountered=date.today())
    group = db.create_tag_group(exam.exam_name, "BB Kinds")
    a = db.create_hierarchical_tag(exam.exam_name, "BB A", group.id).id
    b = db.create_hierarchical_tag(exam.exam_name, "BB B", group.id).id
    ids = {}
    for key, d, t, tags, subject in [
            ("hard_fast", 5, 20, [a, b], root),
            ("hard_slow", 4, 200, [a], root),
            ("easy", 1, 20, [b], other),
            ("bare", None, None, [], other)]:
        ids[key] = db.create_question_entry(
            review_session_id=session.id, user_answer="A", correct_answer="B",
            perceived_difficulty=d, time_spent_seconds=t, reflection="r",
            explanation="e", primary_subject_ids=[subject.id],
            tag_ids=tags).id
    db.remove_tag_from_exam(exam.exam_name, b)
    yield {"bridge": DatabaseBridge(user_db=db), "exam": exam.id,
           "root": root.id, "a": a, "b": b, "ids": ids}
    db.close()


def entries(s, **params):
    response = json.loads(s["bridge"].getEntriesPaginated(json.dumps(
        {"exam_context_id": s["exam"], "per_page": 50, **params})))
    assert response["success"] is True, response.get("error")
    data = response.get("data") or {}
    return {e["id"] for e in data["entries"]}, data["total"]


@pytest.mark.parametrize("params,expected", [
    ({"difficulty_levels": [4, 5]}, {"hard_fast", "hard_slow"}),
    ({"time_min_seconds": 100}, {"hard_slow"}),
    ({"time_max_seconds": 100.5}, {"hard_fast", "easy"}),
    ({"missing_any": ["difficulty", "time"]}, {"bare"}),
    ({"tag_ids": ["A", "B"], "tag_mode": "all"}, {"hard_fast"}),
    ({"tag_ids": ["A", "B"]}, {"hard_fast", "hard_slow", "easy"}),
    ({"untagged": True}, {"bare"}),
    ({"counted_subject_id": "root"}, {"hard_fast", "hard_slow"}),
    ({}, {"hard_fast", "hard_slow", "easy", "bare"}),
], ids=["difficulty", "time_min", "time_max", "missing", "all", "any",
        "untagged", "counted", "control-none"])
def test_each_key_is_passed_through(setup, params, expected):
    resolved = dict(params)
    if "tag_ids" in resolved:
        resolved["tag_ids"] = [setup[k.lower()] for k in resolved["tag_ids"]]
    if resolved.get("counted_subject_id") == "root":
        resolved["counted_subject_id"] = setup["root"]
    found, total = entries(setup, **resolved)
    assert found == {setup["ids"][k] for k in expected}
    assert total == len(expected)


def test_a_bad_filter_is_a_failure_with_a_sentence(setup):
    response = json.loads(setup["bridge"].getEntriesPaginated(json.dumps(
        {"exam_context_id": setup["exam"], "untagged": True,
         "tag_ids": [setup["a"]]})))
    assert response["success"] is False
    assert "No error type" in response["error"]


def test_tags_for_filter_offers_a_removed_type_still_carried(setup):
    response = json.loads(setup["bridge"].getTagsForFilter(setup["exam"]))
    assert response["success"] is True
    nodes = response.get("data") or []
    listed = [c["id"] for n in nodes if not n.get("not_listed_group")
              for c in n["children"]]
    assert listed == [setup["a"]]
    extra = [n for n in nodes if n.get("not_listed_group")]
    assert [c["id"] for c in extra[0]["children"]] == [setup["b"]]
    assert extra[0]["children"][0]["listed_on_exam"] is False


def test_tags_for_filter_with_no_database(setup):
    bridge = DatabaseBridge(user_db=None)
    assert json.loads(bridge.getTagsForFilter(1))["success"] is False
