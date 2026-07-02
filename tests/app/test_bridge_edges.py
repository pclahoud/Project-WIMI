"""Bridge tests for the polyhierarchy edge slots.

Covers ``EdgesBridgeMixin`` (``addParent``, ``removeParent``,
``setPrimaryParent``, ``getParents``, ``getPathsToRoot``) and the
``setPrimaryParentForEntry`` slot in ``EntryBridgeMixin``. See
``docs/planning/POLYHIERARCHY_MIGRATION.md`` §6 for the slot specs.
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
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except Exception:
        pass


@pytest.fixture
def temp_master_db_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for master database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def user_db(temp_db_path: Path) -> Generator[UserDatabase, None, None]:
    """Create a UserDatabase instance for testing."""
    db = UserDatabase(
        db_path=temp_db_path,
        user_id=1,
        username="test_user",
    )
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    """Create a MasterDatabase for testing."""
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    """Create a DatabaseBridge wired to test databases."""
    master_db.bootstrap_first_user(
        username="test_admin",
        display_name="Test Admin",
    )
    return DatabaseBridge(master_db=master_db, user_db=user_db)


# ---- Subject-tree builders -----------------------------------------------


def _make_node(db: UserDatabase, name: str, parent_id=None, level_type='System'):
    """Helper to create a subject node directly via the mixin API."""
    return db.create_subject_node(
        exam_context='Test Exam',
        name=name,
        level_type=level_type,
        parent_id=parent_id,
        exam_weight_low=0,
        exam_weight_high=0,
        sort_order=1,
    )


def _add_edge(db: UserDatabase, parent_id: int, child_id: int, is_primary: bool = False):
    """Helper to add an edge bypassing the bridge (for setup)."""
    return db.add_edge(parent_id, child_id, is_primary=is_primary)


# ---- Response helpers ----------------------------------------------------


def _parse(response: str) -> dict:
    return json.loads(response)


def _ok(response: str) -> dict:
    payload = _parse(response)
    assert payload['success'] is True, (
        f"Expected success, got error: {payload.get('error')}"
    )
    return payload.get('data')


def _err(response: str) -> str:
    payload = _parse(response)
    assert payload['success'] is False, "Expected error, got success"
    return payload.get('error')


# ==================== addParent ====================


class TestAddParent:
    def test_add_parent_succeeds(self, bridge: DatabaseBridge, user_db: UserDatabase):
        """addParent creates an edge and returns its metadata."""
        a = _make_node(user_db, 'Cardiovascular')
        b = _make_node(user_db, 'Hypertension')

        response = bridge.addParent(b.id, a.id, False)
        data = _ok(response)

        assert data['parent_id'] == a.id
        assert data['child_id'] == b.id
        assert data['is_primary'] is False
        assert 'edge_id' in data
        assert isinstance(data['display_order'], int)

        # Verify on the read side too.
        parents = _ok(bridge.getParents(b.id))
        assert len(parents) == 1
        assert parents[0]['parent_id'] == a.id

    def test_add_parent_with_primary_flag(self, bridge: DatabaseBridge, user_db: UserDatabase):
        """addParent with is_primary=True marks the new edge primary."""
        a = _make_node(user_db, 'Repro')
        b = _make_node(user_db, 'Pregnancy')

        data = _ok(bridge.addParent(b.id, a.id, True))
        assert data['is_primary'] is True

    def test_add_parent_rejects_cycle(self, bridge: DatabaseBridge, user_db: UserDatabase):
        """A cycle attempt returns success=False, error='cycle'."""
        a = _make_node(user_db, 'A')
        b = _make_node(user_db, 'B')
        # Existing edge: A -> B. Adding B -> A would close the cycle.
        _add_edge(user_db, a.id, b.id)

        error = _err(bridge.addParent(a.id, b.id, False))
        assert error == 'cycle'


# ==================== removeParent ====================


class TestRemoveParent:
    def test_remove_parent_deletes_edge(self, bridge: DatabaseBridge, user_db: UserDatabase):
        a = _make_node(user_db, 'A')
        b = _make_node(user_db, 'B')
        edge = _add_edge(user_db, a.id, b.id)

        data = _ok(bridge.removeParent(edge.id))
        assert data == {'ok': True}

        # No more parents for B.
        parents = _ok(bridge.getParents(b.id))
        assert parents == []


# ==================== setPrimaryParent ====================


class TestSetPrimaryParent:
    def test_set_primary_parent_switches_canonical(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """setPrimaryParent atomically moves the primary flag."""
        resp = _make_node(user_db, 'Respiratory')
        preg = _make_node(user_db, 'Pregnancy')
        pe = _make_node(user_db, 'PE')

        _add_edge(user_db, resp.id, pe.id, is_primary=True)
        _add_edge(user_db, preg.id, pe.id, is_primary=False)

        data = _ok(bridge.setPrimaryParent(pe.id, preg.id))
        assert data['parent_id'] == preg.id
        assert data['child_id'] == pe.id
        assert data['is_primary'] is True

        # Verify only Pregnancy is primary now.
        parents = _ok(bridge.getParents(pe.id))
        primaries = [p for p in parents if p['is_primary']]
        assert len(primaries) == 1
        assert primaries[0]['parent_id'] == preg.id

    def test_set_primary_parent_no_edge_errors(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Calling on a non-existent edge returns an error."""
        a = _make_node(user_db, 'A')
        b = _make_node(user_db, 'B')

        # No edge between them -> SubjectNodeError -> generic failure.
        error = _err(bridge.setPrimaryParent(b.id, a.id))
        assert error and 'Failed to set primary parent' in error


# ==================== getParents ====================


class TestGetParents:
    def test_get_parents_returns_primary_first(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """getParents orders the primary edge before non-primary edges."""
        resp = _make_node(user_db, 'Respiratory')
        preg = _make_node(user_db, 'Pregnancy')
        leaf = _make_node(user_db, 'PE')

        # Insert non-primary first to make sure ordering is by flag, not insertion.
        _add_edge(user_db, resp.id, leaf.id, is_primary=False)
        _add_edge(user_db, preg.id, leaf.id, is_primary=True)

        data = _ok(bridge.getParents(leaf.id))

        assert len(data) == 2
        assert data[0]['is_primary'] is True
        assert data[0]['parent_id'] == preg.id
        assert data[0]['parent_name'] == 'Pregnancy'
        assert data[1]['is_primary'] is False
        assert data[1]['parent_id'] == resp.id

    def test_get_parents_empty_for_orphan(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """A node with no edges returns an empty list."""
        n = _make_node(user_db, 'Orphan')
        assert _ok(bridge.getParents(n.id)) == []


# ==================== getPathsToRoot ====================


class TestGetPathsToRoot:
    def test_get_paths_to_root_returns_all_paths(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """A diamond DAG yields two distinct root-to-leaf paths."""
        # Diamond:        ROOT
        #                /    \
        #               A      B
        #                \    /
        #                 LEAF (primary parent = A)
        root = _make_node(user_db, 'Root')
        a = _make_node(user_db, 'A')
        b = _make_node(user_db, 'B')
        leaf = _make_node(user_db, 'Leaf')

        _add_edge(user_db, root.id, a.id, is_primary=True)
        _add_edge(user_db, root.id, b.id, is_primary=True)
        _add_edge(user_db, a.id, leaf.id, is_primary=True)
        _add_edge(user_db, b.id, leaf.id, is_primary=False)

        paths = _ok(bridge.getPathsToRoot(leaf.id))

        assert len(paths) == 2
        # Each path starts at root and ends at leaf.
        for path in paths:
            assert path[0] == root.id
            assert path[-1] == leaf.id
        # Primary path comes first: root -> A -> leaf.
        assert paths[0] == [root.id, a.id, leaf.id]


# ==================== setPrimaryParentForEntry ====================


class TestSetPrimaryParentForEntry:
    """Tests for the per-mapping primary-parent override."""

    def _setup_entry_and_mapping(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ) -> tuple[int, int, int]:
        """Returns (entry_id, subject_node_id, parent_id) ready for the slot."""
        # Need an exam context, session, entry, and a subject node mapping.
        ctx_resp = json.loads(bridge.createExamContext(
            exam_name='Test Exam',
            exam_description='',
            exam_date='',
            weight_rules_json='',
            hierarchy_levels_json='',
            notes='',
        ))
        assert ctx_resp['success'], ctx_resp.get('error')
        exam_context_id = ctx_resp['data']['id']

        leaf = _make_node(user_db, 'Pulmonary Embolism')
        parent = _make_node(user_db, 'Pregnancy')

        session = user_db.create_review_session(
            exam_context_id=exam_context_id,
            total_questions=10,
            total_incorrect=1,
            session_name='Test session',
            date_encountered=date.today(),
        )
        entry = user_db.create_question_entry(
            review_session_id=session.id,
            user_answer='A',
            correct_answer='B',
            primary_subject_ids=[leaf.id],
        )

        # The entry-creation path inserts the mapping with NULL primary_parent_id.
        return entry.id, leaf.id, parent.id

    def test_set_primary_parent_for_entry_updates_db(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        entry_id, leaf_id, parent_id = self._setup_entry_and_mapping(bridge, user_db)

        data = _ok(bridge.setPrimaryParentForEntry(entry_id, leaf_id, parent_id))
        assert data == {'ok': True}

        row = user_db.fetchone(
            "SELECT primary_parent_id FROM entry_subject_mappings "
            "WHERE question_entry_id = ? AND subject_node_id = ?",
            (entry_id, leaf_id),
        )
        assert row is not None
        assert row['primary_parent_id'] == parent_id

    def test_set_primary_parent_for_entry_with_null_clears(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Passing None clears the column back to NULL."""
        entry_id, leaf_id, parent_id = self._setup_entry_and_mapping(bridge, user_db)

        # First set a value so we have something to clear.
        _ok(bridge.setPrimaryParentForEntry(entry_id, leaf_id, parent_id))

        # Now clear with None.
        _ok(bridge.setPrimaryParentForEntry(entry_id, leaf_id, None))

        row = user_db.fetchone(
            "SELECT primary_parent_id FROM entry_subject_mappings "
            "WHERE question_entry_id = ? AND subject_node_id = ?",
            (entry_id, leaf_id),
        )
        assert row is not None
        assert row['primary_parent_id'] is None


# ==================== Stage 5: Allocation bridge ====================
#
# Tests for the Stage 5 read-side bridge slots
# (``getQuestionAllocation`` / ``getEffectiveQuestionCounts``). The
# DB layer is exhaustively covered in
# ``tests/database/test_question_allocation_bridge.py``; this class
# only proves the JSON-serialization shape and error contract.


class TestGetQuestionAllocation:
    """Stage 5: ``getQuestionAllocation`` slot returns a well-formed
    per-parent allocation payload."""

    def _setup_exam_with_length(
        self, user_db: UserDatabase, length_typical: int = 280
    ) -> tuple[int, int, list[int]]:
        """Returns (exam_context_id, parent_id, [edge_id, ...])."""
        ctx = user_db.create_exam_context(
            exam_name='Stage 5 Bridge Exam',
            exam_description='Allocation bridge test',
        )
        user_db.update_exam_length(
            ctx.id,
            kind='fixed',
            min=length_typical,
            max=length_typical,
            typical=length_typical,
        )
        parent = user_db.create_subject_node_with_weight(
            exam_context='Stage 5 Bridge Exam',
            name='Cardio',
            level_type='System',
            exam_weight_low=100,
            exam_weight_high=100,
            weight_source='user_defined',
        )
        edge_ids = []
        for name, rw in (('A', 30.0), ('B', 30.0), ('C', 40.0)):
            child = user_db.create_subject_node_with_weight(
                exam_context='Stage 5 Bridge Exam',
                name=name,
                level_type='Topic',
                parent_id=parent.id,
                relative_weight=rw,
                weight_source='user_defined',
            )
            edge_row = user_db.fetchone(
                "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
                (parent.id, child.id),
            )
            # Stamp the per-edge relative_weight (the legacy creator
            # writes node-level; the read path keys off edge-level).
            user_db.execute(
                "UPDATE subject_edges SET relative_weight = ?, "
                "weight_source = 'user_defined' WHERE id = ?",
                (rw, edge_row['id']),
            )
            user_db.conn.commit()
            edge_ids.append(edge_row['id'])
        return ctx.id, parent.id, edge_ids

    def test_getQuestionAllocation_returns_serialized_payload(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Slot returns valid JSON with the expected shape and totals."""
        _exam_id, parent_id, edge_ids = self._setup_exam_with_length(
            user_db, length_typical=280
        )

        data = _ok(bridge.getQuestionAllocation(parent_id))

        assert data['ok'] is True
        assert data['parent_id'] == parent_id
        assert data['length_kind'] == 'fixed'
        assert data['total_q'] == 280
        children = data['children']
        assert len(children) == 3
        # Hamilton sums to total_q.
        assert sum(c['allocated_q'] for c in children) == 280
        # Every child carries the documented keys.
        for c in children:
            assert {
                'edge_id', 'child_id', 'child_name', 'allocated_q',
                'low_q', 'high_q', 'weight_source', 'is_anchor',
                'relative_weight',
            }.issubset(c)
        # Edges line up.
        returned_edge_ids = {c['edge_id'] for c in children}
        assert returned_edge_ids == set(edge_ids)

    def test_getQuestionAllocation_unknown_length_returns_nulls(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """When length_kind='unknown', total_q is null and every
        allocated_q is null (the degradation contract)."""
        ctx = user_db.create_exam_context(
            exam_name='Unknown Length Exam',
            exam_description='',
        )
        parent = user_db.create_subject_node_with_weight(
            exam_context='Unknown Length Exam',
            name='Sys',
            level_type='System',
        )
        child = user_db.create_subject_node_with_weight(
            exam_context='Unknown Length Exam',
            name='Topic',
            level_type='Topic',
            parent_id=parent.id,
            relative_weight=50,
        )
        edge_row = user_db.fetchone(
            "SELECT id FROM subject_edges WHERE child_id = ?", (child.id,),
        )
        user_db.execute(
            "UPDATE subject_edges SET relative_weight = 50 WHERE id = ?",
            (edge_row['id'],),
        )
        user_db.conn.commit()

        data = _ok(bridge.getQuestionAllocation(parent.id))
        assert data['length_kind'] == 'unknown'
        assert data['total_q'] is None
        for c in data['children']:
            assert c['allocated_q'] is None
            assert c['low_q'] is None
            assert c['high_q'] is None

    def test_getQuestionAllocation_unknown_parent_errors(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Unknown parent_id returns success=False, not a crash."""
        error = _err(bridge.getQuestionAllocation(99999))
        assert error and 'not found' in error.lower()


class TestGetEffectiveQuestionCounts:
    """Stage 5: ``getEffectiveQuestionCounts`` slot returns the whole-
    tree list per-edge."""

    def test_getEffectiveQuestionCounts_returns_tree(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Slot returns the whole-tree list with q_typical populated."""
        ctx = user_db.create_exam_context(
            exam_name='Stage 5 Whole Tree',
            exam_description='',
        )
        user_db.update_exam_length(
            ctx.id, kind='fixed', min=100, max=100, typical=100,
        )
        sys_node = user_db.create_subject_node_with_weight(
            exam_context='Stage 5 Whole Tree',
            name='Sys',
            level_type='System',
            exam_weight_low=100,
            exam_weight_high=100,
        )
        for name, rw in (('A', 30.0), ('B', 70.0)):
            child = user_db.create_subject_node_with_weight(
                exam_context='Stage 5 Whole Tree',
                name=name,
                level_type='Topic',
                parent_id=sys_node.id,
                relative_weight=rw,
            )
            edge_row = user_db.fetchone(
                "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
                (sys_node.id, child.id),
            )
            user_db.execute(
                "UPDATE subject_edges SET relative_weight = ? WHERE id = ?",
                (rw, edge_row['id']),
            )
            user_db.conn.commit()

        data = _ok(bridge.getEffectiveQuestionCounts(ctx.id))
        assert isinstance(data, list)
        # Response shape (post-bugfix 8890d8a): one synthetic root row
        # per System node (edge_id=None) PLUS one row per edge below it.
        # Here that's 1 root ("Sys") + 2 edges (A, B) = 3.
        assert len(data) == 3
        root_rows = [r for r in data if r['edge_id'] is None]
        edge_rows = [r for r in data if r['edge_id'] is not None]
        assert len(root_rows) == 1
        assert len(edge_rows) == 2
        # Root row carries the System's q_typical (100% × length_typical=100 = 100).
        assert root_rows[0]['child_id'] == sys_node.id
        assert root_rows[0]['q_typical'] == 100
        assert root_rows[0]['parent_id'] is None
        # Edge rows carry per-child allocations (30 + 70 = 100).
        for row in edge_rows:
            assert 'edge_id' in row
            assert 'child_id' in row
            assert 'q_typical' in row
            assert row['q_typical'] is not None
            assert row['parent_id'] == sys_node.id
        assert sum(r['q_typical'] for r in edge_rows) == 100

    def test_getEffectiveQuestionCounts_unknown_exam_context_errors(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Unknown exam_context_id surfaces a clean error message."""
        error = _err(bridge.getEffectiveQuestionCounts(99999))
        assert error and 'not found' in error.lower()
