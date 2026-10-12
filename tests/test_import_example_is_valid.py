"""The shipped import example is a file the importer actually takes (#437).

``examples/imports/cardiology_example.json`` replaced a USMLE-derived example.
That example's aliases were plain strings and its tree sat under a key the
example's own loader did not read, so it failed the published schema 122 times
and nothing noticed. An example is documentation that can be run, so this
runs it: against the published schema, then through the same planner the tree
editor's Import uses.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from database.user_db import UserDatabase

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "imports" / "cardiology_example.json"
SCHEMA = ROOT / "docs" / "examples" / "subject_tree_import.schema.json"


def _count(nodes):
    return sum(1 + _count(n.get("children", [])) for n in nodes)


def _weights(nodes):
    return [n["name"] for n in nodes if "weight" in n] + [
        name for n in nodes for name in _weights(n.get("children", []))]


@pytest.fixture
def example():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_the_example_matches_the_published_schema(example):
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = list(jsonschema.validators.validator_for(schema)(schema)
                  .iter_errors(example))
    assert errors == [], [f"{list(e.path)}: {e.message}" for e in errors[:5]]


def test_the_example_carries_no_weights(example):
    """A weight belongs to the student's own exam's published outline. An
    example that invents one teaches the one thing an import file must not
    do, which is the first rule of the prompt in 03_outline_to_tree.md."""
    assert _weights(example["root_nodes"]) == []


def test_the_example_imports_cleanly_and_a_second_import_changes_nothing(
    example, tmp_path
):
    db = UserDatabase(db_path=tmp_path / "u.db", user_id=1, username="example")
    try:
        exam = db.create_exam_context(exam_name="Example", exam_description="")
        nodes = example["root_nodes"]
        expected = _count(nodes)

        plan = db.plan_subject_import(exam.id, nodes)
        assert plan["counts"]["added"] == expected, plan["counts"]
        assert plan.get("errors") in (None, []), plan.get("errors")
        assert plan.get("warnings") in (None, []), plan.get("warnings")

        db.apply_subject_import(exam.id, nodes)
        stored = db.conn.execute(
            "SELECT COUNT(*) FROM subject_nodes WHERE exam_context = ? "
            "AND status = 'active'", (exam.exam_name,)).fetchone()[0]
        assert stored == expected

        again = db.plan_subject_import(exam.id, nodes)["counts"]
        assert again["unchanged"] == expected and again["added"] == 0, again
    finally:
        db.close()
