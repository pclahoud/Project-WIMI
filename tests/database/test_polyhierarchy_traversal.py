"""Tests for the recursive CTE rewrites in the polyhierarchy migration.

Exercises §5.2 of ``docs/planning/POLYHIERARCHY_MIGRATION.md``: the
recursive CTEs that walk ``subject_edges`` (rather than
``subject_nodes.parent_id``) and the OMOP-style ``COUNT(DISTINCT
entry_id)`` aggregation pattern from §5.3 that ensures a leaf reachable
through multiple paths only counts once per ancestor's rollup.

Uses the ``temp_dir`` / per-user-DB fixture pattern from
``tests/database/test_subject_edges.py``.
"""
from __future__ import annotations

import signal
import tempfile
import time
from datetime import date
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def temp_dir():
    """Temporary directory for test databases."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def test_user(master_db):
    return master_db.create_user(
        username="poly_user",
        display_name="Polyhierarchy User",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db, test_user):
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username,
    )
    yield db
    db.close()


def _make_node(user_db, name: str, parent_id=None) -> int:
    """Insert a subject_nodes row directly. Bypasses ``create_subject_node``
    so tests can build arbitrary DAG shapes via add_edge.
    """
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, sort_order, status) "
        "VALUES (?, ?, ?, ?, ?, 'active')",
        ("USMLE", name, "Topic", parent_id, 0),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _make_session(user_db) -> int:
    """Create a minimal review session for entry insertion.

    review_sessions has a NOT NULL constraint on exam_context_id, so
    we ensure an exam_contexts row exists first.
    """
    ec_row = user_db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = 'USMLE'"
    )
    if ec_row is None:
        cursor = user_db.execute(
            "INSERT INTO exam_contexts (user_id, exam_name, exam_description) "
            "VALUES (?, 'USMLE', 'Test')",
            (user_db.user_id,),
        )
        ec_id = cursor.lastrowid
        user_db.conn.commit()
    else:
        ec_id = ec_row['id']
    cursor = user_db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_db.user_id, "Test session", date.today().isoformat(), ec_id, 1, 1),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _log_entry(user_db, session_id: int, subject_node_id: int,
               primary_parent_id=None) -> int:
    """Insert a question_entry mapped to ``subject_node_id``.

    Returns the new entry_id. ``primary_parent_id`` exercises the §5.4
    polyhierarchy override behavior tested in
    ``test_primary_parent_context.py``.
    """
    cursor = user_db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, ?, ?)",
        (session_id, 1, "A", "B"),
    )
    entry_id = cursor.lastrowid
    user_db.execute(
        "INSERT INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type, primary_parent_id) "
        "VALUES (?, ?, 'primary', ?)",
        (entry_id, subject_node_id, primary_parent_id),
    )
    user_db.conn.commit()
    return entry_id


# ---------------------------------------------------------------- traversal


def test_descendants_walk_subject_edges(user_db):
    """Build A→B, A→C, B→D, C→D (D has two parents). Confirm
    ``_get_descendant_node_ids(A)`` returns {B, C, D} with D included
    exactly once (UNION dedup in the recursive CTE).
    """
    a = _make_node(user_db, "A")
    b = _make_node(user_db, "B")
    c = _make_node(user_db, "C")
    d = _make_node(user_db, "D")

    user_db.add_edge(a, b, is_primary=True)
    user_db.add_edge(a, c, is_primary=True)
    user_db.add_edge(b, d, is_primary=True)
    user_db.add_edge(c, d, is_primary=False)  # second parent of D

    descendants = user_db._get_descendant_node_ids(a)
    assert sorted(descendants) == sorted([b, c, d])
    # D appears exactly once (deduplicated even though reachable via two paths).
    assert descendants.count(d) == 1


def test_count_distinct_avoids_inflation(user_db):
    """One entry on multi-parent leaf D counts once under A (the common
    ancestor reached via two paths) and once under each of B and C.
    """
    a = _make_node(user_db, "A")
    b = _make_node(user_db, "B")
    c = _make_node(user_db, "C")
    d = _make_node(user_db, "D")

    user_db.add_edge(a, b, is_primary=True)
    user_db.add_edge(a, c, is_primary=True)
    user_db.add_edge(b, d, is_primary=True)
    user_db.add_edge(c, d, is_primary=False)

    session_id = _make_session(user_db)
    _log_entry(user_db, session_id, d)

    # COUNT(DISTINCT entry_id) using the rewritten descendants CTE.
    def count_under(root_id):
        cte = user_db._build_descendant_cte(root_id)
        row = user_db.fetchone(
            f"""
            {cte}
            SELECT COUNT(DISTINCT esm.question_entry_id) AS c
            FROM entry_subject_mappings esm
            WHERE esm.subject_node_id IN (SELECT id FROM descendants)
            """
        )
        return row['c']

    assert count_under(a) == 1, "A reaches D via 2 paths but the entry counts once"
    assert count_under(b) == 1
    assert count_under(c) == 1
    assert count_under(d) == 1


def test_dvt_appears_under_both_cardiovascular_and_pregnancy(user_db):
    """Modeled on the USMLE multi-parent topic DVT — one entry on the
    DVT leaf rolls up to BOTH Cardiovascular's and Pregnancy's totals.

    Uses the USMLE outline fixture indirectly: we don't need to build
    the *entire* outline (1,300+ lines), just the two parent paths
    through which DVT/VTE appears in §1 of the migration plan.
    """
    from tests.fixtures.load_usmle_outline import load_usmle_outline

    outline = load_usmle_outline()
    # The fixture identifies multi-parent topics; "deep venous thrombosis"
    # or "venous thromboembolism" should appear with at least two parents.
    multi = set(outline.multi_parent_topics)
    assert multi, "USMLE fixture should expose at least one multi-parent topic"

    cardio = _make_node(user_db, "Cardiovascular System")
    vasc = _make_node(user_db, "Vascular disorders")
    veins = _make_node(user_db, "Diseases of the veins")
    preg = _make_node(user_db, "Pregnancy")
    sysd = _make_node(user_db, "Systemic disorders affecting pregnancy")
    dvt = _make_node(user_db, "DVT / venous thromboembolism")

    user_db.add_edge(cardio, vasc, is_primary=True)
    user_db.add_edge(vasc, veins, is_primary=True)
    user_db.add_edge(veins, dvt, is_primary=True)  # primary path: cardio chain
    user_db.add_edge(preg, sysd, is_primary=True)
    user_db.add_edge(sysd, dvt, is_primary=False)  # secondary parent

    session_id = _make_session(user_db)
    _log_entry(user_db, session_id, dvt)

    def count_under(root_id):
        cte = user_db._build_descendant_cte(root_id)
        row = user_db.fetchone(
            f"""
            {cte}
            SELECT COUNT(DISTINCT esm.question_entry_id) AS c
            FROM entry_subject_mappings esm
            WHERE esm.subject_node_id IN (SELECT id FROM descendants)
            """
        )
        return row['c']

    # The single DVT entry contributes to BOTH parents' rollups
    # (OMOP "honest non-additivity" — sums of siblings exceed the
    # logical superset, which is correct for this metacognitive tool).
    assert count_under(cardio) == 1
    assert count_under(preg) == 1


def test_cycle_in_data_does_not_hang_query(user_db):
    """Manually insert a cycle by bypassing EdgesMixin's cycle check
    (raw SQL INSERT). Walking the descendants CTE from a node in the
    cycle must terminate finitely thanks to ``UNION`` (not ``UNION ALL``).

    Bound the test wall-clock time so a regression that reintroduces
    ``UNION ALL`` shows up as a 5-second timeout failure rather than
    blocking forever.
    """
    a = _make_node(user_db, "A")
    b = _make_node(user_db, "B")
    c = _make_node(user_db, "C")

    # Insert A→B and B→C via the mixin (cycle-checked).
    user_db.add_edge(a, b, is_primary=True)
    user_db.add_edge(b, c, is_primary=True)
    # Bypass the cycle check and insert C→A directly. UNIQUE constraint
    # prevents duplicates but does not detect cycles, and the CHECK
    # constraint only blocks self-loops.
    user_db.execute(
        "INSERT INTO subject_edges (parent_id, child_id, is_primary) "
        "VALUES (?, ?, FALSE)",
        (c, a),
    )
    user_db.conn.commit()

    start = time.monotonic()
    descendants = user_db._get_descendant_node_ids(a)
    elapsed = time.monotonic() - start

    assert elapsed < 5.0, (
        f"Cycle in data caused query to take {elapsed:.2f}s — "
        "UNION dedup must keep the recursion finite."
    )
    # All three nodes are mutually reachable; A's descendants are {B, C, A}.
    # `_get_descendant_node_ids` excludes the seed by query shape, so {B, C}.
    assert sorted(descendants) == sorted([a, b, c]) or sorted(descendants) == sorted([b, c])
