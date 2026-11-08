"""A weight that is not a number imports as 0%, as the preview says (#842).

A file with ``{"low": 5, "high": "11%"}`` used to be previewed with the
warning *"... is not a number (5); imported as 0%"* and then fail at apply
time on a bare ``float('11%')``, rolling back every valid subject in the file.
#64 settles which side is right: nothing about a weight aborts an import, and
everything checkable is a warning. So the bad bound is normalised to 0% in
the one record the preview and the apply both read (#67's guarantee), and the
warning quotes the bound that is actually wrong.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(username="w842", display_name="W842",
                                  user_types=["student"])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username=user.username)
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    user_db.create_exam_context(exam_name="Weight 842", exam_description="")
    return user_db.get_exam_context_by_name("Weight 842")


def _weights(db, exam_name):
    return {r['name']: (r['exam_weight_low'], r['exam_weight_high']) for r in db.fetchall(
        "SELECT name, exam_weight_low, exam_weight_high FROM subject_nodes "
        "WHERE exam_context = ? AND status = 'active'", (exam_name,))}


NODES = [
    {"name": "Typo", "level_type": "System", "weight": {"low": 5, "high": "11%"}},
    {"name": "Fine", "level_type": "System", "weight": 10},
]


@pytest.mark.database
def test_the_issues_reproduction_imports_the_bad_bound_as_zero(user_db, exam):
    plan = user_db.plan_subject_import(exam.id, NODES)
    assert plan['errors'] == []

    user_db.apply_subject_import(exam.id, NODES)

    weights = _weights(user_db, exam.exam_name)
    assert weights["Fine"] == (10, 10), "a valid subject must not be rolled back with the bad one"
    assert weights["Typo"] == (0, 0), "the preview promised 0%"


@pytest.mark.database
def test_the_warning_quotes_the_bound_that_is_wrong(user_db, exam):
    warnings = " ".join(user_db.plan_subject_import(exam.id, NODES)['warnings'])
    assert "'11%'" in warnings, warnings
    assert "(5)" not in warnings, f"quoted the good low bound: {warnings}"
    assert "imported as 0%" in warnings


@pytest.mark.database
@pytest.mark.parametrize("weight, quoted", [
    ({"low": "five", "high": 8}, "'five'"),
    ({"value": "7%"}, "'7%'"),
    ("12%", "'12%'"),
    ({"low": True, "high": 3}, "True"),
])
def test_every_shape_of_bad_weight_imports_as_zero(user_db, exam, weight, quoted):
    nodes = [{"name": "Bad", "level_type": "System", "weight": weight},
             {"name": "Fine", "level_type": "System", "weight": 4}]
    warnings = " ".join(user_db.plan_subject_import(exam.id, nodes)['warnings'])
    assert quoted in warnings, warnings
    user_db.apply_subject_import(exam.id, nodes)
    weights = _weights(user_db, exam.exam_name)
    assert weights == {"Bad": (0, 0), "Fine": (4, 4)}


@pytest.mark.database
def test_a_re_import_with_a_bad_bound_previews_and_applies_the_same_change(user_db, exam):
    """An existing subject at 9% that a file now gives a bad weight: the plan
    reports 9% to 0%, and the apply writes exactly that."""
    user_db.apply_subject_import(exam.id, [{"name": "Typo", "level_type": "System", "weight": 9}])
    plan = user_db.plan_subject_import(exam.id, NODES[:1])
    [typo] = plan['updated']
    assert typo['changes'] == {"exam_weight_low": [9.0, 0.0], "exam_weight_high": [9.0, 0.0]}
    user_db.apply_subject_import(exam.id, NODES[:1])
    assert _weights(user_db, exam.exam_name)["Typo"] == (0, 0)


@pytest.mark.database
def test_a_whole_exam_file_imports_a_bad_bound_as_zero(user_db, exam):
    """The whole-exam path builds its records with the same walker (#241)."""
    dims = [{"name": "System", "root_nodes": NODES}]
    plan = user_db.plan_whole_exam_import(exam.id, dims)
    assert plan['errors'] == []
    assert any("'11%'" in w for w in plan['warnings']), plan['warnings']
    user_db.apply_whole_exam_import(exam.id, dims)
    weights = _weights(user_db, exam.exam_name)
    assert weights == {"Typo": (0, 0), "Fine": (10, 10)}
