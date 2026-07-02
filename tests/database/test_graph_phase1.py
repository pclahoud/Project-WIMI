"""
Test Graph Database Phase 1 — Connection, Schema, ETL, Shadow Reads.

Covers P1.6 requirements:
  - Connection lifecycle (open, close, reopen)
  - Schema initialization and idempotency
  - ETL population from SQLite data
  - Failure handling (ImportError, ETL crash)
  - Shadow read comparison infrastructure
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
        username="graph_test_user",
        display_name="Graph Test User",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db, test_user):
    """Create user database with graph support (no extra SQLite data)."""
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username,
    )
    yield db
    db.close()


def _seed_sqlite_data(db):
    """Insert test dimensions, subjects, entries, mappings, and notes into SQLite.

    This helper is used by ETL tests that need data in SQLite *before* the
    graph ETL runs.  It writes directly through the UserDatabase's SQLite
    connection so the graph ETL can pick it up on a subsequent call to
    ``_populate_graph_from_sqlite()``.
    """
    # Ensure all prerequisite schemas exist:
    #   Phase 2 -> exam_contexts
    #   Phase 4 -> review_sessions, question_entries, entry_subject_mappings, entry_notes
    #   Phase 7 -> exam_dimensions, dimension_id on subject_nodes
    db._ensure_phase2_schema()
    db._ensure_phase4_schema()
    db._ensure_phase7_schema()

    # Exam context (user_id is NOT NULL in the schema)
    db.execute(
        "INSERT OR IGNORE INTO exam_contexts (id, user_id, exam_name, is_active) VALUES (?, ?, ?, ?)",
        (100, db.user_id, "TestExam", 1),
    )
    db.conn.commit()

    # Dimensions (display_order is NOT NULL with UNIQUE constraint per exam)
    db.execute(
        "INSERT OR IGNORE INTO exam_dimensions (id, exam_id, name, display_order) "
        "VALUES (?, ?, ?, ?)",
        (200, 100, "Anatomy", 1),
    )
    db.execute(
        "INSERT OR IGNORE INTO exam_dimensions (id, exam_id, name, display_order) "
        "VALUES (?, ?, ?, ?)",
        (201, 100, "Physiology", 2),
    )
    db.conn.commit()

    # Subject nodes — root + child
    db.execute(
        "INSERT OR IGNORE INTO subject_nodes "
        "(id, exam_context, name, level_type, parent_id, dimension_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (300, "TestExam", "CardioSystem", "System", None, 200, "active"),
    )
    db.execute(
        "INSERT OR IGNORE INTO subject_nodes "
        "(id, exam_context, name, level_type, parent_id, dimension_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (301, "TestExam", "HeartValves", "Topic", 300, 200, "active"),
    )
    db.conn.commit()

    # Review session (needed for question_entries FK)
    db.execute(
        "INSERT OR IGNORE INTO review_sessions "
        "(id, user_id, exam_context_id, date_encountered, total_questions, total_incorrect) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (400, db.user_id, 100, date.today().isoformat(), 10, 5),
    )
    db.conn.commit()

    # Question entry (schema requires entry_order, user_answer, correct_answer)
    db.execute(
        "INSERT OR IGNORE INTO question_entries "
        "(id, review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, ?, ?, ?)",
        (500, 400, 1, "A", "B"),
    )
    db.conn.commit()

    # Entry-subject mapping
    db.execute(
        "INSERT OR IGNORE INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type) "
        "VALUES (?, ?, ?)",
        (500, 301, "primary"),
    )
    db.conn.commit()

    # Entry note with linked subject (uses actual schema column names)
    db.execute(
        "INSERT OR IGNORE INTO entry_notes "
        "(id, question_entry_id, content_html, linked_subject_ids) "
        "VALUES (?, ?, ?, ?)",
        (600, 500, "Remember aortic valve anatomy", json.dumps([301])),
    )
    db.conn.commit()


@pytest.fixture
def seeded_db(master_db, test_user):
    """Create a UserDatabase, seed SQLite data, delete graph, and reopen.

    This ensures the ETL runs against populated SQLite tables.
    """
    db_path = master_db.ensure_user_database(test_user.id)

    # First open — creates empty graph
    db = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)
    _seed_sqlite_data(db)

    # Close and delete the .lbdb so the next open triggers a fresh ETL
    graph_path = Path(str(db.db_path)).with_suffix('.lbdb')
    # Clear the preference so _ensure_graph_schema thinks this is first run
    db._clear_graph_schema_version_pref()
    db.close()

    if graph_path.exists():
        if graph_path.is_dir():
            shutil.rmtree(str(graph_path), ignore_errors=True)
        else:
            graph_path.unlink(missing_ok=True)

    # Reopen — triggers fresh graph schema init + ETL with seeded data
    db2 = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)
    yield db2
    db2.close()


# ===================================================================
# Connection Lifecycle
# ===================================================================

class TestConnectionLifecycle:
    """Tests for graph database connection open/close/reopen."""

    def test_graph_opens_alongside_sqlite(self, user_db):
        """Graph database should be available after UserDatabase init."""
        assert user_db._graph_available is True

    def test_graph_closes_cleanly(self, master_db, test_user):
        """Closing UserDatabase should close graph without errors."""
        db_path = master_db.ensure_user_database(test_user.id)
        db = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)
        assert db._graph_available is True
        db.close()
        # After close, graph objects should be None
        assert db._graph_conn is None
        assert db._graph_db is None

    def test_graph_path_derived_from_sqlite(self, user_db):
        """The .lbdb path should match the .db path with a different extension."""
        expected = Path(str(user_db.db_path)).with_suffix('.lbdb')
        assert user_db._graph_path == expected

    def test_graph_reopen_after_close(self, master_db, test_user):
        """Data should persist after close and reopen."""
        db_path = master_db.ensure_user_database(test_user.id)
        db = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)

        # Write GraphMeta was already done during init — read version
        version1 = db._get_graph_meta_version()
        assert version1 == GRAPH_SCHEMA_VERSION
        db.close()

        # Reopen
        db2 = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)
        version2 = db2._get_graph_meta_version()
        assert version2 == GRAPH_SCHEMA_VERSION
        db2.close()


# ===================================================================
# Schema Initialization
# ===================================================================

class TestSchemaInitialization:
    """Tests for graph schema creation and versioning."""

    def test_ensure_graph_schema_creates_tables(self, user_db):
        """All 6 node tables should be queryable after init."""
        for label in ("ExamContext", "Dimension", "Subject", "Entry", "Note", "GraphMeta"):
            result = user_db._graph_conn.execute(
                f"MATCH (n:{label}) RETURN count(n)"
            )
            rows = user_db._graph_collect(result)
            # Should return a row with a count (even if 0)
            assert len(rows) == 1, f"Query for :{label} returned no rows"

    def test_ensure_graph_schema_idempotent(self, user_db):
        """Calling _ensure_graph_schema() twice should not raise."""
        user_db._ensure_graph_schema()
        user_db._ensure_graph_schema()
        # Still available
        assert user_db._graph_available is True
        assert user_db._get_graph_meta_version() == GRAPH_SCHEMA_VERSION

    def test_graph_meta_version(self, user_db):
        """GraphMeta node should contain version '1.0.0'."""
        version = user_db._get_graph_meta_version()
        assert version == GRAPH_SCHEMA_VERSION

    def test_graph_schema_version_in_preferences(self, user_db):
        """user_preferences table should have graph_schema_version column."""
        columns = user_db.fetchall("PRAGMA table_info(user_preferences)")
        column_names = {col['name'] for col in columns}
        assert 'graph_schema_version' in column_names


# ===================================================================
# ETL — Populate Graph from SQLite
# ===================================================================

class TestETL:
    """Tests for ETL population from SQLite data."""

    def test_etl_populates_dimensions(self, seeded_db):
        """Dimensions in SQLite should appear as :Dimension nodes in the graph."""
        result = seeded_db._graph_conn.execute(
            "MATCH (d:Dimension) RETURN d.sqlite_id, d.name ORDER BY d.sqlite_id"
        )
        rows = seeded_db._graph_collect(result)
        ids = [r[0] for r in rows]
        assert 200 in ids
        assert 201 in ids

    def test_etl_populates_subjects_with_hierarchy(self, seeded_db):
        """Subject nodes and :HAS_CHILD edges should exist in the graph."""
        # Check subject nodes
        result = seeded_db._graph_conn.execute(
            "MATCH (s:Subject) RETURN s.sqlite_id, s.name ORDER BY s.sqlite_id"
        )
        rows = seeded_db._graph_collect(result)
        ids = [r[0] for r in rows]
        assert 300 in ids, "Root subject (CardioSystem) missing"
        assert 301 in ids, "Child subject (HeartValves) missing"

        # Check HAS_CHILD edge: 300 -> 301
        result2 = seeded_db._graph_conn.execute(
            "MATCH (p:Subject {sqlite_id: 300})-[:HAS_CHILD]->(c:Subject {sqlite_id: 301}) "
            "RETURN p.sqlite_id, c.sqlite_id"
        )
        edges = seeded_db._graph_collect(result2)
        assert len(edges) == 1, "Expected exactly one HAS_CHILD edge from 300 to 301"

    def test_etl_populates_entries_and_mappings(self, seeded_db):
        """Entry stubs and TAGGED_TO edges should exist in the graph."""
        # Entry node
        result = seeded_db._graph_conn.execute(
            "MATCH (e:Entry {sqlite_id: 500}) RETURN e.sqlite_id"
        )
        rows = seeded_db._graph_collect(result)
        assert len(rows) == 1

        # TAGGED_TO edge
        result2 = seeded_db._graph_conn.execute(
            "MATCH (e:Entry {sqlite_id: 500})-[:TAGGED_TO]->(s:Subject {sqlite_id: 301}) "
            "RETURN e.sqlite_id, s.sqlite_id"
        )
        edges = seeded_db._graph_collect(result2)
        assert len(edges) == 1

    def test_etl_populates_notes_with_links(self, seeded_db):
        """Note stubs and NOTE_LINKED_TO edges should exist in the graph."""
        # Note node
        result = seeded_db._graph_conn.execute(
            "MATCH (n:Note {sqlite_id: 600}) RETURN n.sqlite_id"
        )
        rows = seeded_db._graph_collect(result)
        assert len(rows) == 1

        # NOTE_LINKED_TO edge
        result2 = seeded_db._graph_conn.execute(
            "MATCH (n:Note {sqlite_id: 600})-[:NOTE_LINKED_TO]->(s:Subject {sqlite_id: 301}) "
            "RETURN n.sqlite_id, s.sqlite_id"
        )
        edges = seeded_db._graph_collect(result2)
        assert len(edges) == 1

    def test_etl_idempotent(self, seeded_db):
        """Running _populate_graph_from_sqlite a second time should not create duplicates."""
        # Count nodes before
        result_before = seeded_db._graph_conn.execute(
            "MATCH (s:Subject) RETURN count(s)"
        )
        count_before = seeded_db._graph_collect(result_before)[0][0]

        # Run ETL again
        seeded_db._populate_graph_from_sqlite()

        # Count nodes after
        result_after = seeded_db._graph_conn.execute(
            "MATCH (s:Subject) RETURN count(s)"
        )
        count_after = seeded_db._graph_collect(result_after)[0][0]

        assert count_after == count_before, (
            f"Duplicate subjects created: before={count_before}, after={count_after}"
        )


# ===================================================================
# Failure Handling
# ===================================================================

class TestFailureHandling:
    """Tests for graceful degradation when graph is unavailable."""

    def test_graph_unavailable_graceful(self, master_db, test_user):
        """When real_ladybug is not importable, graph should be disabled but app works."""
        db_path = master_db.ensure_user_database(test_user.id)

        # Patch the import inside _init_graph to raise ImportError
        original_init_graph = UserDatabase._init_graph

        def patched_init_graph(self_inner):
            self_inner._graph_db = None
            self_inner._graph_conn = None
            self_inner._graph_path = None
            # Simulate ImportError — don't set _lbug
            # (the real _init_graph catches ImportError)

        with patch.object(UserDatabase, '_init_graph', patched_init_graph):
            db = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)
            assert db._graph_available is False
            # SQLite operations should still work
            prefs = db.get_preferences()
            assert prefs is not None
            db.close()

    def test_etl_failure_cleans_up(self, master_db, test_user):
        """If ETL fails, the .lbdb file should be deleted and preferences cleared."""
        db_path = master_db.ensure_user_database(test_user.id)

        # First, create a normal db so schema exists
        db = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)
        graph_path = Path(str(db.db_path)).with_suffix('.lbdb')
        db.close()

        # Delete .lbdb and clear pref so next open triggers fresh schema + ETL
        if graph_path.exists():
            if graph_path.is_dir():
                shutil.rmtree(str(graph_path), ignore_errors=True)
            else:
                graph_path.unlink(missing_ok=True)

        # Patch _populate_graph_from_sqlite to raise during ETL
        # The error is caught by _ensure_graph_schema which cleans up
        with patch.object(
            UserDatabase, '_populate_graph_from_sqlite',
            side_effect=RuntimeError("Simulated ETL failure"),
        ):
            db2 = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)
            # Graph should be unavailable after failure cleanup
            assert db2._graph_available is False
            # .lbdb should be cleaned up
            assert not graph_path.exists(), ".lbdb should be deleted after ETL failure"
            db2.close()


# ===================================================================
# Shadow Read Infrastructure
# ===================================================================

class TestShadowReads:
    """Tests for shadow read comparison infrastructure."""

    def test_shadow_compare_match(self, user_db):
        """_shadow_compare should return True for matching results."""
        sqlite_result = [{'id': 1}, {'id': 2}, {'id': 3}]
        graph_result = [[1], [2], [3]]
        result = user_db._shadow_compare(
            "test_method", {"param": "value"}, sqlite_result, graph_result
        )
        assert result is True

    def test_shadow_compare_mismatch(self, user_db, caplog):
        """_shadow_compare should return False and log warning for mismatched results."""
        sqlite_result = [{'id': 1}, {'id': 2}]
        graph_result = [[1], [3]]

        with caplog.at_level(logging.WARNING, logger='wimi.graph.shadow'):
            result = user_db._shadow_compare(
                "test_method", {"param": "value"}, sqlite_result, graph_result
            )

        assert result is False
        # Check that a warning was logged
        assert any("MISMATCH" in record.message for record in caplog.records)

    def test_shadow_reads_enabled_default(self, user_db):
        """Shadow reads should be enabled by default when graph is available."""
        assert user_db._shadow_reads_enabled is True
