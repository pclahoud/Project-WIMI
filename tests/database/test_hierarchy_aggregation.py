"""
Tests for Hierarchy Aggregation Helper Methods

Tests the _build_descendant_cte() and _aggregate_hierarchy_counts() methods
used for aggregating analytics counts up through the subject node hierarchy.
"""

import pytest
from database.user_db import UserDatabase


@pytest.fixture
def db_with_hierarchy(tmp_path):
    """Create a database with a multi-level subject hierarchy for testing."""
    db_path = tmp_path / "test_hierarchy.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")

    # Create exam context
    exam = db.create_exam_context(
        exam_name="Hierarchy Test Exam",
        exam_description="Test exam for hierarchy aggregation",
        hierarchy_levels=["System", "Subsystem", "Topic", "Subtopic"]
    )

    # Create a multi-level hierarchy:
    # Cardiovascular (System)
    # ├── Heart (Subsystem)
    # │   ├── Valves (Topic)
    # │   │   ├── Mitral (Subtopic)
    # │   │   └── Aortic (Subtopic)
    # │   └── Chambers (Topic)
    # │       └── Left Ventricle (Subtopic)
    # └── Blood Vessels (Subsystem)
    #     ├── Arteries (Topic)
    #     └── Veins (Topic)

    cardiovascular = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Cardiovascular",
        level_type="System"
    )

    heart = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Heart",
        level_type="Subsystem",
        parent_id=cardiovascular.id
    )

    valves = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Valves",
        level_type="Topic",
        parent_id=heart.id
    )

    mitral = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Mitral",
        level_type="Subtopic",
        parent_id=valves.id
    )

    aortic = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Aortic",
        level_type="Subtopic",
        parent_id=valves.id
    )

    chambers = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Chambers",
        level_type="Topic",
        parent_id=heart.id
    )

    left_ventricle = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Left Ventricle",
        level_type="Subtopic",
        parent_id=chambers.id
    )

    blood_vessels = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Blood Vessels",
        level_type="Subsystem",
        parent_id=cardiovascular.id
    )

    arteries = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Arteries",
        level_type="Topic",
        parent_id=blood_vessels.id
    )

    veins = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Veins",
        level_type="Topic",
        parent_id=blood_vessels.id
    )

    # Create a separate root for testing multiple roots
    respiratory = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Respiratory",
        level_type="System"
    )

    lungs = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Lungs",
        level_type="Subsystem",
        parent_id=respiratory.id
    )

    return {
        'db': db,
        'exam': exam,
        'nodes': {
            'cardiovascular': cardiovascular,
            'heart': heart,
            'valves': valves,
            'mitral': mitral,
            'aortic': aortic,
            'chambers': chambers,
            'left_ventricle': left_ventricle,
            'blood_vessels': blood_vessels,
            'arteries': arteries,
            'veins': veins,
            'respiratory': respiratory,
            'lungs': lungs,
        }
    }


class TestAggregateHierarchyCounts:
    """Tests for the _aggregate_hierarchy_counts() helper method."""

    def test_simple_parent_child(self, db_with_hierarchy):
        """Test basic parent-child aggregation.

        Polyhierarchy migration: ``_aggregate_hierarchy_counts`` now
        consults ``subject_edges`` for any node whose ID matches an
        edge row in the DB; otherwise it falls back to the per-row
        ``parent_id`` field. We use synthetic IDs >= 1000 so they do
        not collide with real ``subject_nodes`` rows in the fixture.
        """
        db = db_with_hierarchy['db']

        nodes = [
            {'id': 1001, 'parent_id': None, 'direct_count': 5},
            {'id': 1002, 'parent_id': 1001, 'direct_count': 10},
            {'id': 1003, 'parent_id': 1001, 'direct_count': 15},
        ]

        result = db._aggregate_hierarchy_counts(nodes)

        assert result[1001] == 30  # 5 + 10 + 15
        assert result[1002] == 10  # leaf node
        assert result[1003] == 15  # leaf node

    def test_deep_hierarchy(self, db_with_hierarchy):
        """Test multi-level aggregation (4 levels deep).

        Synthetic IDs offset to avoid collisions with real DB rows.
        """
        db = db_with_hierarchy['db']

        nodes = [
            {'id': 1001, 'parent_id': None, 'direct_count': 1},   # root (level 0)
            {'id': 1002, 'parent_id': 1001, 'direct_count': 2},   # level 1
            {'id': 1003, 'parent_id': 1002, 'direct_count': 3},   # level 2
            {'id': 1004, 'parent_id': 1003, 'direct_count': 4},   # level 3 (leaf)
        ]

        result = db._aggregate_hierarchy_counts(nodes)

        assert result[1004] == 4       # leaf: just its own count
        assert result[1003] == 7       # 3 + 4
        assert result[1002] == 9       # 2 + 3 + 4
        assert result[1001] == 10      # 1 + 2 + 3 + 4

    def test_wide_hierarchy(self, db_with_hierarchy):
        """Test node with many children.

        Synthetic IDs offset to avoid collisions with real DB rows.
        """
        db = db_with_hierarchy['db']

        nodes = [
            {'id': 1001, 'parent_id': None, 'direct_count': 0},
        ] + [
            {'id': i, 'parent_id': 1001, 'direct_count': 1} for i in range(1002, 1052)
        ]

        result = db._aggregate_hierarchy_counts(nodes)

        assert result[1001] == 50  # 0 + 50 children with 1 each
        for i in range(1002, 1052):
            assert result[i] == 1  # each child is a leaf

    def test_empty_input(self, db_with_hierarchy):
        """Test with empty node list."""
        db = db_with_hierarchy['db']

        result = db._aggregate_hierarchy_counts([])

        assert result == {}

    def test_single_node(self, db_with_hierarchy):
        """Test with a single root node.

        Synthetic ID offset to avoid collision with real DB rows.
        """
        db = db_with_hierarchy['db']

        nodes = [
            {'id': 1001, 'parent_id': None, 'direct_count': 42},
        ]

        result = db._aggregate_hierarchy_counts(nodes)

        assert result[1001] == 42

    def test_multiple_roots(self, db_with_hierarchy):
        """Test with multiple root nodes (no parent).

        Synthetic IDs offset to avoid collisions with real DB rows.
        """
        db = db_with_hierarchy['db']

        nodes = [
            {'id': 1001, 'parent_id': None, 'direct_count': 10},
            {'id': 1002, 'parent_id': None, 'direct_count': 20},
            {'id': 1003, 'parent_id': 1001, 'direct_count': 5},
            {'id': 1004, 'parent_id': 1002, 'direct_count': 8},
        ]

        result = db._aggregate_hierarchy_counts(nodes)

        assert result[1001] == 15  # 10 + 5
        assert result[1002] == 28  # 20 + 8
        assert result[1003] == 5   # leaf
        assert result[1004] == 8   # leaf

    def test_custom_count_field(self, db_with_hierarchy):
        """Test with custom count field name."""
        db = db_with_hierarchy['db']

        nodes = [
            {'id': 1001, 'parent_id': None, 'entry_count': 5},
            {'id': 1002, 'parent_id': 1001, 'entry_count': 10},
        ]

        result = db._aggregate_hierarchy_counts(nodes, count_field='entry_count')

        assert result[1001] == 15
        assert result[1002] == 10

    def test_zero_counts(self, db_with_hierarchy):
        """Test nodes with zero direct counts still aggregate children."""
        db = db_with_hierarchy['db']

        nodes = [
            {'id': 1001, 'parent_id': None, 'direct_count': 0},
            {'id': 1002, 'parent_id': 1001, 'direct_count': 0},
            {'id': 1003, 'parent_id': 1002, 'direct_count': 10},
        ]

        result = db._aggregate_hierarchy_counts(nodes)

        assert result[1003] == 10
        assert result[1002] == 10  # 0 + 10
        assert result[1001] == 10  # 0 + 0 + 10

    def test_none_counts_treated_as_zero(self, db_with_hierarchy):
        """Test that None counts are treated as 0."""
        db = db_with_hierarchy['db']

        nodes = [
            {'id': 1001, 'parent_id': None, 'direct_count': None},
            {'id': 1002, 'parent_id': 1001, 'direct_count': 5},
        ]

        result = db._aggregate_hierarchy_counts(nodes)

        assert result[1001] == 5  # None + 5 = 5
        assert result[1002] == 5

    def test_realistic_medical_hierarchy(self, db_with_hierarchy):
        """Test with a realistic medical subject hierarchy structure.

        Synthetic IDs offset to avoid collisions with real DB rows.
        """
        db = db_with_hierarchy['db']

        # Simulating:
        # Cardiovascular (0 direct) -> 45 total
        # ├── Heart (2 direct) -> 30 total
        # │   ├── Valves (0 direct) -> 18 total
        # │   │   ├── Mitral (10 direct) -> 10
        # │   │   └── Aortic (8 direct) -> 8
        # │   └── Chambers (0 direct) -> 10 total
        # │       └── Left Ventricle (10 direct) -> 10
        # └── Blood Vessels (3 direct) -> 13 total
        #     ├── Arteries (5 direct) -> 5
        #     └── Veins (5 direct) -> 5

        nodes = [
            {'id': 1001, 'parent_id': None, 'direct_count': 0},   # Cardiovascular
            {'id': 1002, 'parent_id': 1001, 'direct_count': 2},   # Heart
            {'id': 1003, 'parent_id': 1002, 'direct_count': 0},   # Valves
            {'id': 1004, 'parent_id': 1003, 'direct_count': 10},  # Mitral
            {'id': 1005, 'parent_id': 1003, 'direct_count': 8},   # Aortic
            {'id': 1006, 'parent_id': 1002, 'direct_count': 0},   # Chambers
            {'id': 1007, 'parent_id': 1006, 'direct_count': 10},  # Left Ventricle
            {'id': 1008, 'parent_id': 1001, 'direct_count': 3},   # Blood Vessels
            {'id': 1009, 'parent_id': 1008, 'direct_count': 5},   # Arteries
            {'id': 1010, 'parent_id': 1008, 'direct_count': 5},   # Veins
        ]

        result = db._aggregate_hierarchy_counts(nodes)

        # Leaf nodes
        assert result[1004] == 10   # Mitral
        assert result[1005] == 8    # Aortic
        assert result[1007] == 10   # Left Ventricle
        assert result[1009] == 5    # Arteries
        assert result[1010] == 5    # Veins

        # Mid-level nodes
        assert result[1003] == 18   # Valves: 0 + 10 + 8
        assert result[1006] == 10   # Chambers: 0 + 10
        assert result[1008] == 13   # Blood Vessels: 3 + 5 + 5

        # Higher level
        assert result[1002] == 30   # Heart: 2 + 18 + 10

        # Root
        assert result[1001] == 43   # Cardiovascular: 0 + 30 + 13


class TestBuildDescendantCte:
    """Tests for the _build_descendant_cte() helper method."""

    def test_cte_string_format(self, db_with_hierarchy):
        """Test that CTE returns properly formatted SQL string.

        Polyhierarchy migration: the CTE now joins through
        ``subject_edges`` (the polyhierarchy junction table) rather
        than walking ``subject_nodes.parent_id``. We use ``UNION``
        rather than ``UNION ALL`` so accidental data cycles do not
        cause infinite recursion.
        """
        db = db_with_hierarchy['db']

        cte = db._build_descendant_cte(1)

        assert 'WITH RECURSIVE descendants AS' in cte
        assert 'SELECT id FROM subject_nodes WHERE id = 1' in cte
        # Edge-based traversal (subject_edges junction).
        assert 'subject_edges' in cte
        assert 'se.parent_id = d.id' in cte
        # UNION (not UNION ALL) for cycle defense.
        assert 'UNION\n' in cte or 'UNION ' in cte
        assert 'UNION ALL' not in cte

    def test_cte_finds_all_descendants(self, db_with_hierarchy):
        """Test that CTE query finds all descendants in database."""
        db = db_with_hierarchy['db']
        nodes = db_with_hierarchy['nodes']

        # Get descendants of Cardiovascular
        cte = db._build_descendant_cte(nodes['cardiovascular'].id)
        query = f"{cte} SELECT id FROM descendants ORDER BY id"

        cursor = db.conn.execute(query)
        result_ids = [row[0] for row in cursor.fetchall()]

        # Should include cardiovascular itself and all descendants
        expected_ids = [
            nodes['cardiovascular'].id,
            nodes['heart'].id,
            nodes['valves'].id,
            nodes['mitral'].id,
            nodes['aortic'].id,
            nodes['chambers'].id,
            nodes['left_ventricle'].id,
            nodes['blood_vessels'].id,
            nodes['arteries'].id,
            nodes['veins'].id,
        ]

        assert sorted(result_ids) == sorted(expected_ids)

    def test_cte_leaf_node_returns_only_itself(self, db_with_hierarchy):
        """Test that CTE on leaf node returns only that node."""
        db = db_with_hierarchy['db']
        nodes = db_with_hierarchy['nodes']

        # Mitral is a leaf node
        cte = db._build_descendant_cte(nodes['mitral'].id)
        query = f"{cte} SELECT id FROM descendants"

        cursor = db.conn.execute(query)
        result_ids = [row[0] for row in cursor.fetchall()]

        assert result_ids == [nodes['mitral'].id]

    def test_cte_mid_level_node(self, db_with_hierarchy):
        """Test CTE on a mid-level node."""
        db = db_with_hierarchy['db']
        nodes = db_with_hierarchy['nodes']

        # Heart is mid-level with 2 children that have children
        cte = db._build_descendant_cte(nodes['heart'].id)
        query = f"{cte} SELECT id FROM descendants"

        cursor = db.conn.execute(query)
        result_ids = [row[0] for row in cursor.fetchall()]

        expected_ids = [
            nodes['heart'].id,
            nodes['valves'].id,
            nodes['mitral'].id,
            nodes['aortic'].id,
            nodes['chambers'].id,
            nodes['left_ventricle'].id,
        ]

        assert sorted(result_ids) == sorted(expected_ids)

    def test_cte_counts_entries_in_subtree(self, db_with_hierarchy):
        """Integration test: use CTE to count entries across a subtree."""
        db = db_with_hierarchy['db']
        nodes = db_with_hierarchy['nodes']
        exam = db_with_hierarchy['exam']

        # Create a review session
        session = db.create_review_session(
            exam_context_id=exam.id,
            total_questions=10,
            total_incorrect=5,
            session_name="Test Session"
        )

        # Create entries and map them to leaf nodes
        # 3 entries tagged to Mitral
        for i in range(3):
            entry = db.create_question_entry(
                review_session_id=session.id,
                user_answer=f"Answer {i}",
                correct_answer="Correct",
                perceived_difficulty=3,
                reflection=f"Mitral entry {i}"
            )
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, nodes['mitral'].id))

        # 2 entries tagged to Aortic
        for i in range(2):
            entry = db.create_question_entry(
                review_session_id=session.id,
                user_answer=f"Answer {i}",
                correct_answer="Correct",
                perceived_difficulty=3,
                reflection=f"Aortic entry {i}"
            )
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, nodes['aortic'].id))

        db.conn.commit()

        # Now use CTE to count entries in Cardiovascular subtree
        cte = db._build_descendant_cte(nodes['cardiovascular'].id)
        query = f"""
            {cte}
            SELECT COUNT(DISTINCT esm.question_entry_id) as total
            FROM entry_subject_mappings esm
            WHERE esm.subject_node_id IN (SELECT id FROM descendants)
        """

        cursor = db.conn.execute(query)
        total = cursor.fetchone()[0]

        assert total == 5  # 3 Mitral + 2 Aortic

        # Also verify Heart subtree
        cte_heart = db._build_descendant_cte(nodes['heart'].id)
        query_heart = f"""
            {cte_heart}
            SELECT COUNT(DISTINCT esm.question_entry_id) as total
            FROM entry_subject_mappings esm
            WHERE esm.subject_node_id IN (SELECT id FROM descendants)
        """

        cursor = db.conn.execute(query_heart)
        total_heart = cursor.fetchone()[0]

        assert total_heart == 5  # Same, since all entries are under Heart

        # Verify Valves subtree
        cte_valves = db._build_descendant_cte(nodes['valves'].id)
        query_valves = f"""
            {cte_valves}
            SELECT COUNT(DISTINCT esm.question_entry_id) as total
            FROM entry_subject_mappings esm
            WHERE esm.subject_node_id IN (SELECT id FROM descendants)
        """

        cursor = db.conn.execute(query_valves)
        total_valves = cursor.fetchone()[0]

        assert total_valves == 5  # All entries are under Valves

    def test_cte_does_not_cross_trees(self, db_with_hierarchy):
        """Test that CTE only finds descendants, not siblings or cousins."""
        db = db_with_hierarchy['db']
        nodes = db_with_hierarchy['nodes']

        # Blood Vessels subtree should NOT include Heart or its children
        cte = db._build_descendant_cte(nodes['blood_vessels'].id)
        query = f"{cte} SELECT id FROM descendants"

        cursor = db.conn.execute(query)
        result_ids = [row[0] for row in cursor.fetchall()]

        expected_ids = [
            nodes['blood_vessels'].id,
            nodes['arteries'].id,
            nodes['veins'].id,
        ]

        assert sorted(result_ids) == sorted(expected_ids)

        # Should NOT include Heart's children
        assert nodes['heart'].id not in result_ids
        assert nodes['valves'].id not in result_ids
        assert nodes['mitral'].id not in result_ids


class TestIntegrationAggregationWithDatabase:
    """Integration tests combining both helpers with real database queries."""

    def test_full_aggregation_workflow(self, db_with_hierarchy):
        """Test the complete workflow: fetch direct counts, then aggregate."""
        db = db_with_hierarchy['db']
        nodes = db_with_hierarchy['nodes']
        exam = db_with_hierarchy['exam']

        # Create session and entries
        session = db.create_review_session(
            exam_context_id=exam.id,
            total_questions=20,
            total_incorrect=10,
            session_name="Integration Test"
        )

        # Create entries at various levels
        entry_counts = {
            'cardiovascular': 1,  # Direct to root
            'heart': 2,
            'valves': 0,
            'mitral': 5,
            'aortic': 3,
            'chambers': 1,
            'left_ventricle': 4,
            'blood_vessels': 2,
            'arteries': 3,
            'veins': 2,
        }

        for node_name, count in entry_counts.items():
            node = nodes[node_name]
            for i in range(count):
                entry = db.create_question_entry(
                    review_session_id=session.id,
                    user_answer=f"Answer",
                    correct_answer="Correct",
                    perceived_difficulty=3,
                    reflection=f"{node_name} entry {i}"
                )
                db.conn.execute("""
                    INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                    VALUES (?, ?, 'primary')
                """, (entry.id, node.id))

        db.conn.commit()

        # Step 1: Query direct counts for all nodes
        cursor = db.conn.execute("""
            SELECT
                sn.id,
                sn.parent_id,
                COUNT(DISTINCT esm.question_entry_id) as direct_count
            FROM subject_nodes sn
            LEFT JOIN entry_subject_mappings esm ON esm.subject_node_id = sn.id
            WHERE sn.exam_context = ?
            AND sn.status = 'active'
            GROUP BY sn.id, sn.parent_id
        """, (exam.exam_name,))

        nodes_with_counts = [
            {'id': row[0], 'parent_id': row[1], 'direct_count': row[2]}
            for row in cursor.fetchall()
        ]

        # Step 2: Aggregate using helper
        totals = db._aggregate_hierarchy_counts(nodes_with_counts)

        # Verify totals
        # Mitral: 5, Aortic: 3 -> Valves: 0+5+3=8
        assert totals[nodes['mitral'].id] == 5
        assert totals[nodes['aortic'].id] == 3
        assert totals[nodes['valves'].id] == 8

        # Left Ventricle: 4 -> Chambers: 1+4=5
        assert totals[nodes['left_ventricle'].id] == 4
        assert totals[nodes['chambers'].id] == 5

        # Heart: 2 + Valves(8) + Chambers(5) = 15
        assert totals[nodes['heart'].id] == 15

        # Arteries: 3, Veins: 2 -> Blood Vessels: 2+3+2=7
        assert totals[nodes['arteries'].id] == 3
        assert totals[nodes['veins'].id] == 2
        assert totals[nodes['blood_vessels'].id] == 7

        # Cardiovascular: 1 + Heart(15) + Blood Vessels(7) = 23
        assert totals[nodes['cardiovascular'].id] == 23


class TestGetDimensionPerformanceAggregation:
    """Tests for get_dimension_performance() with hierarchy aggregation."""

    @pytest.fixture
    def db_with_dimension_hierarchy(self, tmp_path):
        """Create a database with a dimension hierarchy for testing."""
        db_path = tmp_path / "test_dim_perf.db"
        db = UserDatabase(str(db_path), user_id=1, username="testuser")

        # Create exam context
        exam = db.create_exam_context(
            exam_name="Dimension Test Exam",
            exam_description="Test exam for dimension performance",
            hierarchy_levels=["System", "Subsystem", "Topic"]
        )

        # Create a dimension
        dim_id = db.create_dimension(
            exam_id=exam.id,
            name="System",
            description="Body system",
            display_order=1
        )

        # Create hierarchy:
        # Cardiovascular (System)
        # ├── Heart (Subsystem)
        # │   └── Valves (Topic)
        # └── Blood Vessels (Subsystem)

        cardiovascular = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Cardiovascular",
            level_type="System",
            dimension_id=dim_id
        )

        heart = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Heart",
            level_type="Subsystem",
            parent_id=cardiovascular.id,
            dimension_id=dim_id
        )

        valves = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Valves",
            level_type="Topic",
            parent_id=heart.id,
            dimension_id=dim_id
        )

        blood_vessels = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Blood Vessels",
            level_type="Subsystem",
            parent_id=cardiovascular.id,
            dimension_id=dim_id
        )

        # Create session and entries
        session = db.create_review_session(
            exam_context_id=exam.id,
            total_questions=10,
            total_incorrect=5,
            session_name="Test Session"
        )

        # Create entries: 3 to Valves (leaf), 2 to Blood Vessels
        for i in range(3):
            entry = db.create_question_entry(
                review_session_id=session.id,
                user_answer="Answer",
                correct_answer="Correct",
                perceived_difficulty=3,
                reflection=f"Valves entry {i}"
            )
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, valves.id))

        for i in range(2):
            entry = db.create_question_entry(
                review_session_id=session.id,
                user_answer="Answer",
                correct_answer="Correct",
                perceived_difficulty=4,
                reflection=f"Blood Vessels entry {i}"
            )
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, blood_vessels.id))

        db.conn.commit()

        return {
            'db': db,
            'exam': exam,
            'dimension_id': dim_id,
            'nodes': {
                'cardiovascular': cardiovascular,
                'heart': heart,
                'valves': valves,
                'blood_vessels': blood_vessels
            }
        }

    def test_dimension_performance_with_aggregation(self, db_with_dimension_hierarchy):
        """Test that parent nodes aggregate child counts."""
        data = db_with_dimension_hierarchy
        db = data['db']
        exam = data['exam']
        dim_id = data['dimension_id']
        nodes = data['nodes']

        result = db.get_dimension_performance(exam.id, dim_id, include_children=True)

        # Build lookup by hierarchy_id
        by_id = {n['hierarchy_id']: n for n in result['nodes']}

        # Valves: 3 direct, 3 total (leaf)
        assert by_id[nodes['valves'].id]['direct_entries'] == 3
        assert by_id[nodes['valves'].id]['total_entries'] == 3

        # Blood Vessels: 2 direct, 2 total (leaf)
        assert by_id[nodes['blood_vessels'].id]['direct_entries'] == 2
        assert by_id[nodes['blood_vessels'].id]['total_entries'] == 2

        # Heart: 0 direct, 3 total (from Valves)
        assert by_id[nodes['heart'].id]['direct_entries'] == 0
        assert by_id[nodes['heart'].id]['total_entries'] == 3

        # Cardiovascular: 0 direct, 5 total (3 from Valves via Heart + 2 from Blood Vessels)
        assert by_id[nodes['cardiovascular'].id]['direct_entries'] == 0
        assert by_id[nodes['cardiovascular'].id]['total_entries'] == 5

    def test_dimension_performance_without_aggregation(self, db_with_dimension_hierarchy):
        """Test that include_children=False returns only direct counts."""
        data = db_with_dimension_hierarchy
        db = data['db']
        exam = data['exam']
        dim_id = data['dimension_id']
        nodes = data['nodes']

        result = db.get_dimension_performance(exam.id, dim_id, include_children=False)

        by_id = {n['hierarchy_id']: n for n in result['nodes']}

        # With include_children=False, total_entries should equal direct_entries
        assert by_id[nodes['valves'].id]['total_entries'] == 3
        assert by_id[nodes['blood_vessels'].id]['total_entries'] == 2
        assert by_id[nodes['heart'].id]['total_entries'] == 0
        assert by_id[nodes['cardiovascular'].id]['total_entries'] == 0

    def test_dimension_performance_sorted_by_total(self, db_with_dimension_hierarchy):
        """Test that results are sorted by total_entries descending."""
        data = db_with_dimension_hierarchy
        db = data['db']
        exam = data['exam']
        dim_id = data['dimension_id']

        result = db.get_dimension_performance(exam.id, dim_id, include_children=True)

        totals = [n['total_entries'] for n in result['nodes']]
        assert totals == sorted(totals, reverse=True)


class TestGetSubjectAnalyticsAggregation:
    """Tests for get_subject_analytics() with hierarchy aggregation."""

    @pytest.fixture
    def db_with_subject_hierarchy(self, tmp_path):
        """Create a database with subject hierarchy for testing analytics."""
        db_path = tmp_path / "test_subject_analytics.db"
        db = UserDatabase(str(db_path), user_id=1, username="testuser")

        # Create exam context
        exam = db.create_exam_context(
            exam_name="Subject Analytics Test",
            exam_description="Test exam",
            hierarchy_levels=["System", "Topic", "Subtopic"]
        )

        # Create hierarchy
        system = db.create_subject_node(
            exam_context=exam.exam_name,
            name="System A",
            level_type="System"
        )

        topic = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Topic 1",
            level_type="Topic",
            parent_id=system.id
        )

        subtopic = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Subtopic X",
            level_type="Subtopic",
            parent_id=topic.id
        )

        # Create another system for comparison
        system_b = db.create_subject_node(
            exam_context=exam.exam_name,
            name="System B",
            level_type="System"
        )

        # Create session and entries
        session = db.create_review_session(
            exam_context_id=exam.id,
            total_questions=10,
            total_incorrect=7,
            session_name="Test Session"
        )

        # 5 entries to Subtopic X
        for i in range(5):
            entry = db.create_question_entry(
                review_session_id=session.id,
                user_answer="Answer",
                correct_answer="Correct",
                perceived_difficulty=3,
                reflection=f"Subtopic entry {i}"
            )
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, subtopic.id))

        # 2 entries to System B (direct)
        for i in range(2):
            entry = db.create_question_entry(
                review_session_id=session.id,
                user_answer="Answer",
                correct_answer="Correct",
                perceived_difficulty=4,
                reflection=f"System B entry {i}"
            )
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, system_b.id))

        db.conn.commit()

        return {
            'db': db,
            'exam': exam,
            'nodes': {
                'system': system,
                'topic': topic,
                'subtopic': subtopic,
                'system_b': system_b
            }
        }

    def test_subject_analytics_includes_total_mistake_count(self, db_with_subject_hierarchy):
        """Test that results include both mistake_count and total_mistake_count."""
        data = db_with_subject_hierarchy
        db = data['db']
        exam = data['exam']

        results = db.get_subject_analytics(exam_context_id=exam.id, limit=10, include_children=True)

        # All results should have both fields
        for result in results:
            assert 'mistake_count' in result
            assert 'total_mistake_count' in result

    def test_subject_analytics_aggregates_children(self, db_with_subject_hierarchy):
        """Test that subjects with direct entries include child counts in total.

        Note: get_subject_analytics() only returns subjects that have at least
        one direct entry (due to JOIN). Parent nodes with 0 direct entries but
        children with entries are not included in results.
        """
        data = db_with_subject_hierarchy
        db = data['db']
        exam = data['exam']
        nodes = data['nodes']

        results = db.get_subject_analytics(exam_context_id=exam.id, limit=20, include_children=True)

        # Build lookup by subject_id
        by_id = {r['subject_id']: r for r in results}

        # Subtopic X: 5 direct, 5 total (leaf node)
        assert by_id[nodes['subtopic'].id]['mistake_count'] == 5
        assert by_id[nodes['subtopic'].id]['total_mistake_count'] == 5

        # System B: 2 direct, 2 total (no children with entries)
        assert by_id[nodes['system_b'].id]['mistake_count'] == 2
        assert by_id[nodes['system_b'].id]['total_mistake_count'] == 2

        # Note: Topic 1 and System A have 0 direct entries, so they don't
        # appear in results. This is current expected behavior - only subjects
        # with at least one direct entry are returned.
        assert nodes['topic'].id not in by_id
        assert nodes['system'].id not in by_id

    def test_subject_analytics_sorted_by_total_when_aggregating(self, db_with_subject_hierarchy):
        """Test that results are sorted by total_mistake_count when include_children=True."""
        data = db_with_subject_hierarchy
        db = data['db']
        exam = data['exam']

        results = db.get_subject_analytics(exam_context_id=exam.id, limit=10, include_children=True)

        totals = [r['total_mistake_count'] for r in results]
        assert totals == sorted(totals, reverse=True)

    def test_subject_analytics_parent_with_direct_entries(self, tmp_path):
        """Test aggregation when parent nodes also have direct entries."""
        db_path = tmp_path / "test_parent_entries.db"
        db = UserDatabase(str(db_path), user_id=1, username="testuser")

        exam = db.create_exam_context(
            exam_name="Parent Entry Test",
            exam_description="Test",
            hierarchy_levels=["System", "Topic"]
        )

        # Create hierarchy
        parent = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Parent System",
            level_type="System"
        )

        child = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Child Topic",
            level_type="Topic",
            parent_id=parent.id
        )

        session = db.create_review_session(
            exam_context_id=exam.id,
            total_questions=10,
            total_incorrect=5,
            session_name="Test"
        )

        # 2 entries directly to parent
        for i in range(2):
            entry = db.create_question_entry(
                review_session_id=session.id,
                user_answer="A",
                correct_answer="B",
                perceived_difficulty=3,
                reflection=f"Parent entry {i}"
            )
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, parent.id))

        # 3 entries to child
        for i in range(3):
            entry = db.create_question_entry(
                review_session_id=session.id,
                user_answer="A",
                correct_answer="B",
                perceived_difficulty=3,
                reflection=f"Child entry {i}"
            )
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, child.id))

        db.conn.commit()

        results = db.get_subject_analytics(exam_context_id=exam.id, limit=10, include_children=True)
        by_id = {r['subject_id']: r for r in results}

        # Parent: 2 direct, 5 total (2 direct + 3 from child)
        assert by_id[parent.id]['mistake_count'] == 2
        assert by_id[parent.id]['total_mistake_count'] == 5

        # Child: 3 direct, 3 total
        assert by_id[child.id]['mistake_count'] == 3
        assert by_id[child.id]['total_mistake_count'] == 3


class TestGetIntersectionEntriesWithChildren:
    """Tests for get_intersection_entries() with include_children parameter."""

    @pytest.fixture
    def db_with_two_dimensions(self, tmp_path):
        """Create database with two dimensions for intersection testing."""
        db_path = tmp_path / "test_intersection.db"
        db = UserDatabase(str(db_path), user_id=1, username="testuser")

        exam = db.create_exam_context(
            exam_name="Intersection Test",
            exam_description="Test",
            hierarchy_levels=["System", "Topic"]
        )

        # Dimension A: System hierarchy
        dim_a = db.create_dimension(exam.id, "System", "Body system", 1)

        cardio = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Cardiovascular",
            level_type="System",
            dimension_id=dim_a
        )

        heart = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Heart",
            level_type="Topic",
            parent_id=cardio.id,
            dimension_id=dim_a
        )

        # Dimension B: Task hierarchy
        dim_b = db.create_dimension(exam.id, "Task", "Clinical task", 2)

        diagnosis = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Diagnosis",
            level_type="System",
            dimension_id=dim_b
        )

        workup = db.create_subject_node(
            exam_context=exam.exam_name,
            name="Diagnostic Workup",
            level_type="Topic",
            parent_id=diagnosis.id,
            dimension_id=dim_b
        )

        # Create session
        session = db.create_review_session(
            exam_context_id=exam.id,
            total_questions=5,
            total_incorrect=3,
            session_name="Test"
        )

        # Create entries tagged to leaf nodes
        for i in range(3):
            entry = db.create_question_entry(
                review_session_id=session.id,
                user_answer="A",
                correct_answer="B",
                perceived_difficulty=3,
                reflection=f"Heart + Workup entry {i}"
            )
            # Tag to Heart (child of Cardiovascular)
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, heart.id))
            # Tag to Workup (child of Diagnosis)
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, workup.id))

        db.conn.commit()

        return {
            'db': db,
            'exam': exam,
            'dim_a': dim_a,
            'dim_b': dim_b,
            'nodes': {
                'cardio': cardio,
                'heart': heart,
                'diagnosis': diagnosis,
                'workup': workup
            }
        }

    def test_intersection_entries_with_children(self, db_with_two_dimensions):
        """Test that include_children=True finds entries in child nodes."""
        data = db_with_two_dimensions
        db = data['db']
        dim_a = data['dim_a']
        dim_b = data['dim_b']
        nodes = data['nodes']

        # Query for Cardiovascular x Diagnosis intersection (parent nodes)
        # Entries are actually tagged to Heart x Workup (child nodes)
        results = db.get_intersection_entries(
            exam_context_id=data['exam'].id,
            hierarchy_a_id=nodes['cardio'].id,
            dimension_a_id=dim_a,
            hierarchy_b_id=nodes['diagnosis'].id,
            dimension_b_id=dim_b,
            include_children=True
        )

        # Should find the 3 entries tagged to Heart x Workup
        assert len(results) == 3

    def test_intersection_entries_without_children(self, db_with_two_dimensions):
        """Test that include_children=False only finds direct mappings."""
        data = db_with_two_dimensions
        db = data['db']
        dim_a = data['dim_a']
        dim_b = data['dim_b']
        nodes = data['nodes']

        # Query for Cardiovascular x Diagnosis (parent nodes)
        # No entries are directly tagged to these parents
        results = db.get_intersection_entries(
            exam_context_id=data['exam'].id,
            hierarchy_a_id=nodes['cardio'].id,
            dimension_a_id=dim_a,
            hierarchy_b_id=nodes['diagnosis'].id,
            dimension_b_id=dim_b,
            include_children=False
        )

        # Should find no entries (entries are tagged to children)
        assert len(results) == 0

    def test_intersection_entries_direct_mapping(self, db_with_two_dimensions):
        """Test that direct mappings work correctly."""
        data = db_with_two_dimensions
        db = data['db']
        dim_a = data['dim_a']
        dim_b = data['dim_b']
        nodes = data['nodes']

        # Query for Heart x Workup (the actual tagged nodes)
        results = db.get_intersection_entries(
            exam_context_id=data['exam'].id,
            hierarchy_a_id=nodes['heart'].id,
            dimension_a_id=dim_a,
            hierarchy_b_id=nodes['workup'].id,
            dimension_b_id=dim_b,
            include_children=False  # Doesn't matter for leaf nodes
        )

        assert len(results) == 3
