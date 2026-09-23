"""Bridge tests for the subject delete slots — issue #15.

Covers ``HierarchyBridgeMixin.getSubjectDeletePreview`` and the two
registered arities of ``deleteSubjectNode``.

The overload matters on its own: ``src/web/js/import_export.js`` calls the
single-argument form during a replace-mode import, so changing the
existing signature rather than adding to it would have broken import
without touching import's own code. ``deleteSubjectNode(int)`` therefore
has to keep meaning exactly what it meant — delete the exclusive children
too — while ``deleteSubjectNode(int, bool)`` carries decision 2's choice.
"""
import json
import tempfile
from datetime import date
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


# ==================== Helpers ====================

def _node(db: UserDatabase, name: str) -> int:
    cursor = db.execute(
        "INSERT INTO subject_nodes "
        "(exam_context, name, level_type, parent_id, sort_order, status) "
        "VALUES ('USMLE', ?, 'Topic', NULL, 0, 'active')",
        (name,),
    )
    db.conn.commit()
    return cursor.lastrowid


def _shape(db: UserDatabase):
    """Pdel holds Shared (with Qkeep) and Exclusive (alone)."""
    pdel, qkeep = _node(db, "Pdel"), _node(db, "Qkeep")
    shared, exclusive = _node(db, "Shared"), _node(db, "Exclusive")
    db.add_edge(pdel, shared, is_primary=True)
    db.add_edge(qkeep, shared, is_primary=False)
    db.add_edge(pdel, exclusive, is_primary=True)
    return pdel, qkeep, shared, exclusive


def _status(db: UserDatabase, node_id: int) -> str:
    return db.fetchone(
        "SELECT status FROM subject_nodes WHERE id = ?", (node_id,)
    )['status']


# ==================== getSubjectDeletePreview ====================

def test_preview_returns_classified_buckets(bridge, user_db):
    pdel, _qkeep, shared, exclusive = _shape(user_db)

    response = json.loads(bridge.getSubjectDeletePreview(pdel))

    assert response['success'] is True
    data = response['data']
    assert data['node_name'] == 'Pdel'
    assert [c['id'] for c in data['exclusive_direct_children']] == [exclusive]
    assert [c['id'] for c in data['shared_direct_children']] == [shared]
    assert set(data['modes']) == {'delete', 'promote'}


def test_preview_mutates_nothing(bridge, user_db):
    pdel, _qkeep, _shared, exclusive = _shape(user_db)

    json.loads(bridge.getSubjectDeletePreview(pdel))

    assert _status(user_db, pdel) == 'active'
    assert _status(user_db, exclusive) == 'active'


def test_preview_rejects_a_missing_node(bridge):
    response = json.loads(bridge.getSubjectDeletePreview(424242))
    assert response['success'] is False
    assert 'not found' in response['error']


def test_preview_guards_on_no_user_db(master_db):
    master_db.bootstrap_first_user(username="admin2", display_name="A")
    guarded = DatabaseBridge(master_db=master_db, user_db=None)
    response = json.loads(guarded.getSubjectDeletePreview(1))
    assert response['success'] is False
    assert response['error'] == 'No user database connected'


# ==================== deleteSubjectNode — both arities ====================

def test_single_argument_call_still_deletes_exclusive_children(bridge, user_db):
    """The import_export.js contract. One argument means the original
    behaviour: take the exclusive subtree with it."""
    pdel, _qkeep, shared, exclusive = _shape(user_db)

    response = json.loads(bridge.deleteSubjectNode(pdel))

    assert response['success'] is True
    assert _status(user_db, pdel) == 'archived'
    assert _status(user_db, exclusive) == 'archived'
    assert _status(user_db, shared) == 'active'


def test_two_argument_call_with_false_matches_the_one_argument_call(bridge, user_db):
    pdel, _qkeep, _shared, exclusive = _shape(user_db)

    assert json.loads(bridge.deleteSubjectNode(pdel, False))['success'] is True

    assert _status(user_db, exclusive) == 'archived'


def test_two_argument_call_with_true_promotes(bridge, user_db):
    pdel, _qkeep, _shared, exclusive = _shape(user_db)

    response = json.loads(bridge.deleteSubjectNode(pdel, True))

    assert response['success'] is True
    assert _status(user_db, exclusive) == 'active'
    assert [n['id'] for n in response['data']['promoted']] == [exclusive]
    assert exclusive in {n.id for n in user_db.get_subject_hierarchy("USMLE")}


def test_both_signatures_are_registered_on_the_meta_object(bridge):
    """QWebChannel publishes a slot per registered signature and resolves
    by argument count on the JS side. If only one survived, the tree
    editor's two-argument call would silently do nothing."""
    meta = bridge.metaObject()
    signatures = {
        bytes(meta.method(i).methodSignature()).decode()
        for i in range(meta.methodCount())
    }
    assert 'deleteSubjectNode(int)' in signatures
    assert 'deleteSubjectNode(int,bool)' in signatures


# ==================== response payload ====================

def test_response_carries_the_executed_plan(bridge, user_db):
    pdel, _qkeep, shared, exclusive = _shape(user_db)
    ec = user_db.execute(
        "INSERT INTO exam_contexts (user_id, exam_name, exam_description) "
        "VALUES (?, 'USMLE', 'T')", (user_db.user_id,)
    ).lastrowid
    rs = user_db.execute(
        "INSERT INTO review_sessions (user_id, session_name, date_encountered, "
        "exam_context_id, total_questions, total_incorrect) "
        "VALUES (?, 'S', ?, ?, 1, 1)",
        (user_db.user_id, date.today().isoformat(), ec),
    ).lastrowid
    entry = user_db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, user_answer, "
        "correct_answer) VALUES (?, 1, 'A', 'B')", (rs,)
    ).lastrowid
    user_db.execute(
        "INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, "
        "mapping_type, primary_parent_id) VALUES (?, ?, 'primary', ?)",
        (entry, shared, pdel),
    )
    user_db.conn.commit()

    data = json.loads(bridge.deleteSubjectNode(pdel))['data']

    assert data['id'] == pdel
    assert data['deleted'] is True
    assert data['batch_id']
    assert {n['id'] for n in data['archived']} == {pdel, exclusive}
    assert [d['child_id'] for d in data['detached']] == [shared]
    assert data['entries_unscoped'] == 1


def test_delete_rejects_a_missing_node(bridge):
    response = json.loads(bridge.deleteSubjectNode(424242))
    assert response['success'] is False
    assert 'not found' in response['error']


def test_delete_guards_on_no_user_db(master_db):
    master_db.bootstrap_first_user(username="admin3", display_name="A")
    guarded = DatabaseBridge(master_db=master_db, user_db=None)
    response = json.loads(guarded.deleteSubjectNode(1, True))
    assert response['success'] is False
    assert response['error'] == 'No user database connected'
