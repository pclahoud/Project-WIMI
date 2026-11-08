"""``getDifficultyTimeQuadrants`` (#898 Wave 0): the bridge contract.

Plain-method bridge tests, no QApplication, as tests/app/test_bridge_*.py do.
``data`` is read with ``.get`` because ``serialize_response`` omits the key
rather than sending null.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from app.bridge import DatabaseBridge
from database.user_db import UserDatabase

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def setup(tmp_path):
    db = UserDatabase(tmp_path / "dt_bridge.db", user_id=1, username="dt")
    exam = db.create_exam_context(
        exam_name="DT Bridge", exam_description="#898",
        hierarchy_levels=["System", "Topic"])
    subject = db.create_subject_node(
        exam_context=exam.exam_name, name="DT Topic", level_type="System")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=20,
        session_name="DT", date_encountered=date.today())
    tag = db.create_tag(exam.exam_name, "DT Rushed").id
    for i in range(12):
        db.create_question_entry(
            review_session_id=session.id, user_answer="A", correct_answer="B",
            perceived_difficulty=(4 if i % 2 else 2),
            time_spent_seconds=30 + i, reflection="r", explanation="e",
            primary_subject_ids=[subject.id],
            tag_ids=[tag] if i < 3 else [])
    yield DatabaseBridge(user_db=db), exam.id, subject.id, tag
    db.close()


def call(bridge, **params):
    return json.loads(bridge.getDifficultyTimeQuadrants(json.dumps(params)))


def test_the_slot_returns_the_payload(setup):
    bridge, exam_id, _, _ = setup
    response = call(bridge, exam_context_id=exam_id)
    assert response["success"] is True
    data = response.get("data") or {}
    assert data.get("total") == 12
    assert data["median"]["available"] is True


def test_the_slot_passes_the_subject_and_the_selection(setup):
    bridge, exam_id, subject_id, tag = setup
    data = call(bridge, exam_context_id=exam_id, subject_id=subject_id,
                tag_ids=[tag], match="all").get("data") or {}
    assert data["scope"]["subject_id"] == subject_id
    assert data["selection"] == {"tag_ids": [tag], "untagged": False,
                                 "match": "all"}
    assert sum(1 for e in data["entries"] if e["matches"]) == 3


def test_untagged_reaches_the_method(setup):
    bridge, exam_id, _, _ = setup
    data = call(bridge, exam_context_id=exam_id, untagged=True).get("data") or {}
    assert data["untagged_count"] == 9
    assert sum(1 for e in data["entries"] if e["matches"]) == 9


@pytest.mark.parametrize("params", [
    {},
    {"exam_context_id": 99999},
    {"exam_context_id": "EXAM", "match": "some"},
    {"exam_context_id": "EXAM", "untagged": True, "tag_ids": ["TAG"]},
    {"exam_context_id": "EXAM", "tag_ids": ["x"]},
])
def test_a_refused_request_is_success_false_with_a_sentence(setup, params):
    bridge, exam_id, _, tag = setup
    params = {k: (exam_id if v == "EXAM" else
                  [tag] if v == ["TAG"] else v) for k, v in params.items()}
    response = call(bridge, **params)
    assert response["success"] is False
    assert response.get("data") is None
    assert response.get("error")


def test_a_refusal_is_the_methods_own_sentence(setup):
    bridge, exam_id, _, tag = setup
    response = call(bridge, exam_context_id=exam_id, untagged=True,
                    tag_ids=[tag])
    assert "No error type" in response["error"]


def test_no_database_is_success_false(setup):
    bridge = DatabaseBridge(user_db=None)
    response = json.loads(bridge.getDifficultyTimeQuadrants("{}"))
    assert response["success"] is False
    assert response.get("data") is None


def test_the_js_wrapper_calls_this_slot_with_snake_case_keys():
    module = (REPO / "src/web/js/api/analytics.js").read_text(encoding="utf-8")
    body = re.search(
        r"api\.getDifficultyTimeQuadrants\s*=\s*async function\(params\)\s*\{(.*?)\n    \};",
        module, re.S)
    assert body, "api.getDifficultyTimeQuadrants is not defined"
    text = body.group(1)
    assert "_callBridge('getDifficultyTimeQuadrants'" in text
    for key in ("exam_context_id", "subject_id", "primary_parent_id",
                "tag_ids", "untagged", "match"):
        assert f"{key}:" in text, f"the wrapper does not send {key}"
