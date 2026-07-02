"""
Test Graph Database Phase 2 — Dual-Write Operations.

Covers P2.6 requirements:
  - Subject dual-writes (create, parent/child, root-of)
  - Entry dual-writes (create, update subjects, delete)
  - Note dual-writes (create, update linked subjects, delete)
  - Dimension dual-writes (create, delete)
  - Stale flag and reconciliation infrastructure
  - Exception safety of _dual_write_graph
"""
import json
import logging
import shutil
import pytest
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

from database import MasterDatabase, UserDatabase
from database.domains.graph import GRAPH_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_dir():
    """Create temporary directory for test databases."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
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
        username="dual_write_user",
        display_name="Dual Write Test User",
        user_types=["student"],
    )


@pytest.fixture
def dual_db(master_db, test_user):
    """UserDatabase with test data for dual-write testing.

    Sets up exam context, dimensions, and subjects in SQLite
    then verifies graph ETL populated correctly on init.
    """
    db_path = master_db.ensure_user_database(test_user.id)

    # First open — creates empty graph via ETL (no data yet)
    db = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)

    # Ensure prerequisite schemas
    db._ensure_phase2_schema()
    db._ensure_phase4_schema()
    db._ensure_phase7_schema()

    # Create exam context via SQLite
    db.execute(
        "INSERT INTO exam_contexts (id, user_id, exam_name, is_active) "
        "VALUES (?, ?, ?, 1)",
        (100, db.user_id, 'TestExam'),
    )
    db.conn.commit()

    # Create ExamContext node in graph (ETL missed it since it was added after init)
    db._graph_execute(
        "MERGE (ec:ExamContext {sqlite_id: $id}) SET ec.name = $name",
        {"id": 100, "name": "TestExam"},
    )

    # Ensure user_preferences row exists (needed for stale flag tests)
    db.get_preferences()

    # Store for test access
    db._test_exam_id = 100
    db._test_exam_name = 'TestExam'

    yield db
    db.close()


# ===================================================================
# Subject Operations
# ===================================================================

class TestSubjectDualWrite:
    """Tests for subject node dual-write to graph."""

    def test_create_subject_writes_to_graph(self, dual_db):
        """create_subject_node() should create a :Subject node in the graph."""
        node = dual_db.create_subject_node(
            exam_context='TestExam',
            name='Cardiology',
            level_type='System',
            parent_id=None,
            sort_order=1,
        )

        # Verify in graph
        result = dual_db._graph_execute(
            "MATCH (s:Subject {sqlite_id: $id}) "
            "RETURN s.name, s.level_type, s.full_path",
            {"id": node.id},
        )
        rows = dual_db._graph_collect(result)
        assert len(rows) == 1
        assert rows[0][0] == 'Cardiology'
        assert rows[0][1] == 'System'
        # full_path for a root node is just the name
        assert 'Cardiology' in rows[0][2]

    def test_create_subject_with_parent_creates_has_child_edge(self, dual_db):
        """Creating a child subject should produce a :HAS_CHILD edge from parent."""
        parent = dual_db.create_subject_node(
            exam_context='TestExam',
            name='Cardiology',
            level_type='System',
            parent_id=None,
            sort_order=1,
        )
        child = dual_db.create_subject_node(
            exam_context='TestExam',
            name='Heart Valves',
            level_type='Topic',
            parent_id=parent.id,
            sort_order=1,
        )

        # Verify HAS_CHILD edge
        result = dual_db._graph_execute(
            "MATCH (p:Subject {sqlite_id: $pid})-[:HAS_CHILD]->(c:Subject {sqlite_id: $cid}) "
            "RETURN p.name, c.name",
            {"pid": parent.id, "cid": child.id},
        )
        rows = dual_db._graph_collect(result)
        assert len(rows) == 1
        assert rows[0][0] == 'Cardiology'
        assert rows[0][1] == 'Heart Valves'

    def test_create_root_subject_creates_root_of_edge(self, dual_db):
        """Creating a root subject should produce a :ROOT_OF edge from ExamContext."""
        node = dual_db.create_subject_node(
            exam_context='TestExam',
            name='Neurology',
            level_type='System',
            parent_id=None,
            sort_order=1,
        )

        # Verify ROOT_OF edge
        result = dual_db._graph_execute(
            "MATCH (ec:ExamContext {sqlite_id: $ecid})-[:ROOT_OF]->(s:Subject {sqlite_id: $sid}) "
            "RETURN ec.name, s.name",
            {"ecid": dual_db._test_exam_id, "sid": node.id},
        )
        rows = dual_db._graph_collect(result)
        assert len(rows) == 1
        assert rows[0][0] == 'TestExam'
        assert rows[0][1] == 'Neurology'

    def test_create_subject_with_dimension_creates_belongs_to_edge(self, dual_db):
        """Creating a subject with dimension_id should produce a :BELONGS_TO edge."""
        # Create dimension first
        dim_id = dual_db.create_dimension(
            exam_id=dual_db._test_exam_id,
            name='Anatomy',
            display_order=1,
        )

        node = dual_db.create_subject_node(
            exam_context='TestExam',
            name='Upper Limb',
            level_type='System',
            parent_id=None,
            sort_order=1,
            dimension_id=dim_id,
        )

        # Verify BELONGS_TO edge
        result = dual_db._graph_execute(
            "MATCH (s:Subject {sqlite_id: $sid})-[:BELONGS_TO]->(d:Dimension {sqlite_id: $did}) "
            "RETURN s.name, d.name",
            {"sid": node.id, "did": dim_id},
        )
        rows = dual_db._graph_collect(result)
        assert len(rows) == 1
        assert rows[0][0] == 'Upper Limb'
        assert rows[0][1] == 'Anatomy'


# ===================================================================
# Entry Operations
# ===================================================================

class TestEntryDualWrite:
    """Tests for question entry dual-write to graph."""

    @pytest.fixture
    def entry_db(self, dual_db):
        """Extend dual_db with a subject and review session for entry tests."""
        db = dual_db

        # Create a subject
        node = db.create_subject_node(
            exam_context='TestExam',
            name='Cardiology',
            level_type='System',
            parent_id=None,
            sort_order=1,
        )
        db._test_subject_id = node.id

        # Create a second subject for update tests
        node2 = db.create_subject_node(
            exam_context='TestExam',
            name='Neurology',
            level_type='System',
            parent_id=None,
            sort_order=2,
        )
        db._test_subject_id_2 = node2.id

        # Create review session
        session = db.create_review_session(
            exam_context_id=db._test_exam_id,
            date_encountered=date.today(),
            total_questions=10,
            total_incorrect=5,
        )
        db._test_session_id = session.id

        return db

    def test_create_entry_writes_stub_to_graph(self, entry_db):
        """create_question_entry() should create :Entry stub and :TAGGED_TO edges."""
        entry = entry_db.create_question_entry(
            review_session_id=entry_db._test_session_id,
            user_answer='A',
            correct_answer='B',
            primary_subject_ids=[entry_db._test_subject_id],
        )

        # Verify Entry node
        result = entry_db._graph_execute(
            "MATCH (e:Entry {sqlite_id: $id}) RETURN e.sqlite_id",
            {"id": entry.id},
        )
        rows = entry_db._graph_collect(result)
        assert len(rows) == 1

        # Verify TAGGED_TO edge
        result2 = entry_db._graph_execute(
            "MATCH (e:Entry {sqlite_id: $eid})-[r:TAGGED_TO]->(s:Subject {sqlite_id: $sid}) "
            "RETURN r.mapping_type",
            {"eid": entry.id, "sid": entry_db._test_subject_id},
        )
        edges = entry_db._graph_collect(result2)
        assert len(edges) == 1
        assert edges[0][0] == 'primary'

    def test_update_entry_subjects_updates_graph_edges(self, entry_db):
        """Updating subject mappings should replace TAGGED_TO edges in graph."""
        entry = entry_db.create_question_entry(
            review_session_id=entry_db._test_session_id,
            user_answer='A',
            correct_answer='B',
            primary_subject_ids=[entry_db._test_subject_id],
        )

        # Update to a different subject
        entry_db.update_question_entry(
            entry_id=entry.id,
            primary_subject_ids=[entry_db._test_subject_id_2],
        )

        # Old edge should be gone
        result_old = entry_db._graph_execute(
            "MATCH (e:Entry {sqlite_id: $eid})-[:TAGGED_TO]->(s:Subject {sqlite_id: $sid}) "
            "RETURN count(*)",
            {"eid": entry.id, "sid": entry_db._test_subject_id},
        )
        old_rows = entry_db._graph_collect(result_old)
        assert old_rows[0][0] == 0

        # New edge should exist
        result_new = entry_db._graph_execute(
            "MATCH (e:Entry {sqlite_id: $eid})-[:TAGGED_TO]->(s:Subject {sqlite_id: $sid}) "
            "RETURN count(*)",
            {"eid": entry.id, "sid": entry_db._test_subject_id_2},
        )
        new_rows = entry_db._graph_collect(result_new)
        assert new_rows[0][0] == 1

    def test_delete_entry_removes_from_graph(self, entry_db):
        """delete_question_entry() should remove :Entry stub from graph."""
        entry = entry_db.create_question_entry(
            review_session_id=entry_db._test_session_id,
            user_answer='A',
            correct_answer='B',
            primary_subject_ids=[entry_db._test_subject_id],
        )
        entry_id = entry.id

        entry_db.delete_question_entry(entry_id)

        # Entry node should be gone
        result = entry_db._graph_execute(
            "MATCH (e:Entry {sqlite_id: $id}) RETURN count(*)",
            {"id": entry_id},
        )
        rows = entry_db._graph_collect(result)
        assert rows[0][0] == 0


# ===================================================================
# Note Operations
# ===================================================================

class TestNoteDualWrite:
    """Tests for entry note dual-write to graph."""

    @pytest.fixture
    def note_db(self, dual_db):
        """Extend dual_db with subjects, session, and entry for note tests."""
        db = dual_db

        # Create subjects
        node = db.create_subject_node(
            exam_context='TestExam',
            name='Cardiology',
            level_type='System',
            parent_id=None,
            sort_order=1,
        )
        db._test_subject_id = node.id

        node2 = db.create_subject_node(
            exam_context='TestExam',
            name='Neurology',
            level_type='System',
            parent_id=None,
            sort_order=2,
        )
        db._test_subject_id_2 = node2.id

        # Create review session + entry
        session = db.create_review_session(
            exam_context_id=db._test_exam_id,
            date_encountered=date.today(),
            total_questions=10,
            total_incorrect=5,
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer='A',
            correct_answer='B',
        )
        db._test_entry_id = entry.id

        return db

    def test_create_note_writes_to_graph(self, note_db):
        """add_entry_note() should create :Note stub and :NOTE_LINKED_TO edges."""
        note = note_db.add_entry_note(
            entry_id=note_db._test_entry_id,
            content_html='<p>Important concept</p>',
            linked_subject_ids=[note_db._test_subject_id],
        )

        # Verify Note node
        result = note_db._graph_execute(
            "MATCH (n:Note {sqlite_id: $id}) RETURN n.sqlite_id",
            {"id": note.id},
        )
        rows = note_db._graph_collect(result)
        assert len(rows) == 1

        # Verify NOTE_LINKED_TO edge
        result2 = note_db._graph_execute(
            "MATCH (n:Note {sqlite_id: $nid})-[:NOTE_LINKED_TO]->(s:Subject {sqlite_id: $sid}) "
            "RETURN n.sqlite_id, s.sqlite_id",
            {"nid": note.id, "sid": note_db._test_subject_id},
        )
        edges = note_db._graph_collect(result2)
        assert len(edges) == 1

    def test_update_note_subjects_updates_graph(self, note_db):
        """update_entry_note() with new linked_subject_ids should update graph edges."""
        note = note_db.add_entry_note(
            entry_id=note_db._test_entry_id,
            content_html='<p>Note text</p>',
            linked_subject_ids=[note_db._test_subject_id],
        )

        # Update linked subjects
        note_db.update_entry_note(
            note_id=note.id,
            linked_subject_ids=[note_db._test_subject_id_2],
        )

        # Old link should be gone
        result_old = note_db._graph_execute(
            "MATCH (n:Note {sqlite_id: $nid})-[:NOTE_LINKED_TO]->(s:Subject {sqlite_id: $sid}) "
            "RETURN count(*)",
            {"nid": note.id, "sid": note_db._test_subject_id},
        )
        assert note_db._graph_collect(result_old)[0][0] == 0

        # New link should exist
        result_new = note_db._graph_execute(
            "MATCH (n:Note {sqlite_id: $nid})-[:NOTE_LINKED_TO]->(s:Subject {sqlite_id: $sid}) "
            "RETURN count(*)",
            {"nid": note.id, "sid": note_db._test_subject_id_2},
        )
        assert note_db._graph_collect(result_new)[0][0] == 1

    def test_delete_note_removes_from_graph(self, note_db):
        """delete_entry_note() should remove :Note stub from graph."""
        note = note_db.add_entry_note(
            entry_id=note_db._test_entry_id,
            content_html='<p>Temporary note</p>',
            linked_subject_ids=[note_db._test_subject_id],
        )
        note_id = note.id

        note_db.delete_entry_note(note_id)

        # Note node should be gone
        result = note_db._graph_execute(
            "MATCH (n:Note {sqlite_id: $id}) RETURN count(*)",
            {"id": note_id},
        )
        rows = note_db._graph_collect(result)
        assert rows[0][0] == 0

        # Edges should also be gone
        result2 = note_db._graph_execute(
            "MATCH (n:Note {sqlite_id: $id})-[:NOTE_LINKED_TO]->() RETURN count(*)",
            {"id": note_id},
        )
        assert note_db._graph_collect(result2)[0][0] == 0


# ===================================================================
# Dimension Operations
# ===================================================================

class TestDimensionDualWrite:
    """Tests for dimension dual-write to graph."""

    def test_create_dimension_writes_to_graph(self, dual_db):
        """create_dimension() should create :Dimension node and :HAS_DIMENSION edge."""
        dim_id = dual_db.create_dimension(
            exam_id=dual_db._test_exam_id,
            name='Anatomy',
            display_order=1,
        )

        # Verify Dimension node
        result = dual_db._graph_execute(
            "MATCH (d:Dimension {sqlite_id: $id}) RETURN d.name",
            {"id": dim_id},
        )
        rows = dual_db._graph_collect(result)
        assert len(rows) == 1
        assert rows[0][0] == 'Anatomy'

        # Verify HAS_DIMENSION edge
        result2 = dual_db._graph_execute(
            "MATCH (ec:ExamContext {sqlite_id: $ecid})-[:HAS_DIMENSION]->(d:Dimension {sqlite_id: $did}) "
            "RETURN ec.name, d.name",
            {"ecid": dual_db._test_exam_id, "did": dim_id},
        )
        edges = dual_db._graph_collect(result2)
        assert len(edges) == 1
        assert edges[0][0] == 'TestExam'
        assert edges[0][1] == 'Anatomy'

    def test_delete_dimension_removes_from_graph(self, dual_db):
        """delete_dimension() should remove :Dimension node and edges from graph."""
        dim_id = dual_db.create_dimension(
            exam_id=dual_db._test_exam_id,
            name='Physiology',
            display_order=2,
        )

        # Confirm it exists
        result = dual_db._graph_execute(
            "MATCH (d:Dimension {sqlite_id: $id}) RETURN count(*)",
            {"id": dim_id},
        )
        assert dual_db._graph_collect(result)[0][0] == 1

        # Delete it
        dual_db.delete_dimension(dim_id)

        # Should be gone
        result2 = dual_db._graph_execute(
            "MATCH (d:Dimension {sqlite_id: $id}) RETURN count(*)",
            {"id": dim_id},
        )
        assert dual_db._graph_collect(result2)[0][0] == 0

    def test_update_dimension_name_updates_graph(self, dual_db):
        """update_dimension() with a new name should update the graph node."""
        dim_id = dual_db.create_dimension(
            exam_id=dual_db._test_exam_id,
            name='OldName',
            display_order=3,
        )

        dual_db.update_dimension(dimension_id=dim_id, name='NewName')

        result = dual_db._graph_execute(
            "MATCH (d:Dimension {sqlite_id: $id}) RETURN d.name",
            {"id": dim_id},
        )
        rows = dual_db._graph_collect(result)
        assert len(rows) == 1
        assert rows[0][0] == 'NewName'


# ===================================================================
# Infrastructure — Stale Flag, Reconciliation, Exception Safety
# ===================================================================

class TestDualWriteInfrastructure:
    """Tests for stale flag, reconciliation, and exception safety."""

    def test_stale_flag_set_on_graph_failure(self, dual_db):
        """When a graph write fails, the stale flag should be set."""
        assert dual_db._is_graph_stale() is False

        # Force a graph failure by passing a bad callable
        def bad_write():
            raise RuntimeError("Simulated graph failure")

        dual_db._dual_write_graph("test_op", bad_write)

        assert dual_db._is_graph_stale() is True

    def test_reconciliation_rebuilds_graph(self, dual_db):
        """Setting stale flag and calling reconcile should rebuild graph from SQLite."""
        # Create some data so reconciliation has something to rebuild
        dim_id = dual_db.create_dimension(
            exam_id=dual_db._test_exam_id,
            name='ReconDim',
            display_order=1,
        )
        node = dual_db.create_subject_node(
            exam_context='TestExam',
            name='ReconSubject',
            level_type='System',
            parent_id=None,
            sort_order=1,
            dimension_id=dim_id,
        )

        # Mark stale
        dual_db._mark_graph_stale()
        assert dual_db._is_graph_stale() is True

        # Reconcile
        dual_db._reconcile_graph()

        # Graph should be available again
        assert dual_db._graph_available is True
        # Stale flag should be cleared
        assert dual_db._is_graph_stale() is False

        # Data should be rebuilt from SQLite
        result = dual_db._graph_execute(
            "MATCH (s:Subject {sqlite_id: $id}) RETURN s.name",
            {"id": node.id},
        )
        rows = dual_db._graph_collect(result)
        assert len(rows) == 1
        assert rows[0][0] == 'ReconSubject'

        # Dimension should also be rebuilt
        result2 = dual_db._graph_execute(
            "MATCH (d:Dimension {sqlite_id: $id}) RETURN d.name",
            {"id": dim_id},
        )
        rows2 = dual_db._graph_collect(result2)
        assert len(rows2) == 1
        assert rows2[0][0] == 'ReconDim'

    def test_dual_write_graph_catches_exceptions(self, dual_db):
        """_dual_write_graph should not propagate exceptions to the caller."""
        def exploding_write():
            raise ValueError("This should be caught")

        # Should not raise
        dual_db._dual_write_graph("safe_test", exploding_write)

        # Stale flag should be set as a side effect
        assert dual_db._is_graph_stale() is True

    def test_dual_write_graph_noop_when_unavailable(self, dual_db):
        """_dual_write_graph should do nothing when graph is unavailable."""
        # Save and disable graph
        original_conn = dual_db._graph_conn
        dual_db._graph_conn = None

        call_count = 0

        def should_not_run():
            nonlocal call_count
            call_count += 1

        dual_db._dual_write_graph("noop_test", should_not_run)
        assert call_count == 0

        # Restore
        dual_db._graph_conn = original_conn

    def test_mark_graph_stale_and_clear(self, dual_db):
        """_mark_graph_stale sets the flag, reconciliation clears it."""
        assert dual_db._is_graph_stale() is False

        dual_db._mark_graph_stale()
        assert dual_db._is_graph_stale() is True

        # Reconcile clears stale
        dual_db._reconcile_graph()
        assert dual_db._is_graph_stale() is False
