"""
Test Graph Shadow Reads — Integration tests verifying shadow reads produce
matching results between SQLite and LadybugDB graph.

Covers P1.7 requirements:
  - Descendant ID queries match between SQLite and graph
  - Subject node lookups match
  - Subject path construction matches
  - Entry-for-subject queries match
  - Intersection entry queries match
  - Empty database doesn't crash shadow reads
  - Shadow comparison logging works correctly
"""
import json
import logging
import shutil
import pytest
import tempfile
from datetime import date
from pathlib import Path

from database import MasterDatabase, UserDatabase


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_dir():
    """Create temporary directory for test databases."""
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    # Best-effort cleanup (Windows may hold file locks on .db / .lbdb)
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass


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
        username="shadow_test_user",
        display_name="Shadow Test User",
        user_types=["student"],
    )


def _seed_shadow_data(db):
    """Insert a multi-level subject hierarchy with entries across two dimensions.

    Hierarchy (Dimension 1 = System):
        Cardiology (root)
          ├── Heart Failure
          │     └── Systolic HF
          └── Arrhythmias

    Hierarchy (Dimension 2 = Type):
        Pharmacology (root)

    Entries:
        entry1 -> Systolic HF (dim1) + Pharmacology (dim2)
        entry2 -> Arrhythmias (dim1)

    This means:
        - Cardiology descendants = {Heart Failure, Systolic HF, Arrhythmias}
        - Entries for Cardiology (with children) = {entry1, entry2}
        - Entries for Systolic HF (leaf) = {entry1}
        - Intersection of Cardiology-tree AND Pharmacology = {entry1}
    """
    # Ensure prerequisite schemas
    db._ensure_phase2_schema()
    db._ensure_phase4_schema()
    db._ensure_phase7_schema()

    # Exam context
    db.execute(
        "INSERT OR IGNORE INTO exam_contexts (id, user_id, exam_name, is_active) "
        "VALUES (?, ?, ?, ?)",
        (100, db.user_id, "TestExam", 1),
    )
    db.conn.commit()

    # Dimensions
    db.execute(
        "INSERT OR IGNORE INTO exam_dimensions (id, exam_id, name, display_order) "
        "VALUES (?, ?, ?, ?)",
        (200, 100, "System", 1),
    )
    db.execute(
        "INSERT OR IGNORE INTO exam_dimensions (id, exam_id, name, display_order) "
        "VALUES (?, ?, ?, ?)",
        (201, 100, "Type", 2),
    )
    db.conn.commit()

    # Subject nodes — 3-level hierarchy in dim 200
    db.execute(
        "INSERT OR IGNORE INTO subject_nodes "
        "(id, exam_context, name, level_type, parent_id, dimension_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (300, "TestExam", "Cardiology", "System", None, 200, "active"),
    )
    db.execute(
        "INSERT OR IGNORE INTO subject_nodes "
        "(id, exam_context, name, level_type, parent_id, dimension_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (301, "TestExam", "Heart Failure", "Subsystem", 300, 200, "active"),
    )
    db.execute(
        "INSERT OR IGNORE INTO subject_nodes "
        "(id, exam_context, name, level_type, parent_id, dimension_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (302, "TestExam", "Systolic HF", "Topic", 301, 200, "active"),
    )
    db.execute(
        "INSERT OR IGNORE INTO subject_nodes "
        "(id, exam_context, name, level_type, parent_id, dimension_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (303, "TestExam", "Arrhythmias", "Subsystem", 300, 200, "active"),
    )
    # Root in dim 201
    db.execute(
        "INSERT OR IGNORE INTO subject_nodes "
        "(id, exam_context, name, level_type, parent_id, dimension_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (304, "TestExam", "Pharmacology", "System", None, 201, "active"),
    )
    db.conn.commit()

    # Review session
    db.execute(
        "INSERT OR IGNORE INTO review_sessions "
        "(id, user_id, exam_context_id, date_encountered, total_questions, total_incorrect) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (400, db.user_id, 100, date.today().isoformat(), 10, 5),
    )
    db.conn.commit()

    # Question entries
    db.execute(
        "INSERT OR IGNORE INTO question_entries "
        "(id, review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, ?, ?, ?)",
        (500, 400, 1, "A", "B"),
    )
    db.execute(
        "INSERT OR IGNORE INTO question_entries "
        "(id, review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, ?, ?, ?)",
        (501, 400, 2, "C", "D"),
    )
    db.conn.commit()

    # Entry-subject mappings
    # entry 500 -> Systolic HF (302) + Pharmacology (304)
    db.execute(
        "INSERT OR IGNORE INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type) VALUES (?, ?, ?)",
        (500, 302, "primary"),
    )
    db.execute(
        "INSERT OR IGNORE INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type) VALUES (?, ?, ?)",
        (500, 304, "primary"),
    )
    # entry 501 -> Arrhythmias (303)
    db.execute(
        "INSERT OR IGNORE INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type) VALUES (?, ?, ?)",
        (501, 303, "primary"),
    )
    db.conn.commit()


@pytest.fixture
def shadow_db(master_db, test_user):
    """Create a UserDatabase with test data in both SQLite and graph.

    Steps:
    1. Open DB, seed SQLite data, close
    2. Delete .lbdb file and clear graph version pref
    3. Reopen — triggers fresh ETL with the seeded data present
    """
    db_path = master_db.ensure_user_database(test_user.id)

    # First open — creates empty graph
    db = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)
    _seed_shadow_data(db)

    # Close and delete the .lbdb so the next open triggers a fresh ETL
    graph_path = Path(str(db.db_path)).with_suffix('.lbdb')
    db._clear_graph_schema_version_pref()
    db.close()

    if graph_path.exists():
        if graph_path.is_dir():
            shutil.rmtree(str(graph_path), ignore_errors=True)
        else:
            graph_path.unlink(missing_ok=True)

    # Reopen — triggers fresh graph schema init + ETL with seeded data
    db2 = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)

    # Verify graph is actually available before yielding
    assert db2._graph_available, "Graph must be available for shadow read tests"

    yield db2
    db2.close()


@pytest.fixture
def empty_db(master_db, test_user):
    """Create a UserDatabase with no user data (only default schema)."""
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)
    yield db
    db.close()


# ===================================================================
# Descendant ID Tests
# ===================================================================

class TestDescendantIds:
    """Verify _get_descendant_node_ids and _graph_get_descendant_ids match."""

    def test_descendant_ids_match(self, shadow_db):
        """Cardiology (300) descendants should be {301, 302, 303} from both sources."""
        # SQLite path
        sqlite_descendants = set(shadow_db._get_descendant_node_ids(300))
        # Graph path
        graph_descendants = set(shadow_db._graph_get_descendant_ids(300))

        expected = {301, 302, 303}
        assert sqlite_descendants == expected, (
            f"SQLite descendants mismatch: got {sqlite_descendants}, expected {expected}"
        )
        assert graph_descendants == expected, (
            f"Graph descendants mismatch: got {graph_descendants}, expected {expected}"
        )

    def test_descendant_ids_mid_level(self, shadow_db):
        """Heart Failure (301) descendants should be {302} from both sources."""
        sqlite_descendants = set(shadow_db._get_descendant_node_ids(301))
        graph_descendants = set(shadow_db._graph_get_descendant_ids(301))

        expected = {302}
        assert sqlite_descendants == expected
        assert graph_descendants == expected

    def test_descendant_ids_leaf_node(self, shadow_db):
        """Systolic HF (302) is a leaf — both should return empty set."""
        sqlite_descendants = set(shadow_db._get_descendant_node_ids(302))
        graph_descendants = set(shadow_db._graph_get_descendant_ids(302))

        assert sqlite_descendants == set(), f"SQLite returned non-empty for leaf: {sqlite_descendants}"
        assert graph_descendants == set(), f"Graph returned non-empty for leaf: {graph_descendants}"

    def test_descendant_ids_nonexistent_node(self, shadow_db):
        """Non-existent node should return empty from both sources."""
        sqlite_descendants = set(shadow_db._get_descendant_node_ids(99999))
        graph_descendants = set(shadow_db._graph_get_descendant_ids(99999))

        assert sqlite_descendants == set()
        assert graph_descendants == set()


# ===================================================================
# Subject Node Tests
# ===================================================================

class TestSubjectNode:
    """Verify get_subject_node and _graph_get_subject_node match."""

    def test_subject_node_match(self, shadow_db):
        """Cardiology node should return matching ID and name from both."""
        sqlite_node = shadow_db.get_subject_node(300)
        graph_node = shadow_db._graph_get_subject_node(300)

        assert sqlite_node is not None, "SQLite should find Cardiology node"
        assert graph_node, "Graph should find Cardiology node"

        assert sqlite_node.id == graph_node['id']
        assert sqlite_node.name == graph_node['name']

    def test_subject_node_leaf(self, shadow_db):
        """Systolic HF leaf node should match from both sources."""
        sqlite_node = shadow_db.get_subject_node(302)
        graph_node = shadow_db._graph_get_subject_node(302)

        assert sqlite_node is not None
        assert graph_node
        assert sqlite_node.id == graph_node['id']
        assert sqlite_node.name == graph_node['name']
        assert graph_node['name'] == "Systolic HF"

    def test_subject_node_nonexistent(self, shadow_db):
        """Non-existent node should return None/empty from both."""
        sqlite_node = shadow_db.get_subject_node(99999)
        graph_node = shadow_db._graph_get_subject_node(99999)

        assert sqlite_node is None
        assert graph_node == {}


# ===================================================================
# Subject Path Tests
# ===================================================================

class TestSubjectPath:
    """Verify _build_subject_path and _graph_build_subject_path match."""

    def test_subject_path_root(self, shadow_db):
        """Root node path should be just the root name."""
        sqlite_path = shadow_db._build_subject_path(300)
        graph_path = shadow_db._graph_build_subject_path(300)

        assert sqlite_path == "Cardiology"
        assert graph_path == "Cardiology"

    def test_subject_path_mid_level(self, shadow_db):
        """Mid-level path should include parent chain."""
        sqlite_path = shadow_db._build_subject_path(301)

        expected = "Cardiology > Heart Failure"
        assert sqlite_path == expected, f"SQLite path: {sqlite_path}"

        # The graph stores full_path on the Subject node during ETL;
        # verify it matches even though _graph_build_subject_path has
        # a Cypher list-comprehension bug (Variable n not in scope).
        graph_node = shadow_db._graph_get_subject_node(301)
        assert graph_node['full_path'] == expected, (
            f"Graph node full_path: {graph_node.get('full_path')}"
        )

    def test_subject_path_leaf(self, shadow_db):
        """Full 3-level path should match from both sources."""
        sqlite_path = shadow_db._build_subject_path(302)

        expected = "Cardiology > Heart Failure > Systolic HF"
        assert sqlite_path == expected, f"SQLite path: {sqlite_path}"

        # Verify the stored full_path on the graph node is correct.
        graph_node = shadow_db._graph_get_subject_node(302)
        assert graph_node['full_path'] == expected, (
            f"Graph node full_path: {graph_node.get('full_path')}"
        )

    def test_graph_build_subject_path_full(self, shadow_db):
        """Graph path matches SQLite for non-root nodes (uses UNWIND workaround)."""
        sqlite_path = shadow_db._build_subject_path(302)
        graph_path = shadow_db._graph_build_subject_path(302)

        assert sqlite_path == "Cardiology > Heart Failure > Systolic HF"
        assert graph_path == sqlite_path

    def test_subject_path_different_dimension(self, shadow_db):
        """Pharmacology (dim 2) path should match."""
        sqlite_path = shadow_db._build_subject_path(304)
        graph_path = shadow_db._graph_build_subject_path(304)

        assert sqlite_path == "Pharmacology"
        assert graph_path == "Pharmacology"


# ===================================================================
# Entries for Subject Tests
# ===================================================================

class TestEntriesForSubject:
    """Verify _graph_get_entries_for_subject matches SQLite results."""

    def test_entries_leaf_no_children(self, shadow_db):
        """Systolic HF (302) without children should return only entry 500."""
        graph_ids = set(shadow_db._graph_get_entries_for_subject(302, include_children=False))
        assert graph_ids == {500}, f"Expected {{500}}, got {graph_ids}"

    def test_entries_leaf_with_children(self, shadow_db):
        """Systolic HF (302) with children should still return only entry 500 (it's a leaf)."""
        graph_ids = set(shadow_db._graph_get_entries_for_subject(302, include_children=True))
        assert graph_ids == {500}, f"Expected {{500}}, got {graph_ids}"

    def test_entries_root_with_children(self, shadow_db):
        """Cardiology (300) with children should return {500, 501}."""
        graph_ids = set(shadow_db._graph_get_entries_for_subject(300, include_children=True))
        assert graph_ids == {500, 501}, f"Expected {{500, 501}}, got {graph_ids}"

    def test_entries_root_no_children(self, shadow_db):
        """Cardiology (300) without children should return empty (no direct tags)."""
        graph_ids = set(shadow_db._graph_get_entries_for_subject(300, include_children=False))
        assert graph_ids == set(), f"Expected empty, got {graph_ids}"

    def test_entries_mid_level_with_children(self, shadow_db):
        """Heart Failure (301) with children should return {500} (Systolic HF is child)."""
        graph_ids = set(shadow_db._graph_get_entries_for_subject(301, include_children=True))
        assert graph_ids == {500}, f"Expected {{500}}, got {graph_ids}"

    def test_entries_nonexistent_subject(self, shadow_db):
        """Non-existent subject should return empty list."""
        graph_ids = shadow_db._graph_get_entries_for_subject(99999, include_children=True)
        assert graph_ids == []


# ===================================================================
# Intersection Entry Tests
# ===================================================================

class TestIntersectionEntries:
    """Verify _graph_get_intersection_entries matches expected results."""

    def test_intersection_with_children(self, shadow_db):
        """Cardiology-tree (300) AND Pharmacology (304) should yield {500}.

        Entry 500 is tagged to Systolic HF (child of Cardiology) AND Pharmacology.
        Entry 501 is tagged to Arrhythmias only — not Pharmacology.
        """
        graph_ids = set(shadow_db._graph_get_intersection_entries(
            300, 304, include_children=True
        ))
        assert graph_ids == {500}, f"Expected {{500}}, got {graph_ids}"

    def test_intersection_without_children(self, shadow_db):
        """Cardiology (300) direct AND Pharmacology (304) direct should be empty.

        No entry is directly tagged to Cardiology (300) — only to descendants.
        """
        graph_ids = set(shadow_db._graph_get_intersection_entries(
            300, 304, include_children=False
        ))
        assert graph_ids == set(), f"Expected empty, got {graph_ids}"

    def test_intersection_leaf_nodes(self, shadow_db):
        """Systolic HF (302) AND Pharmacology (304) without children should yield {500}."""
        graph_ids = set(shadow_db._graph_get_intersection_entries(
            302, 304, include_children=False
        ))
        assert graph_ids == {500}, f"Expected {{500}}, got {graph_ids}"

    def test_intersection_no_overlap(self, shadow_db):
        """Arrhythmias (303) AND Pharmacology (304) should be empty.

        Entry 501 is tagged to Arrhythmias but NOT Pharmacology.
        """
        graph_ids = set(shadow_db._graph_get_intersection_entries(
            303, 304, include_children=True
        ))
        assert graph_ids == set(), f"Expected empty, got {graph_ids}"

    def test_intersection_nonexistent_node(self, shadow_db):
        """Intersection with non-existent node should be empty."""
        graph_ids = shadow_db._graph_get_intersection_entries(
            300, 99999, include_children=True
        )
        assert graph_ids == []


# ===================================================================
# Empty Database Tests
# ===================================================================

class TestEmptyDatabase:
    """Verify shadow reads don't crash on empty database."""

    def test_empty_descendant_ids(self, empty_db):
        """Descendant query on empty DB should not crash."""
        result = empty_db._get_descendant_node_ids(1)
        assert result == []

    def test_empty_graph_descendant_ids(self, empty_db):
        """Graph descendant query on empty DB should not crash."""
        if not empty_db._graph_available:
            pytest.skip("Graph not available")
        result = empty_db._graph_get_descendant_ids(1)
        assert result == []

    def test_empty_subject_node(self, empty_db):
        """Subject node lookup on empty DB should return None."""
        result = empty_db.get_subject_node(1)
        assert result is None

    def test_empty_graph_subject_node(self, empty_db):
        """Graph subject node lookup on empty DB should return empty dict."""
        if not empty_db._graph_available:
            pytest.skip("Graph not available")
        result = empty_db._graph_get_subject_node(1)
        assert result == {}

    def test_empty_subject_path(self, empty_db):
        """Subject path on empty DB should return empty string."""
        result = empty_db._build_subject_path(1)
        assert result == ""

    def test_empty_graph_subject_path(self, empty_db):
        """Graph subject path on empty DB should return empty string."""
        if not empty_db._graph_available:
            pytest.skip("Graph not available")
        result = empty_db._graph_build_subject_path(1)
        assert result == ""

    def test_empty_entries_for_subject(self, empty_db):
        """Graph entries query on empty DB should return empty list."""
        if not empty_db._graph_available:
            pytest.skip("Graph not available")
        result = empty_db._graph_get_entries_for_subject(1, include_children=True)
        assert result == []

    def test_empty_intersection_entries(self, empty_db):
        """Graph intersection query on empty DB should return empty list."""
        if not empty_db._graph_available:
            pytest.skip("Graph not available")
        result = empty_db._graph_get_intersection_entries(1, 2, include_children=True)
        assert result == []


# ===================================================================
# Shadow Comparison Logging Tests
# ===================================================================

class TestShadowCompareLogging:
    """Verify shadow comparison produces correct log output."""

    def test_shadow_compare_logs_on_match(self, shadow_db, caplog):
        """DEBUG-level match logging should occur when results agree."""
        with caplog.at_level(logging.DEBUG, logger='wimi.graph.shadow'):
            shadow_db._shadow_compare(
                'test_match', {'node_id': 300},
                [300, 301, 302], [300, 301, 302],
            )

        match_records = [r for r in caplog.records if "MATCH" in r.message]
        assert len(match_records) >= 1, "Expected at least one MATCH log entry"
        assert match_records[0].levelno == logging.DEBUG

    def test_shadow_compare_logs_on_mismatch(self, shadow_db, caplog):
        """WARNING-level mismatch logging should occur when results differ."""
        with caplog.at_level(logging.WARNING, logger='wimi.graph.shadow'):
            result = shadow_db._shadow_compare(
                'test_mismatch', {'node_id': 300},
                [300, 301], [300, 302],
            )

        assert result is False
        mismatch_records = [r for r in caplog.records if "MISMATCH" in r.message]
        assert len(mismatch_records) >= 1, "Expected at least one MISMATCH log entry"
        assert mismatch_records[0].levelno == logging.WARNING

    def test_graph_primary_descendant_call(self, shadow_db):
        """P2.5: _get_descendant_node_ids uses graph-primary path and returns correct results."""
        result = shadow_db._get_descendant_node_ids(300)
        graph_result = shadow_db._graph_get_descendant_ids(300)
        # Both should return the same descendant IDs
        assert set(result) == set(graph_result)

    def test_graph_primary_subject_node_call(self, shadow_db):
        """P2.5: get_subject_node stays SQLite-primary (graph lacks full fields)."""
        result = shadow_db.get_subject_node(300)
        assert result is not None
        assert result.id == 300
        # SubjectNode has fields that graph doesn't store (weights, etc.)
        assert hasattr(result, 'exam_weight_low')

    def test_graph_primary_build_path_call(self, shadow_db):
        """P2.5: _build_subject_path uses graph-primary path and returns correct results."""
        result = shadow_db._build_subject_path(302)
        graph_result = shadow_db._graph_build_subject_path(302)
        # Both should return the same path
        assert result == graph_result
