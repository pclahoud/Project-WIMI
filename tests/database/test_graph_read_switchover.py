"""
Test Graph Database Phase 2 — Read Switchover and Invariants.

Covers P2.7 requirements:
  - Graph-primary reads return correct results (_get_descendant_node_ids, _build_subject_path)
  - Intersection entries via graph match expected cross-dimension results
  - Fallback to SQLite when graph is unavailable
  - No orphan subjects in graph after mutations
  - No cycles in subject hierarchy
  - All subjects have BELONGS_TO edges when dimensions exist
  - Reconciliation rebuilds graph end-to-end
  - Mutations keep graph consistent (create entry, delete entry)
"""
import json
import logging
import shutil
import pytest
import tempfile
from datetime import date
from pathlib import Path

from database import MasterDatabase, UserDatabase
from database.domains.graph import GRAPH_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_dir():
    """Create temporary directory for test databases."""
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
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
        username="read_switchover_user",
        display_name="Read Switchover Test User",
        user_types=["student"],
    )


def _seed_read_data(db):
    """Insert a multi-level subject hierarchy with entries, notes, and dimensions.

    Hierarchy (Dimension 1 = System, id=200):
        Cardiology (300, root)
          +-- Heart Failure (301)
          |     +-- Systolic HF (302)
          +-- Arrhythmias (303)

    Hierarchy (Dimension 2 = Type, id=201):
        Pharmacology (304, root)

    Entries:
        entry 500 -> Systolic HF (302) + Pharmacology (304)  [cross-dimension]
        entry 501 -> Arrhythmias (303)
        entry 502 -> Heart Failure (301) + Pharmacology (304) [cross-dimension]

    Notes:
        note 600 -> linked to Cardiology (300)
    """
    db._ensure_phase2_schema()
    db._ensure_phase4_schema()
    db._ensure_phase7_schema()
    db._ensure_entry_notes_table()

    # Ensure user_preferences row exists (needed for stale flag tests)
    db.get_preferences()

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

    # Subject nodes
    subjects = [
        (300, "TestExam", "Cardiology",   "System",    None, 200, "active"),
        (301, "TestExam", "Heart Failure", "Subsystem", 300,  200, "active"),
        (302, "TestExam", "Systolic HF",  "Topic",     301,  200, "active"),
        (303, "TestExam", "Arrhythmias",  "Subsystem", 300,  200, "active"),
        (304, "TestExam", "Pharmacology", "System",    None, 201, "active"),
    ]
    for s in subjects:
        db.execute(
            "INSERT OR IGNORE INTO subject_nodes "
            "(id, exam_context, name, level_type, parent_id, dimension_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            s,
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
    for eid, order in [(500, 1), (501, 2), (502, 3)]:
        db.execute(
            "INSERT OR IGNORE INTO question_entries "
            "(id, review_session_id, entry_order, user_answer, correct_answer) "
            "VALUES (?, ?, ?, ?, ?)",
            (eid, 400, order, "A", "B"),
        )
    db.conn.commit()

    # Entry-subject mappings
    mappings = [
        (500, 302, "primary"),   # entry 500 -> Systolic HF
        (500, 304, "primary"),   # entry 500 -> Pharmacology
        (501, 303, "primary"),   # entry 501 -> Arrhythmias
        (502, 301, "primary"),   # entry 502 -> Heart Failure
        (502, 304, "primary"),   # entry 502 -> Pharmacology
    ]
    for m in mappings:
        db.execute(
            "INSERT OR IGNORE INTO entry_subject_mappings "
            "(question_entry_id, subject_node_id, mapping_type) VALUES (?, ?, ?)",
            m,
        )
    db.conn.commit()

    # Entry note linked to Cardiology
    db.execute(
        "INSERT OR IGNORE INTO entry_notes "
        "(id, question_entry_id, content_html, linked_subject_ids, sort_order) "
        "VALUES (?, ?, ?, ?, ?)",
        (600, 500, "<p>Important cardiology concept</p>", json.dumps([300]), 1),
    )
    db.conn.commit()


@pytest.fixture
def read_db(master_db, test_user):
    """UserDatabase with hierarchy, entries, notes, and graph populated.

    Steps:
    1. Open DB, seed SQLite data, close
    2. Delete .lbdb file and clear graph version pref
    3. Reopen — triggers fresh ETL with the seeded data present
    """
    db_path = master_db.ensure_user_database(test_user.id)

    # First open — creates empty graph
    db = UserDatabase(db_path=db_path, user_id=test_user.id, username=test_user.username)
    _seed_read_data(db)

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

    assert db2._graph_available, "Graph must be available for read switchover tests"
    assert db2._graph_read_ready, "Graph must be read-ready for switchover tests"

    yield db2
    db2.close()


# ===================================================================
# Read Switchover Tests
# ===================================================================

class TestDescendantIdsFromGraph:
    """P2.7: _get_descendant_node_ids uses graph-primary path."""

    def test_descendant_ids_from_graph(self, read_db):
        """_get_descendant_node_ids(Cardiology) should return correct descendants via graph."""
        # Call the graph-primary method
        result = read_db._get_descendant_node_ids(300)
        result_set = set(result)

        expected = {301, 302, 303}
        assert result_set == expected, (
            f"_get_descendant_node_ids returned {result_set}, expected {expected}"
        )

        # Confirm the graph method returns the same result
        graph_result = set(read_db._graph_get_descendant_ids(300))
        assert graph_result == expected, (
            f"_graph_get_descendant_ids returned {graph_result}, expected {expected}"
        )

    def test_descendant_ids_mid_level(self, read_db):
        """Heart Failure descendants should be {Systolic HF}."""
        result = set(read_db._get_descendant_node_ids(301))
        assert result == {302}

    def test_descendant_ids_leaf(self, read_db):
        """Leaf node (Systolic HF) should return empty set."""
        result = set(read_db._get_descendant_node_ids(302))
        assert result == set()


class TestSubjectPathFromGraph:
    """P2.7: _build_subject_path uses graph-primary path."""

    def test_subject_path_from_graph(self, read_db):
        """_build_subject_path(Systolic HF) should return full 3-level path."""
        path = read_db._build_subject_path(302)
        assert path == "Cardiology > Heart Failure > Systolic HF", (
            f"Got path: {path}"
        )

    def test_subject_path_root(self, read_db):
        """Root node path should be just the root name."""
        path = read_db._build_subject_path(300)
        assert path == "Cardiology"

    def test_subject_path_mid_level(self, read_db):
        """Mid-level node path should include parent."""
        path = read_db._build_subject_path(301)
        assert path == "Cardiology > Heart Failure"

    def test_subject_path_other_dimension(self, read_db):
        """Pharmacology (dim 2) path should be just its name."""
        path = read_db._build_subject_path(304)
        assert path == "Pharmacology"


class TestIntersectionEntriesFromGraph:
    """P2.7: get_intersection_entries uses graph for cross-dimension queries."""

    def test_intersection_entries_from_graph(self, read_db):
        """Cardiology-tree AND Pharmacology should return entries 500 and 502."""
        # Use the graph-level method directly to verify
        graph_ids = set(read_db._graph_get_intersection_entries(
            300, 304, include_children=True,
        ))
        assert graph_ids == {500, 502}, (
            f"Expected {{500, 502}}, got {graph_ids}"
        )

    def test_intersection_leaf_and_pharmacology(self, read_db):
        """Systolic HF AND Pharmacology should yield {500}."""
        graph_ids = set(read_db._graph_get_intersection_entries(
            302, 304, include_children=False,
        ))
        assert graph_ids == {500}, f"Expected {{500}}, got {graph_ids}"

    def test_intersection_no_overlap(self, read_db):
        """Arrhythmias AND Pharmacology should be empty (no shared entries)."""
        graph_ids = set(read_db._graph_get_intersection_entries(
            303, 304, include_children=True,
        ))
        assert graph_ids == set(), f"Expected empty, got {graph_ids}"


class TestFallbackToSqlite:
    """P2.7: When graph is unavailable, methods fall back to SQLite."""

    def test_fallback_descendant_ids(self, read_db):
        """After closing graph, _get_descendant_node_ids still works via SQLite."""
        # Close graph connection
        read_db._close_graph()
        assert not read_db._graph_available

        # Should still work via SQLite fallback
        result = set(read_db._get_descendant_node_ids(300))
        expected = {301, 302, 303}
        assert result == expected, (
            f"SQLite fallback returned {result}, expected {expected}"
        )

    def test_fallback_subject_path(self, read_db):
        """After closing graph, _build_subject_path still works via SQLite."""
        read_db._close_graph()
        assert not read_db._graph_available

        path = read_db._build_subject_path(302)
        assert path == "Cardiology > Heart Failure > Systolic HF", (
            f"SQLite fallback path: {path}"
        )

    def test_fallback_descendant_ids_leaf(self, read_db):
        """Leaf node fallback returns empty."""
        read_db._close_graph()
        result = set(read_db._get_descendant_node_ids(302))
        assert result == set()


# ===================================================================
# Invariant Tests
# ===================================================================

class TestNoOrphanSubjects:
    """P2.7: Every Subject node must be reachable from an ExamContext."""

    def test_no_orphan_subjects(self, read_db):
        """After ETL, all subjects are reachable from ExamContext via ROOT_OF or HAS_CHILD."""
        # Count subjects NOT reachable from any ExamContext
        result = read_db._graph_execute(
            "MATCH (s:Subject) "
            "WHERE NOT EXISTS { "
            "  MATCH (ec:ExamContext)-[:ROOT_OF]->(root:Subject)-[:HAS_CHILD*0..20]->(s) "
            "} "
            "RETURN count(s)"
        )
        rows = read_db._graph_collect(result)
        orphan_count = rows[0][0] if rows else -1
        assert orphan_count == 0, (
            f"Found {orphan_count} orphan Subject nodes not reachable from any ExamContext"
        )

    def test_no_orphans_after_creating_subjects(self, read_db):
        """After creating new subjects via dual-write, no orphans exist."""
        # Create a new root subject via the API (triggers dual-write)
        new_root = read_db.create_subject_node(
            exam_context='TestExam',
            name='Neurology',
            level_type='System',
            parent_id=None,
            sort_order=10,
            dimension_id=200,
        )
        # Create a child
        new_child = read_db.create_subject_node(
            exam_context='TestExam',
            name='Stroke',
            level_type='Subsystem',
            parent_id=new_root.id,
            sort_order=1,
            dimension_id=200,
        )

        # Verify no orphans
        result = read_db._graph_execute(
            "MATCH (s:Subject) "
            "WHERE NOT EXISTS { "
            "  MATCH (ec:ExamContext)-[:ROOT_OF]->(root:Subject)-[:HAS_CHILD*0..20]->(s) "
            "} "
            "RETURN count(s)"
        )
        rows = read_db._graph_collect(result)
        assert rows[0][0] == 0, "Found orphan subjects after creating new nodes"


class TestNoCyclesInHierarchy:
    """P2.7: No subject should be its own ancestor."""

    def test_no_cycles_in_hierarchy(self, read_db):
        """For each subject with children, descendants must not include self."""
        # Get all subjects that have children
        result = read_db._graph_execute(
            "MATCH (p:Subject)-[:HAS_CHILD]->(c:Subject) "
            "RETURN DISTINCT p.sqlite_id"
        )
        rows = read_db._graph_collect(result)

        for row in rows:
            parent_id = row[0]
            descendants = read_db._graph_get_descendant_ids(parent_id)
            assert parent_id not in descendants, (
                f"Cycle detected: Subject {parent_id} is its own descendant"
            )

    def test_no_self_referencing_has_child(self, read_db):
        """No subject should have a HAS_CHILD edge to itself."""
        result = read_db._graph_execute(
            "MATCH (s:Subject)-[:HAS_CHILD]->(s) RETURN count(s)"
        )
        rows = read_db._graph_collect(result)
        assert rows[0][0] == 0, "Found self-referencing HAS_CHILD edge"


class TestAllSubjectsHaveBelongsTo:
    """P2.7: Every Subject must have exactly one BELONGS_TO edge when dimensions exist."""

    def test_all_subjects_have_belongs_to(self, read_db):
        """Every Subject should have a BELONGS_TO edge to a Dimension."""
        # Count subjects without BELONGS_TO
        result = read_db._graph_execute(
            "MATCH (s:Subject) "
            "WHERE NOT (s)-[:BELONGS_TO]->(:Dimension) "
            "RETURN count(s)"
        )
        rows = read_db._graph_collect(result)
        unlinked_count = rows[0][0] if rows else -1
        assert unlinked_count == 0, (
            f"Found {unlinked_count} Subject nodes without a BELONGS_TO edge"
        )

    def test_belongs_to_points_to_correct_dimension(self, read_db):
        """Cardiology (dim 200) BELONGS_TO should point to System dimension."""
        result = read_db._graph_execute(
            "MATCH (s:Subject {sqlite_id: 300})-[:BELONGS_TO]->(d:Dimension) "
            "RETURN d.sqlite_id, d.name",
        )
        rows = read_db._graph_collect(result)
        assert len(rows) == 1
        assert rows[0][0] == 200
        assert rows[0][1] == "System"

    def test_pharmacology_belongs_to_type_dimension(self, read_db):
        """Pharmacology (dim 201) BELONGS_TO should point to Type dimension."""
        result = read_db._graph_execute(
            "MATCH (s:Subject {sqlite_id: 304})-[:BELONGS_TO]->(d:Dimension) "
            "RETURN d.sqlite_id, d.name",
        )
        rows = read_db._graph_collect(result)
        assert len(rows) == 1
        assert rows[0][0] == 201
        assert rows[0][1] == "Type"


class TestReconciliationEndToEnd:
    """P2.7: Graph reconciliation rebuilds correctly after stale flag."""

    def test_reconciliation_end_to_end(self, read_db):
        """Mark graph stale, close and reopen DB, verify graph rebuilt with all data."""
        db_path = read_db.db_path
        user_id = read_db.user_id
        username = getattr(read_db, 'username', 'read_switchover_user')

        # Verify initial data is present
        initial_descendants = set(read_db._graph_get_descendant_ids(300))
        assert initial_descendants == {301, 302, 303}

        # Mark graph stale
        read_db._mark_graph_stale()
        assert read_db._is_graph_stale() is True

        # Close the database
        read_db.close()

        # Reopen — should trigger reconciliation (stale flag detected)
        db2 = UserDatabase(db_path=db_path, user_id=user_id, username=username)

        try:
            assert db2._graph_available, "Graph should be available after reconciliation"

            # Verify all subjects are present
            descendants = set(db2._graph_get_descendant_ids(300))
            assert descendants == {301, 302, 303}, (
                f"After reconciliation, descendants = {descendants}"
            )

            # Verify entries are present
            entry_ids = set(db2._graph_get_entries_for_subject(300, include_children=True))
            assert 500 in entry_ids
            assert 501 in entry_ids
            assert 502 in entry_ids

            # Verify note is present
            result = db2._graph_execute(
                "MATCH (n:Note {sqlite_id: 600}) RETURN n.sqlite_id",
            )
            rows = db2._graph_collect(result)
            assert len(rows) == 1, "Note 600 should exist after reconciliation"

            # Verify note link
            result2 = db2._graph_execute(
                "MATCH (n:Note {sqlite_id: 600})-[:NOTE_LINKED_TO]->(s:Subject {sqlite_id: 300}) "
                "RETURN count(*)",
            )
            rows2 = db2._graph_collect(result2)
            assert rows2[0][0] == 1, "Note 600 should link to Cardiology after reconciliation"

            # Stale flag should be cleared
            assert db2._is_graph_stale() is False

        finally:
            db2.close()


class TestMutationsKeepGraphConsistent:
    """P2.7: After mutations, graph stays consistent with SQLite."""

    def test_create_and_delete_entry_consistency(self, read_db):
        """Create entry tagged to a subject, delete it, verify TAGGED_TO edge gone."""
        # Create a review session and entry via the API
        session = read_db.create_review_session(
            exam_context_id=100,
            date_encountered=date.today(),
            total_questions=5,
            total_incorrect=2,
        )
        entry = read_db.create_question_entry(
            review_session_id=session.id,
            user_answer='X',
            correct_answer='Y',
            primary_subject_ids=[302],  # Systolic HF
        )
        entry_id = entry.id

        # Verify entry exists in graph with TAGGED_TO edge
        result = read_db._graph_execute(
            "MATCH (e:Entry {sqlite_id: $eid})-[:TAGGED_TO]->(s:Subject {sqlite_id: 302}) "
            "RETURN count(*)",
            {"eid": entry_id},
        )
        rows = read_db._graph_collect(result)
        assert rows[0][0] == 1, "TAGGED_TO edge should exist after creation"

        # Delete the entry
        read_db.delete_question_entry(entry_id)

        # Entry node and TAGGED_TO edge should be gone
        result2 = read_db._graph_execute(
            "MATCH (e:Entry {sqlite_id: $eid}) RETURN count(*)",
            {"eid": entry_id},
        )
        rows2 = read_db._graph_collect(result2)
        assert rows2[0][0] == 0, "Entry node should be gone after deletion"

        result3 = read_db._graph_execute(
            "MATCH (e:Entry {sqlite_id: $eid})-[:TAGGED_TO]->() RETURN count(*)",
            {"eid": entry_id},
        )
        rows3 = read_db._graph_collect(result3)
        assert rows3[0][0] == 0, "TAGGED_TO edges should be gone after entry deletion"

    def test_create_note_and_delete_consistency(self, read_db):
        """Create note linked to subject, delete it, verify NOTE_LINKED_TO edge gone."""
        note = read_db.add_entry_note(
            entry_id=500,
            content_html='<p>Test note for consistency</p>',
            linked_subject_ids=[303],  # Arrhythmias
        )
        note_id = note.id

        # Verify note exists in graph
        result = read_db._graph_execute(
            "MATCH (n:Note {sqlite_id: $nid})-[:NOTE_LINKED_TO]->(s:Subject {sqlite_id: 303}) "
            "RETURN count(*)",
            {"nid": note_id},
        )
        rows = read_db._graph_collect(result)
        assert rows[0][0] == 1, "NOTE_LINKED_TO edge should exist after creation"

        # Delete the note
        read_db.delete_entry_note(note_id)

        # Note node and edge should be gone
        result2 = read_db._graph_execute(
            "MATCH (n:Note {sqlite_id: $nid}) RETURN count(*)",
            {"nid": note_id},
        )
        rows2 = read_db._graph_collect(result2)
        assert rows2[0][0] == 0, "Note node should be gone after deletion"

    def test_subject_creation_updates_graph_descendants(self, read_db):
        """Creating a new child subject should make it appear in graph descendants."""
        # Verify initial descendants of Cardiology
        before = set(read_db._graph_get_descendant_ids(300))
        assert before == {301, 302, 303}

        # Create a new child of Cardiology via dual-write API
        new_child = read_db.create_subject_node(
            exam_context='TestExam',
            name='Valvular Disease',
            level_type='Subsystem',
            parent_id=300,
            sort_order=5,
            dimension_id=200,
        )

        # Descendants should now include the new child
        after = set(read_db._graph_get_descendant_ids(300))
        assert new_child.id in after, (
            f"New child {new_child.id} not found in descendants: {after}"
        )
        assert after == {301, 302, 303, new_child.id}
