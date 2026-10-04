"""The tree editor's feasibility walk must not re-derive the exam per parent (#177).

``validate_hierarchy_feasibility_recursive`` produces one report per
parent, and every **non-root** parent needs a q-range that comes from
``get_effective_question_counts`` — a walk of the *entire* tree through
the Hamilton allocator. Before #177 each parent called it for itself,
kept the rows naming that one parent and discarded the rest, so the same
table was rebuilt once per parent.

Measured on the owner's real profile (USMLE Step 2 CK, 10,453 active
nodes, 425 parents): **403 calls, 16.81 s of a 17.0 s total — 98.9%**,
and 945,460 calls to ``get_sibling_edges`` underneath them. After the
fix: 1 call, 0.12 s total. The page it blocks took ~19 s to open, and
users stopped using the subject tree because of it.

**The output was always correct — only the cost was wrong.** That is
exactly why the call count is asserted here and not just the reports: a
refactor that reinstates the per-parent walk would still return
identical reports and pass every other test in this directory. Nothing
else in the suite can tell the difference between 1 walk and 425.

Fixture style mirrors ``tests/database/test_edge_feasibility_report.py``.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import pytest

from database import MasterDatabase, UserDatabase


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def user_db(master_db):
    user = master_db.create_user(
        username="w177_user",
        display_name="W177 User",
        user_types=["student"],
    )
    db = UserDatabase(
        db_path=master_db.ensure_user_database(user.id),
        user_id=user.id,
        username=user.username,
    )
    yield db
    db.close()


class _CallCounter:
    """Wrap a bound method and count invocations, passing everything through."""

    def __init__(self, target, name: str):
        self._real = getattr(target, name)
        self.calls = 0
        setattr(target, name, self)

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self._real(*args, **kwargs)


# ---------------------------------------------------------------- the tree


EXAM = "W177 Exam"


@pytest.fixture
def deep_tree(user_db):
    """A tree with several NON-ROOT parents, which is what the bug needed.

    A root-only tree would pass even with the defect: the root branch of
    ``_resolve_parent_q_range`` reads ``subject_nodes`` directly and
    never reaches ``get_effective_question_counts``. Three intermediate
    parents are the smallest shape that exercises it more than once.

        Root System (100%)
          Topic A ── two leaves      <- non-root parent
          Topic B ── two leaves      <- non-root parent
          Topic C ── two leaves      <- non-root parent
    """
    ctx = user_db.create_exam_context(
        exam_name=EXAM, exam_description="#177 fixture"
    )
    user_db.update_exam_length(ctx.id, kind="fixed", min=100, max=100, typical=100)

    root = user_db.create_subject_node_with_weight(
        exam_context=EXAM, name="Root", level_type="System", parent_id=None,
        exam_weight_low=100.0, exam_weight_high=100.0, weight_source="user_defined",
    )

    parents = []
    for label, low, high in (("A", 30.0, 30.0), ("B", 30.0, 30.0), ("C", 40.0, 40.0)):
        mid = user_db.create_subject_node_with_weight(
            exam_context=EXAM, name=f"Topic {label}", level_type="Topic",
            parent_id=root.id, exam_weight_low=low, exam_weight_high=high,
            relative_weight=low, weight_source="user_defined",
        )
        for leaf in ("1", "2"):
            user_db.create_subject_node_with_weight(
                exam_context=EXAM, name=f"{label}{leaf}", level_type="Subtopic",
                parent_id=mid.id, exam_weight_low=low / 2, exam_weight_high=low / 2,
                relative_weight=50.0, weight_source="user_defined",
            )
        parents.append(mid.id)

    return {"exam_context_id": ctx.id, "root_id": root.id, "parent_ids": parents}


# ---------------------------------------------------------------- the tests


def test_the_whole_tree_is_walked_once_not_once_per_parent(user_db, deep_tree):
    """The guard. Identical reports would hide a reinstated N+1; this cannot."""
    counter = _CallCounter(user_db, "get_effective_question_counts")

    reports = user_db.validate_hierarchy_feasibility_recursive(
        deep_tree["exam_context_id"]
    )

    # Four parents: the root plus three intermediates.
    assert len(reports) == 4, reports
    assert counter.calls == 1, (
        f"get_effective_question_counts ran {counter.calls} times for "
        f"{len(reports)} parents. It walks the entire tree through the "
        f"Hamilton allocator and does not depend on which parent is "
        f"asking, so it must run exactly once per walk (#177)."
    )


def test_more_parents_does_not_mean_more_walks(user_db, deep_tree):
    """The count is independent of N -- that is the whole claim."""
    for label in ("D", "E", "F", "G"):
        mid = user_db.create_subject_node_with_weight(
            exam_context=EXAM, name=f"Topic {label}", level_type="Topic",
            parent_id=deep_tree["root_id"], exam_weight_low=5.0,
            exam_weight_high=5.0, relative_weight=5.0, weight_source="user_defined",
        )
        user_db.create_subject_node_with_weight(
            exam_context=EXAM, name=f"{label}1", level_type="Subtopic",
            parent_id=mid.id, exam_weight_low=5.0, exam_weight_high=5.0,
            relative_weight=100.0, weight_source="user_defined",
        )

    counter = _CallCounter(user_db, "get_effective_question_counts")
    reports = user_db.validate_hierarchy_feasibility_recursive(
        deep_tree["exam_context_id"]
    )

    assert len(reports) == 8
    assert counter.calls == 1, (
        f"{counter.calls} walks for 8 parents -- the cost is scaling with "
        f"the tree again (#177)."
    )


def test_the_shared_index_gives_the_same_answer_as_the_per_parent_walk(
    user_db, deep_tree
):
    """Speed is not the point if the dot moves.

    Verified at scale too: 425 parents of the owner's real profile,
    every field of every report, zero mismatches, with a non-trivial
    spread (399 ok / 25 under / 1 over).
    """
    exam_context_id = deep_tree["exam_context_id"]
    index = user_db._index_q_ranges(
        user_db.get_effective_question_counts(exam_context_id)
    )

    for pid in [deep_tree["root_id"]] + deep_tree["parent_ids"]:
        shared = user_db.validate_hierarchy_feasibility(pid, 100, index)
        per_parent = user_db.validate_hierarchy_feasibility(pid, 100)
        assert shared == per_parent, f"parent {pid} disagrees: {per_parent} vs {shared}"


def test_index_maximises_each_bound_independently(user_db):
    """A polyhierarchy node has one row per incoming edge.

    The per-parent scan took the largest q_low, q_high and q_typical
    *separately* rather than the triple from one winning row, and the
    index has to reproduce that -- not approximate it by picking the row
    with the biggest q_typical.
    """
    counts = [
        {"child_id": 7, "q_low": 1, "q_high": 9, "q_typical": 2},
        {"child_id": 7, "q_low": 4, "q_high": 5, "q_typical": 8},
        {"child_id": 8, "q_low": None, "q_high": None, "q_typical": None},
    ]

    index = UserDatabase._index_q_ranges(counts)

    assert index[7] == (4, 9, 8), "each bound is maximised on its own"
    assert index[8] == (None, None, None), "all-NULL stays NULL, not 0"


def test_a_missing_parent_reads_as_no_constraint(user_db, deep_tree):
    """Absent from the index means absent from the counts table.

    The scan it replaces found no matching row and returned
    ``(None, None, None)``, which the caller treats as 'ok' -- there is
    no constraint to violate. A KeyError here would turn a quiet
    non-answer into a failed report.
    """
    index = user_db._index_q_ranges([])
    assert user_db._resolve_parent_q_range(999_999, 100, index) == (None, None, None)


def test_a_broken_counts_table_degrades_instead_of_blanking_the_report(
    user_db, deep_tree, monkeypatch
):
    """Correct-but-slow beats fast-but-empty.

    If the one shared walk raises, every parent must still get a real
    report via its own walk. Returning stub 'ok's would silently remove
    every warning dot in the tree, which looks exactly like a clean
    hierarchy.
    """
    exam_context_id = deep_tree["exam_context_id"]
    expected = user_db.validate_hierarchy_feasibility_recursive(exam_context_id)

    calls = {"n": 0}
    real = user_db.get_effective_question_counts

    def fail_once_then_work(cid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("counts unavailable")
        return real(cid)

    monkeypatch.setattr(user_db, "get_effective_question_counts", fail_once_then_work)

    degraded = user_db.validate_hierarchy_feasibility_recursive(exam_context_id)

    assert degraded == expected, (
        "the fallback path must produce the same reports, just slowly"
    )
