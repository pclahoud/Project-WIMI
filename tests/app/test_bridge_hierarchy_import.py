"""Bridge tests for subject-tree import — issue #61.

The published import spec documents the file's top-level shape as
``{ exam_context, subjects[] }``, but ``importSubjectHierarchy`` read
only ``data['root_nodes']``. A file written exactly to spec therefore
imported zero subjects and reported success — a silent no-op. The slot
is the one place both UI entry points converge, so it is where the two
spellings are reconciled; ``root_nodes`` stays canonical because that is
what export writes.

Issue #62: ``import_node`` passed ``node_data.get('sort_order', 1)``.
``sort_order`` is not a documented field, so no hand-authored file
supplies it, so every node landed on ``sort_order = 1`` and the tree
came back alphabetically instead of in source order.
``get_subject_hierarchy`` orders roots by ``sn.sort_order, sn.name`` and
children by ``se.display_order, sn.sort_order, sn.name`` — the *edge's*
``display_order`` first — so the tests below pin both columns, not just
the one on ``subject_nodes``.
"""
import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except Exception:
        pass


@pytest.fixture
def temp_master_db_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def user_db(temp_db_path: Path) -> Generator[UserDatabase, None, None]:
    db = UserDatabase(db_path=temp_db_path, user_id=1, username="test_user")
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    master_db.bootstrap_first_user(username="test_admin", display_name="Test Admin")
    return DatabaseBridge(master_db=master_db, user_db=user_db)


@pytest.fixture
def exam(user_db: UserDatabase):
    """A bare exam context with no subjects."""
    created = user_db.create_exam_context(
        exam_name="Import Format Exam",
        exam_description="issues #61 / #62",
    )
    return user_db.get_exam_context_by_name(created.exam_name)


# ==================== Helpers ====================

# Deliberately not alphabetical: alphabetical order is Apple, Mango,
# Zebra, so "the file's order survived" and "the tree sorted by name"
# cannot both be true of the same output (issue #62).
_SIBLINGS = ["Zebra", "Apple", "Mango"]


def _payload(key: str) -> str:
    """An import file whose subject array hangs off ``key``."""
    return json.dumps({
        "exam_context": "Import Format Exam",
        key: [
            {
                "name": "Import Root",
                "children": [{"name": name} for name in _SIBLINGS],
            }
        ],
    })


def _run_import(bridge: DatabaseBridge, exam_id: int, key: str) -> dict:
    response = json.loads(bridge.importSubjectHierarchy(exam_id, _payload(key)))
    assert response["success"], response
    return response["data"]


def _names(nodes) -> list:
    return [n.name for n in nodes]


# ==================== Issue #61 — both keys import ====================

@pytest.mark.parametrize("key", ["root_nodes", "subjects"])
def test_import_accepts_either_top_level_key(bridge, user_db, exam, key):
    """``root_nodes`` (what export writes) and ``subjects`` (what the
    spec documents) must import identically.

    Before the fix, ``key='subjects'`` returned ``success=True`` with
    ``imported_count=0`` and wrote nothing at all — a silent no-op, which
    is worse than the tree editor's outright rejection because nothing
    tells the user their file was ignored.
    """
    data = _run_import(bridge, exam.id, key)

    assert data["imported_count"] == 1 + len(_SIBLINGS), (
        f"file keyed on {key!r} imported {data['imported_count']} nodes, "
        f"expected {1 + len(_SIBLINGS)}"
    )

    roots = user_db.get_subject_hierarchy(exam.exam_name)
    assert _names(roots) == ["Import Root"]
    assert sorted(_names(roots[0].children)) == sorted(_SIBLINGS)


def test_import_prefers_root_nodes_when_a_file_carries_both(bridge, user_db, exam):
    """``root_nodes`` stays canonical: export writes it, so a round-trip
    of WIMI's own export must never be reinterpreted."""
    payload = json.dumps({
        "root_nodes": [{"name": "From root_nodes"}],
        "subjects": [{"name": "From subjects"}],
    })
    response = json.loads(bridge.importSubjectHierarchy(exam.id, payload))
    assert response["success"], response

    roots = user_db.get_subject_hierarchy(exam.exam_name)
    assert _names(roots) == ["From root_nodes"]


def test_import_with_neither_key_imports_nothing(bridge, user_db, exam):
    """A file with neither key is still a no-op, not a crash."""
    response = json.loads(bridge.importSubjectHierarchy(
        exam.id, json.dumps({"exam_context": "Import Format Exam"})))
    assert response["success"], response
    assert response["data"]["imported_count"] == 0


# ==================== Issue #62 — source order survives ====================

def test_import_preserves_sibling_order(bridge, user_db, exam):
    """Children render in file order, not alphabetically.

    This is the assertion the old code failed: every node landed on
    ``sort_order = 1``, every edge on ``display_order = 1``, and
    ``get_subject_hierarchy``'s trailing ``sn.name`` tiebreak decided the
    order — Apple, Mango, Zebra.
    """
    _run_import(bridge, exam.id, "root_nodes")

    roots = user_db.get_subject_hierarchy(exam.exam_name)
    assert _names(roots[0].children) == _SIBLINGS, (
        "children came back in a different order than the import file "
        "listed them"
    )


def test_import_preserves_root_order(bridge, user_db, exam):
    """Roots have no incoming edge, so their order rides entirely on
    ``subject_nodes.sort_order`` — a different ORDER BY branch than the
    children above, and worth its own assertion."""
    payload = json.dumps({
        "root_nodes": [{"name": name} for name in _SIBLINGS],
    })
    assert json.loads(bridge.importSubjectHierarchy(exam.id, payload))["success"]

    assert _names(user_db.get_subject_hierarchy(exam.exam_name)) == _SIBLINGS


def test_import_sets_edge_display_order(bridge, user_db, exam):
    """The edge column, not just the node column.

    ``get_subject_hierarchy`` orders children by ``se.display_order``
    *first*, so a fix that only moved ``subject_nodes.sort_order`` would
    look right in the table and change nothing on screen. Pin the column
    that actually governs.
    """
    _run_import(bridge, exam.id, "root_nodes")

    rows = user_db.fetchall(
        """
        SELECT sn.name, se.display_order, sn.sort_order
        FROM subject_edges se
        JOIN subject_nodes sn ON sn.id = se.child_id
        WHERE sn.exam_context = ?
        ORDER BY se.display_order
        """,
        (exam.exam_name,),
    )
    assert [r["name"] for r in rows] == _SIBLINGS
    display_orders = [r["display_order"] for r in rows]
    assert len(set(display_orders)) == len(display_orders), (
        f"sibling edges tied on display_order: {display_orders}"
    )
    assert [r["sort_order"] for r in rows] == display_orders, (
        "subject_nodes.sort_order and subject_edges.display_order must "
        "agree — create_subject_node derives one from the other"
    )


def test_explicit_sort_order_overrides_array_position(bridge, user_db, exam):
    """A file that states ``sort_order`` still wins over its position."""
    payload = json.dumps({
        "root_nodes": [
            {
                "name": "Override Root",
                "children": [
                    {"name": "Listed first", "sort_order": 30},
                    {"name": "Listed second", "sort_order": 20},
                    {"name": "Listed third", "sort_order": 10},
                ],
            }
        ],
    })
    assert json.loads(bridge.importSubjectHierarchy(exam.id, payload))["success"]

    roots = user_db.get_subject_hierarchy(exam.exam_name)
    assert _names(roots[0].children) == [
        "Listed third", "Listed second", "Listed first",
    ]
