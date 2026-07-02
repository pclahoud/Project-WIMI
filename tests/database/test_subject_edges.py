"""Tests for ``EdgesMixin`` — polyhierarchy edge CRUD on UserDatabase.

Exercises the methods defined in §5.1 of
``docs/planning/POLYHIERARCHY_MIGRATION.md``: ``add_edge``,
``remove_edge``, ``set_primary_parent``, ``get_parents``,
``get_paths_to_root``, and the internal cycle check.

Uses the ``temp_dir`` / per-user-DB fixture pattern from the rest of
``tests/database/`` rather than the migration-runner fixtures, because
these tests want a fully composed ``UserDatabase`` instance.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.exceptions import CircularReferenceError, SubjectNodeError, ValidationError


@pytest.fixture
def temp_dir():
    """Create temporary directory for test databases."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    """Create master database."""
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def test_user(master_db):
    """Create test user."""
    return master_db.create_user(
        username="edges_user",
        display_name="Edges User",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db, test_user):
    """Create user database (fully migrated by UserDatabase.__init__)."""
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username,
    )
    yield db
    db.close()


def _make_node(user_db, name: str, parent_id=None, sort_order: int = 0) -> int:
    """Insert a subject_node directly and return its id.

    Bypasses ``create_subject_node`` so tests can build arbitrary
    shapes without triggering the legacy parent-tree logic. Returns
    the new node's primary key.
    """
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, sort_order, status) "
        "VALUES (?, ?, ?, ?, ?, 'active')",
        ("USMLE", name, "Topic", parent_id, sort_order),
    )
    user_db.conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------- add_edge


def test_add_edge_creates_row(user_db):
    parent = _make_node(user_db, "ParentA")
    child = _make_node(user_db, "ChildA")

    edge = user_db.add_edge(parent, child, is_primary=True)

    assert edge.parent_id == parent
    assert edge.child_id == child
    assert edge.is_primary is True

    row = user_db.fetchone(
        "SELECT parent_id, child_id, is_primary FROM subject_edges WHERE id = ?",
        (edge.id,),
    )
    assert row is not None
    assert row['parent_id'] == parent
    assert row['child_id'] == child
    assert bool(row['is_primary']) is True


def test_add_edge_rejects_self_loop(user_db):
    node = _make_node(user_db, "Solo")
    with pytest.raises(ValidationError):
        user_db.add_edge(node, node)


def test_add_edge_rejects_cycle(user_db):
    """Direct cycle: A→B exists, then B→A is rejected."""
    a = _make_node(user_db, "A")
    b = _make_node(user_db, "B")
    user_db.add_edge(a, b, is_primary=True)

    with pytest.raises(CircularReferenceError):
        user_db.add_edge(b, a)


def test_add_edge_rejects_indirect_cycle(user_db):
    """Indirect cycle: A→B→C exists, then C→A is rejected."""
    a = _make_node(user_db, "A")
    b = _make_node(user_db, "B")
    c = _make_node(user_db, "C")
    user_db.add_edge(a, b, is_primary=True)
    user_db.add_edge(b, c, is_primary=True)

    with pytest.raises(CircularReferenceError):
        user_db.add_edge(c, a)


# ---------------------------------------------------------------- set_primary_parent


def test_set_primary_parent_clears_old_and_sets_new(user_db):
    """Child has 3 parent edges; switching primary leaves exactly one is_primary=TRUE."""
    p1 = _make_node(user_db, "P1")
    p2 = _make_node(user_db, "P2")
    p3 = _make_node(user_db, "P3")
    child = _make_node(user_db, "Child")

    user_db.add_edge(p1, child, is_primary=True)   # initial primary
    user_db.add_edge(p2, child, is_primary=False)
    user_db.add_edge(p3, child, is_primary=False)

    # Switch primary to p2.
    new_primary_edge = user_db.set_primary_parent(child, p2)
    assert new_primary_edge.parent_id == p2
    assert new_primary_edge.is_primary is True

    # Exactly one is_primary edge for this child, and it's the (p2, child) one.
    primaries = user_db.fetchall(
        "SELECT parent_id FROM subject_edges "
        "WHERE child_id = ? AND is_primary = TRUE",
        (child,),
    )
    assert len(primaries) == 1
    assert primaries[0]['parent_id'] == p2


def test_set_primary_parent_raises_when_no_edge_exists(user_db):
    p1 = _make_node(user_db, "P1")
    p2 = _make_node(user_db, "P2")
    child = _make_node(user_db, "Child")
    user_db.add_edge(p1, child, is_primary=True)

    with pytest.raises(SubjectNodeError):
        user_db.set_primary_parent(child, p2)


# ---------------------------------------------------------------- remove_edge


def test_remove_edge(user_db):
    p1 = _make_node(user_db, "P1")
    p2 = _make_node(user_db, "P2")
    child = _make_node(user_db, "Child")

    edge1 = user_db.add_edge(p1, child, is_primary=True)
    edge2 = user_db.add_edge(p2, child, is_primary=False)

    user_db.remove_edge(edge1.id)

    remaining = user_db.fetchall(
        "SELECT id FROM subject_edges WHERE child_id = ?", (child,)
    )
    remaining_ids = {row['id'] for row in remaining}
    assert remaining_ids == {edge2.id}


# ---------------------------------------------------------------- get_parents


def test_get_parents_returns_primary_first(user_db):
    """Primary edge should be first in the result list, regardless of insertion order."""
    p1 = _make_node(user_db, "P1")
    p2 = _make_node(user_db, "P2")
    p3 = _make_node(user_db, "P3")
    child = _make_node(user_db, "Child")

    # Insert non-primary edges first, then a primary edge.
    user_db.add_edge(p1, child, is_primary=False)
    user_db.add_edge(p2, child, is_primary=False)
    user_db.add_edge(p3, child, is_primary=True)

    parents = user_db.get_parents(child)
    assert len(parents) == 3
    assert parents[0].is_primary is True
    assert parents[0].parent_id == p3
    assert parents[0].parent_name == "P3"
    # Subsequent entries are non-primary.
    assert parents[1].is_primary is False
    assert parents[2].is_primary is False
    # All three parents represented.
    assert {p.parent_id for p in parents} == {p1, p2, p3}


# ---------------------------------------------------------------- get_paths_to_root


def test_get_paths_to_root_returns_all_paths_primary_first(user_db):
    """Two distinct root-to-child paths through a small DAG; primary path leads."""
    # Build:
    #         R1        R2
    #          \        /
    #           M1    M2
    #            \   /
    #             C
    # Primary path: R1 -> M1 -> C
    r1 = _make_node(user_db, "R1")
    r2 = _make_node(user_db, "R2")
    m1 = _make_node(user_db, "M1")
    m2 = _make_node(user_db, "M2")
    c = _make_node(user_db, "C")

    user_db.add_edge(r1, m1, is_primary=True)
    user_db.add_edge(r2, m2, is_primary=True)
    user_db.add_edge(m1, c, is_primary=True)   # primary parent of C
    user_db.add_edge(m2, c, is_primary=False)  # secondary parent

    paths = user_db.get_paths_to_root(c)
    assert len(paths) == 2

    # Primary path is first.
    assert paths[0] == [r1, m1, c]
    # The other path is also present.
    assert [r2, m2, c] in paths
