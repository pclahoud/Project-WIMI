"""Tests for breadcrumb path resolution in the polyhierarchy migration.

Exercises §5.1 of ``docs/planning/POLYHIERARCHY_MIGRATION.md``:
``EdgesMixin.get_paths_to_root`` must return every distinct root-to-leaf
path through the DAG with the primary path first;
``_build_subject_path`` must return ONLY the primary path (so
breadcrumbs don't multiply when a leaf has multiple parents).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

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
def test_user(master_db):
    return master_db.create_user(
        username="bc_user",
        display_name="Breadcrumb User",
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


def _make_node(user_db, name: str) -> int:
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, sort_order, status) "
        "VALUES (?, ?, ?, NULL, 0, 'active')",
        ("USMLE", name, "Topic"),
    )
    user_db.conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------- tests


def test_get_paths_to_root_primary_first(user_db):
    """D has parents B (primary) and C; both have parent A.

    ``get_paths_to_root(D)`` must return both paths
    ``[A, B, D]`` and ``[A, C, D]`` with the primary path first.
    """
    a = _make_node(user_db, "A")
    b = _make_node(user_db, "B")
    c = _make_node(user_db, "C")
    d = _make_node(user_db, "D")

    user_db.add_edge(a, b, is_primary=True)
    user_db.add_edge(a, c, is_primary=True)
    user_db.add_edge(b, d, is_primary=True)   # primary parent of D
    user_db.add_edge(c, d, is_primary=False)  # secondary parent

    paths = user_db.get_paths_to_root(d)
    assert len(paths) == 2
    # Primary path is first.
    assert paths[0] == [a, b, d]
    # The non-primary path is also present.
    assert [a, c, d] in paths


def test_build_subject_path_uses_primary_only(user_db):
    """``_build_subject_path(D)`` returns the primary path (A → B → D),
    NOT the union of both. Per §7.2 of the plan: breadcrumbs show one
    canonical inline trail; alternate paths are surfaced via
    ``get_paths_to_root``.
    """
    a = _make_node(user_db, "A")
    b = _make_node(user_db, "B")
    c = _make_node(user_db, "C")
    d = _make_node(user_db, "D")

    user_db.add_edge(a, b, is_primary=True)
    user_db.add_edge(a, c, is_primary=True)
    user_db.add_edge(b, d, is_primary=True)
    user_db.add_edge(c, d, is_primary=False)

    path = user_db._build_subject_path(d)
    assert path == "A > B > D"
    # Crucially, C is NOT in the breadcrumb (it's a non-primary parent).
    assert "C" not in path


def test_get_paths_to_root_handles_diamond(user_db):
    """A has children B, C; both have child D. ``get_paths_to_root(D)``
    returns 2 distinct paths even though A is reached via 2 routes.
    """
    a = _make_node(user_db, "A")
    b = _make_node(user_db, "B")
    c = _make_node(user_db, "C")
    d = _make_node(user_db, "D")

    user_db.add_edge(a, b, is_primary=True)
    user_db.add_edge(a, c, is_primary=False)
    user_db.add_edge(b, d, is_primary=True)   # primary
    user_db.add_edge(c, d, is_primary=False)

    paths = user_db.get_paths_to_root(d)
    assert len(paths) == 2

    # Both paths share root A but diverge through B and C.
    sets = [tuple(p) for p in paths]
    assert (a, b, d) in sets
    assert (a, c, d) in sets

    # Primary leads.
    assert paths[0] == [a, b, d]
