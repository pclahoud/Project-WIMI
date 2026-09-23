"""
Tests for Phase 7.4-7.6 Multi-Dimensional Analytics
Tests dimension performance, cross-dimension analysis, and advanced analytics methods.
"""

import pytest
from datetime import date, datetime, timedelta
from database.user_db import UserDatabase


@pytest.fixture
def db_with_multi_dim_exam(tmp_path):
    """Create a database with a multi-dimensional exam and test data."""
    db_path = tmp_path / "test_user.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")

    # Create a multi-dimensional exam context
    exam = db.create_exam_context(
        exam_name="NBME Test Exam",
        exam_description="Multi-dimensional test exam",
        hierarchy_levels=["System", "Topic", "Subtopic"]
    )

    # Create dimensions
    dim1 = db.create_dimension(
        exam_id=exam.id,
        name="System",
        description="Body system",
        display_order=1
    )

    dim2 = db.create_dimension(
        exam_id=exam.id,
        name="Physician Task",
        description="Clinical task",
        display_order=2
    )

    dim3 = db.create_dimension(
        exam_id=exam.id,
        name="Site of Care",
        description="Healthcare setting",
        display_order=3
    )

    # Create hierarchy nodes for dimension 1 (System)
    # Note: dim1, dim2, dim3 are integers (dimension IDs), not dicts
    # All nodes use level_type="System" as they're top-level nodes
    cardio = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Cardiovascular",
        level_type="System",
        exam_weight_low=15,
        exam_weight_high=20,
        dimension_id=dim1
    )

    respiratory = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Respiratory",
        level_type="System",
        exam_weight_low=10,
        exam_weight_high=15,
        dimension_id=dim1
    )

    neuro = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Neurology",
        level_type="System",
        exam_weight_low=8,
        exam_weight_high=12,
        dimension_id=dim1
    )

    # Create hierarchy nodes for dimension 2 (Physician Task)
    diagnosis = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Diagnosis",
        level_type="System",
        exam_weight_low=30,
        exam_weight_high=40,
        dimension_id=dim2
    )

    management = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Management",
        level_type="System",
        exam_weight_low=25,
        exam_weight_high=35,
        dimension_id=dim2
    )

    prevention = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Prevention",
        level_type="System",
        exam_weight_low=10,
        exam_weight_high=15,
        dimension_id=dim3
    )

    # Create hierarchy nodes for dimension 3 (Site of Care)
    outpatient = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Outpatient",
        level_type="System",
        exam_weight_low=40,
        exam_weight_high=50,
        dimension_id=dim3
    )

    inpatient = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Inpatient",
        level_type="System",
        exam_weight_low=30,
        exam_weight_high=40,
        dimension_id=dim3
    )

    emergency = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Emergency",
        level_type="System",
        exam_weight_low=10,
        exam_weight_high=20,
        dimension_id=dim3
    )

    # Create a review session
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=50,
        total_incorrect=14,
        session_name="Test Session"
    )

    # Create question entries with dimension tags
    # Note: dim1, dim2, dim3 are integers, not dicts
    entries_data = [
        # Cardiovascular + Diagnosis + Outpatient (5 entries)
        {"stem": "CV Diagnosis Outpatient 1", "difficulty": 3, "tags": [(cardio.id, dim1), (diagnosis.id, dim2), (outpatient.id, dim3)]},
        {"stem": "CV Diagnosis Outpatient 2", "difficulty": 4, "tags": [(cardio.id, dim1), (diagnosis.id, dim2), (outpatient.id, dim3)]},
        {"stem": "CV Diagnosis Outpatient 3", "difficulty": 3, "tags": [(cardio.id, dim1), (diagnosis.id, dim2), (outpatient.id, dim3)]},
        {"stem": "CV Diagnosis Outpatient 4", "difficulty": 5, "tags": [(cardio.id, dim1), (diagnosis.id, dim2), (outpatient.id, dim3)]},
        {"stem": "CV Diagnosis Outpatient 5", "difficulty": 4, "tags": [(cardio.id, dim1), (diagnosis.id, dim2), (outpatient.id, dim3)]},

        # Cardiovascular + Management + Inpatient (3 entries)
        {"stem": "CV Management Inpatient 1", "difficulty": 4, "tags": [(cardio.id, dim1), (management.id, dim2), (inpatient.id, dim3)]},
        {"stem": "CV Management Inpatient 2", "difficulty": 5, "tags": [(cardio.id, dim1), (management.id, dim2), (inpatient.id, dim3)]},
        {"stem": "CV Management Inpatient 3", "difficulty": 4, "tags": [(cardio.id, dim1), (management.id, dim2), (inpatient.id, dim3)]},

        # Respiratory + Diagnosis + Emergency (4 entries)
        {"stem": "Resp Diagnosis Emergency 1", "difficulty": 5, "tags": [(respiratory.id, dim1), (diagnosis.id, dim2), (emergency.id, dim3)]},
        {"stem": "Resp Diagnosis Emergency 2", "difficulty": 4, "tags": [(respiratory.id, dim1), (diagnosis.id, dim2), (emergency.id, dim3)]},
        {"stem": "Resp Diagnosis Emergency 3", "difficulty": 5, "tags": [(respiratory.id, dim1), (diagnosis.id, dim2), (emergency.id, dim3)]},
        {"stem": "Resp Diagnosis Emergency 4", "difficulty": 4, "tags": [(respiratory.id, dim1), (diagnosis.id, dim2), (emergency.id, dim3)]},

        # Neurology + Management + Outpatient (2 entries)
        {"stem": "Neuro Management Outpatient 1", "difficulty": 3, "tags": [(neuro.id, dim1), (management.id, dim2), (outpatient.id, dim3)]},
        {"stem": "Neuro Management Outpatient 2", "difficulty": 2, "tags": [(neuro.id, dim1), (management.id, dim2), (outpatient.id, dim3)]},
    ]

    for entry_data in entries_data:
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="Test answer",
            correct_answer="Correct answer",
            perceived_difficulty=entry_data["difficulty"],
            reflection=entry_data["stem"]
        )

        # Add subject mappings (the table used by analytics methods)
        for hierarchy_id, dimension_id in entry_data["tags"]:
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, hierarchy_id))
        db.conn.commit()

    return {
        'db': db,
        'exam': exam,
        'dimensions': [dim1, dim2, dim3],
        'nodes': {
            'cardio': cardio,
            'respiratory': respiratory,
            'neuro': neuro,
            'diagnosis': diagnosis,
            'management': management,
            'prevention': prevention,
            'outpatient': outpatient,
            'inpatient': inpatient,
            'emergency': emergency
        },
        'session': session
    }


@pytest.fixture
def simple_exam_db(tmp_path):
    """Create a database with a simple (non-dimensional) exam."""
    db_path = tmp_path / "test_simple.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")

    exam = db.create_exam_context(
        exam_name="Simple Exam",
        exam_description="Single-dimension test exam"
    )

    return {'db': db, 'exam': exam}


class TestDimensionPerformance:
    """Tests for get_dimension_performance method."""

    def test_get_dimension_performance_basic(self, db_with_multi_dim_exam):
        """Test basic dimension performance aggregation."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]

        result = db.get_dimension_performance(exam.id, dim1)

        assert result['dimension_name'] == 'System'
        assert result['dimension_id'] == dim1
        assert result['total'] == 14  # Total entries
        assert len(result['nodes']) == 3  # 3 system nodes

        # Check that nodes are sorted by total_entries descending
        totals = [n['total_entries'] for n in result['nodes']]
        assert totals == sorted(totals, reverse=True)

    def test_get_dimension_performance_percentages(self, db_with_multi_dim_exam):
        """Test that percentages are calculated correctly."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]

        result = db.get_dimension_performance(exam.id, dim1)

        # Percentages should sum to 100 (with possible rounding)
        total_pct = sum(n['percentage'] for n in result['nodes'])
        assert 99 <= total_pct <= 101

    def test_get_dimension_performance_invalid_dimension(self, db_with_multi_dim_exam):
        """Test with invalid dimension ID."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']

        result = db.get_dimension_performance(exam.id, 99999)

        assert result['dimension_name'] == ''
        assert result['nodes'] == []
        assert result['total'] == 0


class TestSubjectHierarchyByDimension:
    """Tests for get_subject_hierarchy_with_mistakes_by_dimension method."""

    def test_get_hierarchy_by_dimension(self, db_with_multi_dim_exam):
        """Test hierarchical data filtered by dimension."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]

        result = db.get_subject_hierarchy_with_mistakes_by_dimension(exam.id, dim1)

        assert result['name'] == 'System'
        assert len(result['children']) == 3
        assert result['value'] == 14  # Total mistakes

    def test_hierarchy_values_calculated(self, db_with_multi_dim_exam):
        """Test that node values are correctly calculated."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]

        result = db.get_subject_hierarchy_with_mistakes_by_dimension(exam.id, dim1)

        # Find cardiovascular node (should have 8 entries)
        cardio_node = next((c for c in result['children'] if c['name'] == 'Cardiovascular'), None)
        assert cardio_node is not None
        assert cardio_node['value'] == 8


class TestCrossDimensionPerformance:
    """Tests for get_cross_dimension_performance method."""

    def test_get_cross_dimension_basic(self, db_with_multi_dim_exam):
        """Test 2D matrix generation."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]  # System
        dim2 = data['dimensions'][1]  # Physician Task

        result = db.get_cross_dimension_performance(exam.id, dim1, dim2, min_entries=1)

        assert result['dimension_a']['name'] == 'System'
        assert result['dimension_b']['name'] == 'Physician Task'
        assert len(result['matrix']) > 0
        assert result['total'] > 0

    def test_cross_dimension_min_entries_filter(self, db_with_multi_dim_exam):
        """Test that min_entries filter works."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]
        dim2 = data['dimensions'][1]

        # With min_entries=1, should get more cells
        result_low = db.get_cross_dimension_performance(exam.id, dim1, dim2, min_entries=1)

        # With min_entries=5, should get fewer cells
        result_high = db.get_cross_dimension_performance(exam.id, dim1, dim2, min_entries=5)

        assert len(result_low['matrix']) >= len(result_high['matrix'])

    def test_cross_dimension_invalid_dimension(self, db_with_multi_dim_exam):
        """Test with invalid dimension."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]

        result = db.get_cross_dimension_performance(exam.id, dim1, 99999)

        assert result['dimension_a'] is None
        assert result['dimension_b'] is None
        assert result['matrix'] == []


class TestIntersectionEntries:
    """Tests for get_intersection_entries method."""

    def test_get_intersection_entries(self, db_with_multi_dim_exam):
        """Test getting entries at specific intersection."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]
        dim2 = data['dimensions'][1]
        cardio = data['nodes']['cardio']
        diagnosis = data['nodes']['diagnosis']

        result = db.get_intersection_entries(
            exam_context_id=exam.id,
            hierarchy_a_id=cardio.id,
            dimension_a_id=dim1,
            hierarchy_b_id=diagnosis.id,
            dimension_b_id=dim2,
            limit=10
        )

        assert len(result) == 5  # 5 CV+Diagnosis entries
        assert all('reflection' in e for e in result)


class TestTripleDimensionPerformance:
    """Tests for get_triple_dimension_performance method."""

    def test_get_triple_dimension_basic(self, db_with_multi_dim_exam):
        """Test 3-way combination ranking."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dims = data['dimensions']

        result = db.get_triple_dimension_performance(
            exam.id,
            dims[0], dims[1], dims[2],
            min_entries=1, limit=10
        )

        assert len(result) > 0
        assert all('combination' in r for r in result)

        # Should be sorted by count descending
        counts = [r['count'] for r in result]
        assert counts == sorted(counts, reverse=True)


class TestInteractionEffects:
    """Tests for detect_interaction_effects method."""

    def test_detect_interaction_effects(self, db_with_multi_dim_exam):
        """Test interaction effect detection."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]
        dim2 = data['dimensions'][1]

        result = db.detect_interaction_effects(
            exam.id, dim1, dim2,
            threshold=0.01  # Low threshold to catch more effects
        )

        # Result structure should be correct
        for effect in result:
            assert 'dim_a_value' in effect
            assert 'dim_b_value' in effect
            assert 'expected' in effect
            assert 'actual' in effect
            assert 'interaction' in effect
            assert 'severity' in effect
            assert 'direction' in effect


class TestMistakeTypeByDimension:
    """Tests for get_mistake_type_by_dimension method."""

    def test_get_mistake_type_by_dimension(self, db_with_multi_dim_exam):
        """Test mistake type breakdown by dimension."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]

        result = db.get_mistake_type_by_dimension(exam.id, dim1)

        assert result['dimension_name'] == 'System'
        assert 'values' in result
        assert 'mistake_types' in result


class TestStudyRecommendations:
    """Tests for get_weighted_study_recommendations method."""

    def test_get_recommendations(self, db_with_multi_dim_exam):
        """Test study recommendations generation."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']

        result = db.get_weighted_study_recommendations(exam.id, limit=5)

        # Should return recommendations
        for rec in result:
            assert 'combination' in rec
            assert 'priority_score' in rec
            assert 'recommendation' in rec

        # Should be sorted by priority
        if len(result) > 1:
            scores = [r['priority_score'] for r in result]
            assert scores == sorted(scores, reverse=True)

    def test_recommendations_simple_exam_returns_empty(self, simple_exam_db):
        """Test that simple exams return empty recommendations."""
        db = simple_exam_db['db']
        exam = simple_exam_db['exam']

        result = db.get_weighted_study_recommendations(exam.id)

        assert result == []


class TestTemporalTrends:
    """Tests for get_temporal_trends_by_dimension method."""

    def test_get_temporal_trends(self, db_with_multi_dim_exam):
        """Test temporal trends data."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]

        result = db.get_temporal_trends_by_dimension(
            exam.id, dim1, weeks=12
        )

        assert result['dimension_name'] == 'System'
        assert 'data' in result
        assert 'trend' in result
        assert result['trend'] in ['stable', 'increasing', 'decreasing']


class TestGracefulDegradation:
    """Tests for graceful degradation with simple exams."""

    def test_simple_exam_dimension_performance(self, simple_exam_db):
        """Test that dimension performance returns empty for simple exam."""
        db = simple_exam_db['db']
        exam = simple_exam_db['exam']

        result = db.get_dimension_performance(exam.id, 1)

        assert result['nodes'] == []
        assert result['total'] == 0

    def test_simple_exam_cross_dimension(self, simple_exam_db):
        """Test that cross-dimension returns empty for simple exam."""
        db = simple_exam_db['db']
        exam = simple_exam_db['exam']

        result = db.get_cross_dimension_performance(exam.id, 1, 2)

        assert result['dimension_a'] is None
        assert result['matrix'] == []


@pytest.fixture
def db_with_hierarchical_dim_exam(tmp_path):
    """Create a database with hierarchical dimensions and entries at leaf level.

    Hierarchy:
        Dim1 (System):
          Cardiovascular (System, depth 0)
            └── Heart Failure (Subsystem)
                └── Systolic HF (Topic)       ← 2 entries
            └── Arrhythmia (Subsystem)         ← 1 entry
          Respiratory (System, depth 0)
            └── Asthma (Subsystem)             ← 1 entry

        Dim2 (Task):
          Diagnosis (System, depth 0)
            └── Lab Interpretation (Subsystem) ← entries tagged here
          Management (System, depth 0)         ← entries tagged here
    """
    db_path = tmp_path / "test_hierarchical.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")

    exam = db.create_exam_context(
        exam_name="Hierarchical Test Exam",
        exam_description="Exam with deep hierarchies",
        hierarchy_levels=["System", "Subsystem", "Topic"]
    )

    dim1 = db.create_dimension(exam_id=exam.id, name="BodySystem", description="Body system", display_order=1)
    dim2 = db.create_dimension(exam_id=exam.id, name="ClinicalTask", description="Task type", display_order=2)

    # Dim1 hierarchy
    cardio = db.create_subject_node(exam_context=exam.exam_name, name="Cardiovascular",
                                     level_type="System", dimension_id=dim1)
    heart_failure = db.create_subject_node(exam_context=exam.exam_name, name="Heart Failure",
                                            level_type="Subsystem", parent_id=cardio.id, dimension_id=dim1)
    systolic_hf = db.create_subject_node(exam_context=exam.exam_name, name="Systolic HF",
                                          level_type="Topic", parent_id=heart_failure.id, dimension_id=dim1)
    arrhythmia = db.create_subject_node(exam_context=exam.exam_name, name="Arrhythmia",
                                         level_type="Subsystem", parent_id=cardio.id, dimension_id=dim1)

    respiratory = db.create_subject_node(exam_context=exam.exam_name, name="Respiratory",
                                          level_type="System", dimension_id=dim1)
    asthma = db.create_subject_node(exam_context=exam.exam_name, name="Asthma",
                                     level_type="Subsystem", parent_id=respiratory.id, dimension_id=dim1)

    # Dim2 hierarchy
    diagnosis = db.create_subject_node(exam_context=exam.exam_name, name="Diagnosis",
                                        level_type="System", dimension_id=dim2)
    lab_interp = db.create_subject_node(exam_context=exam.exam_name, name="Lab Interpretation",
                                         level_type="Subsystem", parent_id=diagnosis.id, dimension_id=dim2)
    management = db.create_subject_node(exam_context=exam.exam_name, name="Management",
                                         level_type="System", dimension_id=dim2)

    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=4, session_name="Hier Session"
    )

    # Entries: all tagged at LEAF level
    entries_data = [
        # Entry 1: Systolic HF (leaf of Cardiovascular) + Lab Interpretation (leaf of Diagnosis)
        {"difficulty": 4, "tags": [(systolic_hf.id, dim1), (lab_interp.id, dim2)]},
        # Entry 2: Systolic HF + Lab Interpretation
        {"difficulty": 3, "tags": [(systolic_hf.id, dim1), (lab_interp.id, dim2)]},
        # Entry 3: Arrhythmia (child of Cardiovascular) + Management (direct, no children)
        {"difficulty": 5, "tags": [(arrhythmia.id, dim1), (management.id, dim2)]},
        # Entry 4: Asthma (child of Respiratory) + Lab Interpretation (leaf of Diagnosis)
        {"difficulty": 4, "tags": [(asthma.id, dim1), (lab_interp.id, dim2)]},
    ]

    for i, entry_data in enumerate(entries_data):
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer=f"Answer {i}",
            correct_answer=f"Correct {i}",
            perceived_difficulty=entry_data["difficulty"],
            reflection=f"Reflection {i}"
        )
        for node_id, dimension_id in entry_data["tags"]:
            db.conn.execute("""
                INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                VALUES (?, ?, 'primary')
            """, (entry.id, node_id))
        db.conn.commit()

    return {
        'db': db,
        'exam': exam,
        'dimensions': [dim1, dim2],
        'nodes': {
            'cardio': cardio,
            'heart_failure': heart_failure,
            'systolic_hf': systolic_hf,
            'arrhythmia': arrhythmia,
            'respiratory': respiratory,
            'asthma': asthma,
            'diagnosis': diagnosis,
            'lab_interp': lab_interp,
            'management': management
        },
        'session': session
    }


class TestCrossDimensionIncludeChildren:
    """Tests for include_children in get_cross_dimension_performance."""

    def test_cross_dimension_include_children_aggregates(self, db_with_hierarchical_dim_exam):
        """System-level query with include_children=True aggregates descendant entries."""
        data = db_with_hierarchical_dim_exam
        db = data['db']
        exam = data['exam']
        dim1, dim2 = data['dimensions']

        result = db.get_cross_dimension_performance(
            exam.id, dim1, dim2,
            level_type_a="System", level_type_b="System",
            include_children=True
        )

        matrix = {(c['dim_a_value'], c['dim_b_value']): c['count'] for c in result['matrix']}

        # Cardiovascular + Diagnosis: entries 1,2 (Systolic HF → Lab Interp)
        assert matrix.get(('Cardiovascular', 'Diagnosis')) == 2
        # Cardiovascular + Management: entry 3 (Arrhythmia → Management)
        assert matrix.get(('Cardiovascular', 'Management')) == 1
        # Respiratory + Diagnosis: entry 4 (Asthma → Lab Interp)
        assert matrix.get(('Respiratory', 'Diagnosis')) == 1
        # Total should be 4
        assert result['total'] == 4
        assert result['include_children'] is True

    def test_cross_dimension_include_children_false(self, db_with_hierarchical_dim_exam):
        """System-level query with include_children=False returns only direct mappings."""
        data = db_with_hierarchical_dim_exam
        db = data['db']
        exam = data['exam']
        dim1, dim2 = data['dimensions']

        result = db.get_cross_dimension_performance(
            exam.id, dim1, dim2,
            level_type_a="System", level_type_b="System",
            include_children=False
        )

        # Only Management is a direct System-level tag; Diagnosis entries are at Subsystem leaf.
        # Cardiovascular/Respiratory entries are all at children, so no direct System matches.
        # Only cell with direct match: entry 3 has Arrhythmia (Subsystem, NOT System) + Management (System)
        # So Arrhythmia won't match level_type_a="System", meaning 0 direct System×System matches.
        # Management is System-level and directly tagged, but dim_a nodes need System level too.
        # Result: matrix should have at most Management (System) on dim_b, but no System-level dim_a direct tags.
        assert result['total'] == 0 or len(result['matrix']) == 0
        assert result['include_children'] is False

    def test_cross_dimension_no_double_counting(self, db_with_hierarchical_dim_exam):
        """An entry at a leaf is counted exactly once per ancestor cell."""
        data = db_with_hierarchical_dim_exam
        db = data['db']
        exam = data['exam']
        dim1, dim2 = data['dimensions']

        result = db.get_cross_dimension_performance(
            exam.id, dim1, dim2,
            level_type_a="System", level_type_b="System",
            include_children=True
        )

        # Entries 1 and 2 are both Systolic HF + Lab Interp.
        # Systolic HF is under Heart Failure under Cardiovascular.
        # Lab Interp is under Diagnosis.
        # Each entry should be counted once in (Cardiovascular, Diagnosis), not multiple times.
        matrix = {(c['dim_a_value'], c['dim_b_value']): c['count'] for c in result['matrix']}
        assert matrix.get(('Cardiovascular', 'Diagnosis')) == 2  # exactly 2 entries, not more

    def test_cross_dimension_drilldown_with_children(self, db_with_hierarchical_dim_exam):
        """Drill-down with parent_node_a_id + include_children aggregates sub-descendants."""
        data = db_with_hierarchical_dim_exam
        db = data['db']
        exam = data['exam']
        dim1, dim2 = data['dimensions']
        cardio = data['nodes']['cardio']

        # Drill into Cardiovascular: show its Subsystem children on axis A
        result = db.get_cross_dimension_performance(
            exam.id, dim1, dim2,
            level_type_a="Subsystem", level_type_b="System",
            parent_node_a_id=cardio.id,
            include_children=True
        )

        matrix = {(c['dim_a_value'], c['dim_b_value']): c['count'] for c in result['matrix']}

        # Heart Failure (Subsystem) should aggregate its child Systolic HF entries
        # Entries 1,2 are Systolic HF + Lab Interp → Heart Failure + Diagnosis
        assert matrix.get(('Heart Failure', 'Diagnosis')) == 2
        # Arrhythmia (Subsystem, no children) + Management
        assert matrix.get(('Arrhythmia', 'Management')) == 1

    def test_cross_dimension_flat_hierarchy_unchanged(self, db_with_multi_dim_exam):
        """Existing flat fixture returns same results with include_children=True or False."""
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        dim1 = data['dimensions'][0]
        dim2 = data['dimensions'][1]

        result_with = db.get_cross_dimension_performance(
            exam.id, dim1, dim2, include_children=True
        )
        result_without = db.get_cross_dimension_performance(
            exam.id, dim1, dim2, include_children=False
        )

        # Same counts since all nodes are flat (no children)
        matrix_with = {(c['dim_a_value'], c['dim_b_value']): c['count'] for c in result_with['matrix']}
        matrix_without = {(c['dim_a_value'], c['dim_b_value']): c['count'] for c in result_without['matrix']}
        assert matrix_with == matrix_without


class TestStage9WeightSourceOnDimensionalAnalytics:
    """Stage 9: dimensional analytics consume per-edge weight_source.

    Reference: ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``
    §"Stage 9". Even multi-dimensional exams should pick up the new
    ``weight_source`` field on ``subject_edges`` when running
    ``get_subject_exam_weight_analysis``. This is a regression guard
    for the dimensions.py / analytics.py audit pass — those files have
    no direct ``weight_source`` reads today, so the assertion runs
    through the canonical analysis helper that we *did* change.
    """

    def test_weight_analysis_picks_up_per_edge_weight_source_in_multi_dim_exam(
        self, db_with_multi_dim_exam
    ):
        data = db_with_multi_dim_exam
        db = data['db']
        exam = data['exam']
        cardio_id = data['nodes']['cardio'].id

        # The multi-dim fixture creates Cardio as a System node with
        # no incoming edges, so its ``weight_source`` falls back to
        # ``subject_nodes.weight_source``. To exercise the new
        # per-edge read path we attach Cardio as a child of another
        # node (Diagnosis) and stamp the *edge* source.
        diagnosis_id = data['nodes']['diagnosis'].id

        # Attach the polyhierarchy edge: Diagnosis → Cardio.
        # Cardio already has no primary parent, so this becomes its
        # primary edge (set is_primary=True to make it dominant).
        db.add_edge(parent_id=diagnosis_id, child_id=cardio_id, is_primary=True)

        # Find the new edge id and stamp the source we care about.
        edge_row = db.fetchone(
            "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
            (diagnosis_id, cardio_id),
        )
        assert edge_row is not None
        db.execute(
            "UPDATE subject_edges SET relative_weight = 50.0, "
            "weight_source = 'official' WHERE id = ?",
            (edge_row['id'],),
        )
        # The shared multi-dim fixture creates entries via
        # ``create_question_entry(reflection=...)`` without an
        # ``explanation`` value, which makes the creator default
        # ``is_draft=True``. The weight-analysis query filters
        # ``qe.is_draft = FALSE``, so all those entries would be
        # excluded and the analysis would return an empty subjects
        # list. Force every question entry in this exam to non-draft
        # so the query produces meaningful rows.
        db.execute("UPDATE question_entries SET is_draft = FALSE")
        db.conn.commit()

        analysis = db.get_subject_exam_weight_analysis(exam.id)

        # Find cardio's row in the analysis.
        cardio_row = next(
            (s for s in analysis['subjects'] if s['subject_id'] == cardio_id),
            None,
        )
        assert cardio_row is not None, (
            "Cardio is missing from the analysis after attaching "
            "via subject_edges."
        )
        assert cardio_row['weight_source'] == 'official', (
            f"Cardio should pick up 'official' from its dominant edge; "
            f"got {cardio_row['weight_source']!r}"
        )

        # And the bundled breakdown should reflect the same source.
        dist = analysis.get('weight_source_distribution')
        assert dist is not None
        assert dist['official'] >= 1, (
            f"Breakdown must count Cardio under 'official' after the "
            f"edge stamp; got {dist}"
        )




class TestDimensionSunburstPolyhierarchy:
    """Option B: a shared subject is drawn once per in-dimension parent.

    See ``docs/planning/ANALYTICS_PRIMARY_PARENT_ROLLUP.md``. The tree is
    built from ``subject_edges``, not the legacy
    ``subject_nodes.parent_id``, so a subject with two parents inside the
    dimension appears under each -- and §5.4 decides which entries each
    position may draw.
    """

    @staticmethod
    def _positions(tree, name):
        """Every position ``name`` occupies, as (parent_name, direct)."""
        found = []

        def walk(node, parent_name):
            if node.get('name') == name:
                found.append((parent_name, node['direct_mistakes']))
            for child in node.get('children', []):
                walk(child, node.get('name'))

        for root in tree.get('children', []):
            walk(root, None)
        return found

    def test_shared_subject_is_drawn_under_each_parent(
        self, db_with_multi_dim_exam,
    ):
        """The whole point of option B, as counts at each position."""
        data = db_with_multi_dim_exam
        db, exam, dim1 = data['db'], data['exam'], data['dimensions'][0]

        cardio = db.fetchone(
            "SELECT id FROM subject_nodes WHERE name='Cardiovascular'")['id']
        resp = db.fetchone(
            "SELECT id FROM subject_nodes WHERE name='Respiratory'")['id']

        # A leaf inside the dimension with BOTH systems as parents.
        shared = db.create_subject_node(
            exam_context=exam.exam_name, name="pulmonary embolism",
            level_type="Topic", dimension_id=dim1,
        )
        db.add_edge(cardio, shared.id, is_primary=True)
        db.add_edge(resp, shared.id, is_primary=False)

        session = db.fetchone("SELECT id FROM review_sessions LIMIT 1")['id']

        def entry(order, ppid):
            cur = db.execute(
                "INSERT INTO question_entries (review_session_id, entry_order, "
                "user_answer, correct_answer, is_draft) VALUES (?, ?, 'a', 'b', 0)",
                (session, 900 + order))
            db.execute(
                "INSERT INTO entry_subject_mappings (question_entry_id, "
                "subject_node_id, mapping_type, primary_parent_id) "
                "VALUES (?, ?, 'primary', ?)",
                (cur.lastrowid, shared.id, ppid))
        entry(1, cardio)   # "the cardiac one"
        entry(2, None)     # never disambiguated
        db.conn.commit()

        tree = db.get_subject_hierarchy_with_mistakes_by_dimension(exam.id, dim1)
        positions = dict(self._positions(tree, "pulmonary embolism"))

        assert set(positions) == {"Cardiovascular", "Respiratory"}, (
            f"Expected the subject under both systems, got {positions}. "
            "The tree must come from subject_edges, not sn.parent_id."
        )
        assert positions["Cardiovascular"] == 2, (
            "Cardiovascular draws the entry scoped to it plus the "
            "unscoped one."
        )
        assert positions["Respiratory"] == 1, (
            "Respiratory draws only the unscoped entry -- the one scoped "
            "to Cardiovascular must not appear here. That is §5.4."
        )

    def test_secondary_tags_are_not_counted(self, db_with_multi_dim_exam):
        """Aligned with the sunburst, Top Subjects and the quadrant."""
        data = db_with_multi_dim_exam
        db, exam, dim1 = data['db'], data['exam'], data['dimensions'][0]
        before = db.get_subject_hierarchy_with_mistakes_by_dimension(
            exam.id, dim1)['value']

        cardio = db.fetchone(
            "SELECT id FROM subject_nodes WHERE name='Cardiovascular'")['id']
        session = db.fetchone("SELECT id FROM review_sessions LIMIT 1")['id']
        cur = db.execute(
            "INSERT INTO question_entries (review_session_id, entry_order, "
            "user_answer, correct_answer, is_draft) VALUES (?, 950, 'a', 'b', 0)",
            (session,))
        db.execute(
            "INSERT INTO entry_subject_mappings (question_entry_id, "
            "subject_node_id, mapping_type) VALUES (?, ?, 'secondary')",
            (cur.lastrowid, cardio))
        db.conn.commit()

        after = db.get_subject_hierarchy_with_mistakes_by_dimension(
            exam.id, dim1)['value']
        assert after == before, (
            f"A secondary tag moved the total {before} -> {after}. This "
            "surface counts primary tags only."
        )



class TestDimensionPerformancePolyhierarchy:
    """§5.4 and tag-type handling in get_dimension_performance.

    This surface was missed by the original inventory in
    ``docs/planning/ANALYTICS_PRIMARY_PARENT_ROLLUP.md``. It is live on the
    analytics dashboard -- ``DimensionAnalytics.getAllDimensionPerformance``
    calls it once per dimension on page load -- and it aggregates, so
    ignoring the parent context is a real defect here (unlike the weight
    quadrant, which does no rollup and needed no fix).
    """

    @staticmethod
    def _shared_leaf(db, exam, dim, ppid_from):
        """A leaf under both Cardiovascular and Respiratory, plus an entry."""
        cardio = db.fetchone(
            "SELECT id FROM subject_nodes WHERE name='Cardiovascular'")['id']
        resp = db.fetchone(
            "SELECT id FROM subject_nodes WHERE name='Respiratory'")['id']
        leaf = db.create_subject_node(
            exam_context=exam.exam_name, name="pulmonary embolism",
            level_type="Topic", dimension_id=dim,
        )
        db.add_edge(cardio, leaf.id, is_primary=True)
        db.add_edge(resp, leaf.id, is_primary=False)
        session = db.fetchone("SELECT id FROM review_sessions LIMIT 1")['id']
        cur = db.execute(
            "INSERT INTO question_entries (review_session_id, entry_order, "
            "user_answer, correct_answer, is_draft) VALUES (?, 800, 'a','b',0)",
            (session,))
        db.execute(
            "INSERT INTO entry_subject_mappings (question_entry_id, "
            "subject_node_id, mapping_type, primary_parent_id) "
            "VALUES (?, ?, 'primary', ?)",
            (cur.lastrowid, leaf.id, {'cardio': cardio, 'resp': resp,
                                      None: None}[ppid_from]))
        db.conn.commit()
        return {'cardio': cardio, 'resp': resp, 'leaf': leaf.id,
                'entry': cur.lastrowid}

    @staticmethod
    def _totals(db, exam, dim):
        r = db.get_dimension_performance(exam.id, dim)
        return {n['name']: n['total_entries'] for n in r['nodes']}

    @staticmethod
    def _direct(db, exam, dim):
        """direct_entries, which comes from a DIFFERENT query than totals.

        total_entries is built from the context-bucket query; direct_entries
        from the node SELECT's join. They can disagree, so tests that care
        about tag type have to assert on both -- a mapping_type filter
        missing from only one of them is invisible otherwise.
        """
        r = db.get_dimension_performance(exam.id, dim)
        return {n['name']: n['direct_entries'] for n in r['nodes']}

    def test_pinned_entry_reaches_only_its_chosen_parent(
        self, db_with_multi_dim_exam,
    ):
        """The §5.4 fix, as the numbers each system rolls up."""
        d = db_with_multi_dim_exam
        db, exam, dim = d['db'], d['exam'], d['dimensions'][0]
        base = self._totals(db, exam, dim)

        ids = self._shared_leaf(db, exam, dim, 'cardio')
        after = self._totals(db, exam, dim)

        assert after['Cardiovascular'] == base['Cardiovascular'] + 1, (
            "The system the entry was pinned to must gain it."
        )
        assert after['Respiratory'] == base['Respiratory'], (
            f"Respiratory moved {base['Respiratory']} -> "
            f"{after['Respiratory']}. The entry was pinned to "
            "Cardiovascular, so it must not roll up here."
        )

    def test_unpinned_entry_reaches_both_parents(self, db_with_multi_dim_exam):
        """§5.3 still applies when the student never disambiguated."""
        d = db_with_multi_dim_exam
        db, exam, dim = d['db'], d['exam'], d['dimensions'][0]
        base = self._totals(db, exam, dim)

        self._shared_leaf(db, exam, dim, None)
        after = self._totals(db, exam, dim)

        assert after['Cardiovascular'] == base['Cardiovascular'] + 1
        assert after['Respiratory'] == base['Respiratory'] + 1, (
            "An undisambiguated entry rolls up through every parent. If "
            "this dropped, the fix over-corrected into strict-always."
        )

    def test_secondary_tags_are_not_counted(self, db_with_multi_dim_exam):
        d = db_with_multi_dim_exam
        db, exam, dim = d['db'], d['exam'], d['dimensions'][0]
        base = self._totals(db, exam, dim)

        ids = self._shared_leaf(db, exam, dim, 'cardio')
        db.execute(
            "UPDATE entry_subject_mappings SET mapping_type='secondary' "
            "WHERE question_entry_id = ?", (ids['entry'],))
        db.conn.commit()

        after = self._totals(db, exam, dim)
        # Compare only the systems: _shared_leaf also adds the leaf node
        # itself, which is a new row at 0 rather than a count change.
        assert {k: after[k] for k in base} == base, (
            "A secondary 'also tested' tag must not count as a mistake -- "
            "every other surface filters to primary."
        )
        assert after["pulmonary embolism"] == 0
        # And on the other query too: direct_entries is built by the node
        # SELECT, so a mapping_type filter present in only one of the two
        # would pass every assertion above.
        assert self._direct(db, exam, dim)["pulmonary embolism"] == 0, (
            "The node SELECT counted a secondary tag as a direct entry."
        )

    def test_entries_from_another_exam_are_not_counted(
        self, db_with_multi_dim_exam,
    ):
        """The query must scope entries to this exam's sessions.

        It joined entry_subject_mappings straight to question_entries with
        no review_sessions join at all, so any entry tagging one of these
        subjects counted regardless of which exam's session it belonged to.
        """
        d = db_with_multi_dim_exam
        db, exam, dim = d['db'], d['exam'], d['dimensions'][0]
        base = self._totals(db, exam, dim)
        direct_base = self._direct(db, exam, dim)["Cardiovascular"]

        cardio = db.fetchone(
            "SELECT id FROM subject_nodes WHERE name='Cardiovascular'")['id']
        other = db.create_exam_context(
            exam_name="Some Other Exam", exam_description="different exam")
        from datetime import date
        other_session = db.create_review_session(
            exam_context_id=other.id, total_questions=1, total_incorrect=1,
            session_name="elsewhere", date_encountered=date.today())
        cur = db.execute(
            "INSERT INTO question_entries (review_session_id, entry_order, "
            "user_answer, correct_answer, is_draft) VALUES (?, 810, 'a','b',0)",
            (other_session.id,))
        db.execute(
            "INSERT INTO entry_subject_mappings (question_entry_id, "
            "subject_node_id, mapping_type) VALUES (?, ?, 'primary')",
            (cur.lastrowid, cardio))
        db.conn.commit()

        assert self._totals(db, exam, dim) == base, (
            "An entry from another exam's session leaked into "
            "total_entries."
        )
        assert self._direct(db, exam, dim)["Cardiovascular"] == direct_base, (
            "...and the same must hold for direct_entries, which the node "
            "SELECT builds separately. Scoping present in only one of the "
            "two queries passes every total_entries assertion."
        )


# =============================================================================
# ENTRY_COUNT_AUDIT T2 -- cross-dimension family and the latent dimension
# surfaces.
#
# Every test below records, in its own docstring or name, whether the
# function under test AGGREGATES up a hierarchy. That is the discriminator
# for POLYHIERARCHY_MIGRATION §5.4: a query doing direct per-node counts
# cannot be fixed by it, because no ``primary_parent_id`` value can change
# its output. See ``docs/planning/ANALYTICS_PRIMARY_PARENT_ROLLUP.md``
# ("Correction: the weight quadrant") for the surface that was wrongly
# "fixed" by ignoring this.
# =============================================================================


def _add_entry(db, session_id, order, mappings, difficulty=3):
    """Insert one question entry plus its subject mappings.

    ``mappings`` is a list of ``(subject_node_id, mapping_type,
    primary_parent_id)`` triples.
    """
    cur = db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer, perceived_difficulty, is_draft) "
        "VALUES (?, ?, 'a', 'b', ?, 0)",
        (session_id, order, difficulty))
    entry_id = cur.lastrowid
    for node_id, mapping_type, ppid in mappings:
        db.execute(
            "INSERT INTO entry_subject_mappings (question_entry_id, "
            "subject_node_id, mapping_type, primary_parent_id) VALUES (?, ?, ?, ?)",
            (entry_id, node_id, mapping_type, ppid))
    db.conn.commit()
    return entry_id


def _session_for(db, exam_context_id, user_id, name="scoping probe"):
    """A review_sessions row for an arbitrary user, written directly.

    ``create_review_session`` always stamps ``self.user_id``, and the
    point of several tests below is an entry belonging to somebody else.
    """
    cur = db.execute(
        "INSERT INTO review_sessions (user_id, exam_context_id, session_name, "
        "date_encountered, total_questions, total_incorrect) "
        "VALUES (?, ?, ?, date('now'), 5, 1)",
        (user_id, exam_context_id, name))
    db.conn.commit()
    return cur.lastrowid


def _shared_leaf_in_dim1(data, name="pulmonary embolism"):
    """A dim1 Topic whose parents are BOTH Cardiovascular and Respiratory.

    Same shape as §5.4's motivating example (PE under Respiratory *and*
    Pregnancy): one node, two parents inside a single dimension.
    """
    db, exam, dim1 = data['db'], data['exam'], data['dimensions'][0]
    cardio = data['nodes']['cardio']
    resp = data['nodes']['respiratory']
    leaf = db.create_subject_node(
        exam_context=exam.exam_name, name=name,
        level_type="Topic", dimension_id=dim1,
    )
    db.add_edge(cardio.id, leaf.id, is_primary=True)
    db.add_edge(resp.id, leaf.id, is_primary=False)
    return leaf


def _matrix(db, exam_id, dim_a, dim_b, **kwargs):
    """The heatmap as ``{(row_name, col_name): count}``."""
    result = db.get_cross_dimension_performance(exam_id, dim_a, dim_b, **kwargs)
    return {(c['dim_a_value'], c['dim_b_value']): c['count']
            for c in result['matrix']}


class TestCrossDimensionHeatmapWithChildren:
    """``_cross_dimension_query_with_children`` -- it AGGREGATES.

    Evidence: ``dim_a_tree`` and ``dim_b_tree`` are recursive CTEs (four
    UNIONs between them) walking ``subject_edges`` from each display-level
    root down to every descendant, and the outer SELECT groups by
    ``root_id``. An entry tagged on a leaf lands in its ancestor's cell.
    So §5.4 applies -- and was entirely absent.
    """

    def test_pinned_entry_reaches_only_the_chosen_system(
        self, db_with_hierarchical_dim_exam,
    ):
        """§5.4's non-NULL branch, as heatmap cells."""
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        leaf = _shared_leaf_in_dim1(d)
        cardio = d['nodes']['cardio']
        mgmt = d['nodes']['management']

        base = _matrix(db, exam.id, dim1, dim2,
                       level_type_a='System', level_type_b='System')

        _add_entry(db, d['session'].id, 401,
                   [(leaf.id, 'primary', cardio.id),
                    (mgmt.id, 'primary', None)])

        after = _matrix(db, exam.id, dim1, dim2,
                        level_type_a='System', level_type_b='System')

        assert after[('Cardiovascular', 'Management')] == \
            base.get(('Cardiovascular', 'Management'), 0) + 1, (
            "The system the student pinned must gain the mistake."
        )
        assert after.get(('Respiratory', 'Management'), 0) == \
            base.get(('Respiratory', 'Management'), 0), (
            "Respiratory is the leaf's other parent, but the student said "
            "they meant Cardiovascular. §5.4 keeps it out of this cell."
        )

    def test_unpinned_entry_reaches_both_systems(
        self, db_with_hierarchical_dim_exam,
    ):
        """§5.3 survives: a NULL context still rolls up everywhere."""
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        leaf = _shared_leaf_in_dim1(d)
        mgmt = d['nodes']['management']

        base = _matrix(db, exam.id, dim1, dim2,
                       level_type_a='System', level_type_b='System')

        _add_entry(db, d['session'].id, 402,
                   [(leaf.id, 'primary', None), (mgmt.id, 'primary', None)])

        after = _matrix(db, exam.id, dim1, dim2,
                        level_type_a='System', level_type_b='System')

        assert after[('Cardiovascular', 'Management')] == \
            base.get(('Cardiovascular', 'Management'), 0) + 1
        assert after[('Respiratory', 'Management')] == \
            base.get(('Respiratory', 'Management'), 0) + 1, (
            "An undisambiguated entry rolls up through every parent "
            "(OMOP §5.3). If this dropped, the fix over-corrected into "
            "strict-always."
        )

    def test_a_nodes_own_tags_are_context_blind(
        self, db_with_hierarchical_dim_exam,
    ):
        """Pinning cannot hide an entry from the node it is tagged on.

    ``primary_parent_id`` names the parent the entry rolls *through*. An
    entry tagged directly on Cardiovascular still belongs to
    Cardiovascular whatever sits above it -- the same rule
    ``_aggregate_hierarchy_counts`` applies to a node's own count.
        """
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        cardio, resp = d['nodes']['cardio'], d['nodes']['respiratory']
        mgmt = d['nodes']['management']

        base = _matrix(db, exam.id, dim1, dim2,
                       level_type_a='System', level_type_b='System')
        # Pin to an unrelated node that is nowhere in Cardiovascular's subtree.
        _add_entry(db, d['session'].id, 403,
                   [(cardio.id, 'primary', resp.id),
                    (mgmt.id, 'primary', None)])
        after = _matrix(db, exam.id, dim1, dim2,
                        level_type_a='System', level_type_b='System')

        assert after[('Cardiovascular', 'Management')] == \
            base.get(('Cardiovascular', 'Management'), 0) + 1, (
            "An entry tagged ON Cardiovascular disappeared because its "
            "primary_parent_id pointed outside Cardiovascular's subtree. "
            "§5.4 scopes rollup, it does not delete direct tags."
        )

    def test_secondary_tags_are_not_counted(
        self, db_with_hierarchical_dim_exam,
    ):
        """Both axes were unfiltered, so the error was multiplicative."""
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        systolic = d['nodes']['systolic_hf']
        lab = d['nodes']['lab_interp']

        base = _matrix(db, exam.id, dim1, dim2,
                       level_type_a='System', level_type_b='System')
        _add_entry(db, d['session'].id, 404,
                   [(systolic.id, 'secondary', None),
                    (lab.id, 'secondary', None)])
        assert _matrix(db, exam.id, dim1, dim2,
                       level_type_a='System', level_type_b='System') == base, (
            "A pair of secondary 'also tested' tags moved the heatmap. "
            "Every other analytics surface counts primary tags only."
        )

    def test_another_exams_entries_do_not_leak(
        self, db_with_hierarchical_dim_exam,
    ):
        """The function had ZERO references to review_sessions."""
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        systolic, lab = d['nodes']['systolic_hf'], d['nodes']['lab_interp']

        base = _matrix(db, exam.id, dim1, dim2,
                       level_type_a='System', level_type_b='System')
        other = db.create_exam_context(
            exam_name="Unrelated Exam", exam_description="elsewhere")
        other_session = _session_for(db, other.id, db.user_id, "other exam")
        _add_entry(db, other_session, 405,
                   [(systolic.id, 'primary', None), (lab.id, 'primary', None)])

        assert _matrix(db, exam.id, dim1, dim2,
                       level_type_a='System', level_type_b='System') == base, (
            "An entry belonging to a different exam's session counted in "
            "this exam's heatmap."
        )

    def test_another_users_entries_do_not_leak(
        self, db_with_hierarchical_dim_exam,
    ):
        """...and the same session join must filter rs.user_id."""
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        systolic, lab = d['nodes']['systolic_hf'], d['nodes']['lab_interp']

        base = _matrix(db, exam.id, dim1, dim2,
                       level_type_a='System', level_type_b='System')
        someone_else = _session_for(db, exam.id, db.user_id + 1, "not mine")
        _add_entry(db, someone_else, 406,
                   [(systolic.id, 'primary', None), (lab.id, 'primary', None)])

        assert _matrix(db, exam.id, dim1, dim2,
                       level_type_a='System', level_type_b='System') == base, (
            "Another user's entry counted. Filtering exam_context_id "
            "alone is not enough -- same exam, different student."
        )

    def test_drilldown_finds_an_edge_only_child(
        self, db_with_hierarchical_dim_exam,
    ):
        """The seed read legacy ``sn.parent_id``, so edge-only rows vanished."""
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        cardio, mgmt = d['nodes']['cardio'], d['nodes']['management']

        # A child of Cardiovascular that exists ONLY in subject_edges.
        edge_only = db.create_subject_node(
            exam_context=exam.exam_name, name="Valvular Disease",
            level_type="Subsystem", dimension_id=dim1)
        db.add_edge(cardio.id, edge_only.id, is_primary=True)
        assert db.fetchone(
            "SELECT parent_id FROM subject_nodes WHERE id = ?",
            (edge_only.id,))['parent_id'] is None, (
            "Fixture precondition: this node must have no legacy parent_id, "
            "otherwise the test cannot tell the two sources apart."
        )
        _add_entry(db, d['session'].id, 407,
                   [(edge_only.id, 'primary', None), (mgmt.id, 'primary', None)])

        drilled = _matrix(db, exam.id, dim1, dim2,
                          parent_node_a_id=cardio.id, level_type_b='System')
        assert ('Valvular Disease', 'Management') in drilled, (
            f"Drilling into Cardiovascular missed its edge-only child. "
            f"Got {sorted(drilled)}."
        )


class TestCrossDimensionHeatmapDirect:
    """``_cross_dimension_query_direct`` -- it does NOT aggregate.

    Evidence: no recursion anywhere; ``sn_a.id = esm_a.subject_node_id``
    joins the tagged node itself and the GROUP BY is on
    ``esm_a.subject_node_id``. Every cell is a direct per-node count, so
    §5.4 is definitionally inapplicable -- pinned or not, an entry tagged
    on N is N's mistake. The characterisation test below asserts exactly
    that, so nobody "fixes" this one the way the weight quadrant nearly
    was.
    """

    def test_pinning_cannot_change_a_direct_count(
        self, db_with_hierarchical_dim_exam,
    ):
        """NOT a defect. §5.4 has no purchase on a non-aggregating query."""
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        leaf = _shared_leaf_in_dim1(d)
        cardio, resp = d['nodes']['cardio'], d['nodes']['respiratory']
        mgmt = d['nodes']['management']

        entry_id = _add_entry(db, d['session'].id, 410,
                              [(leaf.id, 'primary', None),
                               (mgmt.id, 'primary', None)])

        seen = []
        for ppid in (None, cardio.id, resp.id):
            db.execute(
                "UPDATE entry_subject_mappings SET primary_parent_id = ? "
                "WHERE question_entry_id = ? AND subject_node_id = ?",
                (ppid, entry_id, leaf.id))
            db.conn.commit()
            seen.append(_matrix(db, exam.id, dim1, dim2,
                                include_children=False))

        assert seen[0] == seen[1] == seen[2], (
            "The direct query's output changed with primary_parent_id. "
            "It has no ancestor walk, so that should be impossible -- "
            "either the query started aggregating or a §5.4 predicate was "
            "added where it does not belong."
        )
        assert seen[0][('pulmonary embolism', 'Management')] == 1, (
            "And the cell sits on the tagged leaf itself, not on a system."
        )

    def test_secondary_tags_are_not_counted(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        systolic, lab = d['nodes']['systolic_hf'], d['nodes']['lab_interp']

        base = _matrix(db, exam.id, dim1, dim2, include_children=False)
        _add_entry(db, d['session'].id, 411,
                   [(systolic.id, 'secondary', None),
                    (lab.id, 'secondary', None)])
        assert _matrix(db, exam.id, dim1, dim2,
                       include_children=False) == base

    def test_another_exams_entries_do_not_leak(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        systolic, lab = d['nodes']['systolic_hf'], d['nodes']['lab_interp']

        base = _matrix(db, exam.id, dim1, dim2, include_children=False)
        other = db.create_exam_context(
            exam_name="Unrelated Exam D", exam_description="elsewhere")
        other_session = _session_for(db, other.id, db.user_id, "other exam")
        _add_entry(db, other_session, 412,
                   [(systolic.id, 'primary', None), (lab.id, 'primary', None)])
        assert _matrix(db, exam.id, dim1, dim2,
                       include_children=False) == base

    def test_another_users_entries_do_not_leak(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        systolic, lab = d['nodes']['systolic_hf'], d['nodes']['lab_interp']

        base = _matrix(db, exam.id, dim1, dim2, include_children=False)
        someone_else = _session_for(db, exam.id, db.user_id + 1, "not mine")
        _add_entry(db, someone_else, 413,
                   [(systolic.id, 'primary', None), (lab.id, 'primary', None)])
        assert _matrix(db, exam.id, dim1, dim2,
                       include_children=False) == base

    def test_drilldown_finds_an_edge_only_child(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        cardio, mgmt = d['nodes']['cardio'], d['nodes']['management']

        edge_only = db.create_subject_node(
            exam_context=exam.exam_name, name="Pericardial Disease",
            level_type="Subsystem", dimension_id=dim1)
        db.add_edge(cardio.id, edge_only.id, is_primary=True)
        _add_entry(db, d['session'].id, 414,
                   [(edge_only.id, 'primary', None), (mgmt.id, 'primary', None)])

        drilled = _matrix(db, exam.id, dim1, dim2, include_children=False,
                          parent_node_a_id=cardio.id)
        assert ('Pericardial Disease', 'Management') in drilled, (
            f"Drill-down still reads the legacy parent column. "
            f"Got {sorted(drilled)}."
        )


class TestFilteredDimensionNodesAxis:
    """``_get_filtered_dimension_nodes`` builds the heatmap's axes.

    It counts nothing and aggregates nothing, so §5.4 is inapplicable.
    Its ``parent_node_id`` filter read legacy ``sn.parent_id``, which
    gives a node exactly one home -- so a multi-parent node was missing
    from one of its parents' axes and its cells could never render.
    """

    def test_axis_includes_an_edge_only_child(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam, dim1 = d['db'], d['exam'], d['dimensions'][0]
        resp = d['nodes']['respiratory']
        _shared_leaf_in_dim1(d)

        axis = db.get_dimension_nodes(exam.id, dim1, parent_node_id=resp.id)
        names = [n['name'] for n in axis]
        assert "pulmonary embolism" in names, (
            f"Respiratory's axis is missing its edge-only child; got "
            f"{names}. The node's legacy parent_id is NULL, so only "
            f"subject_edges knows about this parent."
        )


class TestIntersectionEntriesScoping:
    """``get_intersection_entries``.

    The ``include_children=True`` branch AGGREGATES -- two recursive CTEs
    (``descendants_a``/``descendants_b``) over ``subject_edges`` -- so
    §5.4 applies, and POLYHIERARCHY_MIGRATION §8.1 names this function
    explicitly as needing the override. The ``include_children=False``
    branch matches ``subject_node_id`` exactly and does not aggregate, so
    §5.4 is inapplicable there.
    """

    @staticmethod
    def _ids(db, exam_id, a, dim_a, b, dim_b, **kw):
        return {e['id'] for e in db.get_intersection_entries(
            exam_id, a, dim_a, b, dim_b, **kw)}

    def test_pinned_entry_is_listed_only_under_the_chosen_parent(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        leaf = _shared_leaf_in_dim1(d)
        cardio, resp = d['nodes']['cardio'], d['nodes']['respiratory']
        mgmt = d['nodes']['management']

        entry_id = _add_entry(db, d['session'].id, 420,
                              [(leaf.id, 'primary', cardio.id),
                               (mgmt.id, 'primary', None)])

        assert entry_id in self._ids(
            db, exam.id, cardio.id, dim1, mgmt.id, dim2), (
            "The chosen parent's drill-down must list the entry."
        )
        assert entry_id not in self._ids(
            db, exam.id, resp.id, dim1, mgmt.id, dim2), (
            "Respiratory x Management listed an entry the student scoped "
            "to Cardiovascular. That is the §5.4 violation."
        )

    def test_unpinned_entry_is_listed_under_both_parents(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        leaf = _shared_leaf_in_dim1(d)
        cardio, resp = d['nodes']['cardio'], d['nodes']['respiratory']
        mgmt = d['nodes']['management']

        entry_id = _add_entry(db, d['session'].id, 421,
                              [(leaf.id, 'primary', None),
                               (mgmt.id, 'primary', None)])

        assert entry_id in self._ids(
            db, exam.id, cardio.id, dim1, mgmt.id, dim2)
        assert entry_id in self._ids(
            db, exam.id, resp.id, dim1, mgmt.id, dim2), (
            "A NULL context still reaches every ancestor (§5.3)."
        )

    def test_secondary_tags_are_not_listed(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        cardio, mgmt = d['nodes']['cardio'], d['nodes']['management']
        arrhythmia = d['nodes']['arrhythmia']

        entry_id = _add_entry(db, d['session'].id, 422,
                              [(arrhythmia.id, 'secondary', None),
                               (mgmt.id, 'secondary', None)])
        assert entry_id not in self._ids(
            db, exam.id, cardio.id, dim1, mgmt.id, dim2), (
            "A secondary 'also tested' tag was listed as a mistake at "
            "this intersection."
        )

    def test_another_exams_entries_are_not_listed(
        self, db_with_hierarchical_dim_exam,
    ):
        """rs was joined only to SELECT session_name -- no predicate."""
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        cardio, mgmt = d['nodes']['cardio'], d['nodes']['management']
        arrhythmia = d['nodes']['arrhythmia']

        other = db.create_exam_context(
            exam_name="Unrelated Exam I", exam_description="elsewhere")
        other_session = _session_for(db, other.id, db.user_id, "other exam")
        entry_id = _add_entry(db, other_session, 423,
                              [(arrhythmia.id, 'primary', None),
                               (mgmt.id, 'primary', None)])
        assert entry_id not in self._ids(
            db, exam.id, cardio.id, dim1, mgmt.id, dim2)

    def test_another_users_entries_are_not_listed(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        cardio, mgmt = d['nodes']['cardio'], d['nodes']['management']
        arrhythmia = d['nodes']['arrhythmia']

        someone_else = _session_for(db, exam.id, db.user_id + 1, "not mine")
        entry_id = _add_entry(db, someone_else, 424,
                              [(arrhythmia.id, 'primary', None),
                               (mgmt.id, 'primary', None)])
        assert entry_id not in self._ids(
            db, exam.id, cardio.id, dim1, mgmt.id, dim2), (
            "Another student's entry was listed in this student's "
            "drill-down."
        )

    def test_no_scoping_leak_without_children(
        self, db_with_hierarchical_dim_exam,
    ):
        """include_children=False shares the mapping_type/scoping fixes.

        It does not aggregate, so §5.4 is not asserted here -- only the
        two filters that apply to any counting query.
        """
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        arrhythmia, mgmt = d['nodes']['arrhythmia'], d['nodes']['management']

        secondary = _add_entry(db, d['session'].id, 425,
                               [(arrhythmia.id, 'secondary', None),
                                (mgmt.id, 'secondary', None)])
        someone_else = _session_for(db, exam.id, db.user_id + 1, "not mine")
        foreign = _add_entry(db, someone_else, 426,
                             [(arrhythmia.id, 'primary', None),
                              (mgmt.id, 'primary', None)])

        listed = self._ids(db, exam.id, arrhythmia.id, dim1, mgmt.id, dim2,
                           include_children=False)
        assert secondary not in listed
        assert foreign not in listed


class TestIntersectionEntriesIgnoresGraph:
    """Separate defect: the graph-first read, not §5.4.

    ``get_intersection_entries`` used to call
    ``_graph_get_intersection_entries`` and return its answer whenever it
    was non-empty. The graph's hierarchy comes from
    ``GraphMixin._etl_subjects``, built from the legacy
    ``subject_nodes.parent_id`` column, and ``EdgesMixin`` does no graph
    dual-write -- so a parent added via ``add_parent``/``add_edge`` never
    reaches it. A *partial* graph answer is truthy and was trusted, which
    silently bypassed every fix on the SQLite branch of the same
    function. The graph also has no ``mapping_type`` and no
    ``primary_parent_id`` on ``TAGGED_TO``, so §5.4 is unrepresentable
    there.
    """

    def test_a_partial_graph_answer_is_not_trusted(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions']
        cardio, mgmt = d['nodes']['cardio'], d['nodes']['management']
        arrhythmia = d['nodes']['arrhythmia']

        first = _add_entry(db, d['session'].id, 430,
                           [(arrhythmia.id, 'primary', None),
                            (mgmt.id, 'primary', None)])
        second = _add_entry(db, d['session'].id, 431,
                            [(arrhythmia.id, 'primary', None),
                             (mgmt.id, 'primary', None)])

        # Stand in for the real failure mode: the graph knows one of the
        # two entries (the one reachable through the legacy column) and
        # nothing about the other.
        calls = []

        def partial(*args, **kwargs):
            calls.append(args)
            return [first]

        db._graph_get_intersection_entries = partial

        # _graph_read_ready is a read-only property, and it is True on a
        # real profile. Force it so this test does not silently pass just
        # because the graph happened to be unavailable in the fixture.
        from unittest import mock
        with mock.patch.object(type(db), '_graph_read_ready',
                               property(lambda self: True)):
            got = {e['id'] for e in db.get_intersection_entries(
                exam.id, cardio.id, dim1, mgmt.id, dim2)}

        assert calls == [], (
            "The graph was consulted. SQLite is authoritative here; see "
            "the docstring on get_intersection_entries."
        )
        assert {first, second} <= got, (
            f"A partial graph answer was trusted and truncated the "
            f"result to {got}."
        )


class TestNonAggregatingDimensionSurfaces:
    """Three slot-exposed surfaces that all count directly.

    ``get_mistake_type_by_dimension``, ``get_temporal_trends_by_dimension``
    and ``get_triple_dimension_performance`` contain no recursive CTE and
    no ancestor walk -- each joins ``sn.id = esm.subject_node_id`` and
    groups by the tagged node. §5.4 is therefore inapplicable to all
    three (asserted below for the mistake-type one, which is the easiest
    to observe). What they were missing is orthogonal: a
    ``mapping_type`` filter and any ``review_sessions`` scoping at all.
    """

    @staticmethod
    def _mistake_counts(db, exam_id, dim_id):
        r = db.get_mistake_type_by_dimension(exam_id, dim_id)
        return {v['name']: sum(mt['count'] for mt in v['mistake_types'].values())
                for v in r['values']}

    @staticmethod
    def _tagged(db, exam, session_id, order, node_id, mapping_type='primary',
                ppid=None, tag_name="Knowledge Gap X"):
        tag = db.fetchone(
            "SELECT id FROM tags WHERE exam_context = ? AND tag_name = ?",
            (exam.exam_name, tag_name))
        if tag is None:
            created = db.create_tag(exam_context=exam.exam_name,
                                    tag_name=tag_name,
                                    tag_category='mistake_type')
            tag_id = created.id
        else:
            tag_id = tag['id']
        entry_id = _add_entry(db, session_id, order,
                              [(node_id, mapping_type, ppid)])
        db.execute(
            "INSERT INTO entry_tags (question_entry_id, tag_id) VALUES (?, ?)",
            (entry_id, tag_id))
        db.conn.commit()
        return entry_id

    def test_mistake_type_ignores_secondary_tags(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam, dim1 = d['db'], d['exam'], d['dimensions'][0]
        arrhythmia = d['nodes']['arrhythmia']

        base = self._mistake_counts(db, exam.id, dim1)
        self._tagged(db, exam, d['session'].id, 440, arrhythmia.id,
                     mapping_type='secondary')
        assert self._mistake_counts(db, exam.id, dim1) == base, (
            "A secondary subject tag produced a mistake-type bar."
        )

    def test_mistake_type_ignores_other_exams_and_users(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam, dim1 = d['db'], d['exam'], d['dimensions'][0]
        arrhythmia = d['nodes']['arrhythmia']

        base = self._mistake_counts(db, exam.id, dim1)
        other = db.create_exam_context(
            exam_name="Unrelated Exam M", exam_description="elsewhere")
        self._tagged(db, exam, _session_for(db, other.id, db.user_id, "x"),
                     441, arrhythmia.id)
        assert self._mistake_counts(db, exam.id, dim1) == base, (
            "There was no review_sessions join at all, so another exam's "
            "entry produced a bar here."
        )

        self._tagged(db, exam,
                     _session_for(db, exam.id, db.user_id + 1, "y"),
                     442, arrhythmia.id)
        assert self._mistake_counts(db, exam.id, dim1) == base, (
            "...and another user's entry did too."
        )

    def test_mistake_type_is_unmoved_by_pinning(
        self, db_with_hierarchical_dim_exam,
    ):
        """NOT a §5.4 defect -- pinned or not, the count is identical."""
        d = db_with_hierarchical_dim_exam
        db, exam, dim1 = d['db'], d['exam'], d['dimensions'][0]
        leaf = _shared_leaf_in_dim1(d)
        cardio, resp = d['nodes']['cardio'], d['nodes']['respiratory']

        entry_id = self._tagged(db, exam, d['session'].id, 443, leaf.id)
        seen = []
        for ppid in (None, cardio.id, resp.id):
            db.execute(
                "UPDATE entry_subject_mappings SET primary_parent_id = ? "
                "WHERE question_entry_id = ?", (ppid, entry_id))
            db.conn.commit()
            seen.append(self._mistake_counts(db, exam.id, dim1))
        assert seen[0] == seen[1] == seen[2], (
            "This surface does no ancestor walk, so primary_parent_id "
            "must not change its output."
        )

    def test_temporal_trends_ignore_secondary_tags_and_other_scopes(
        self, db_with_hierarchical_dim_exam,
    ):
        d = db_with_hierarchical_dim_exam
        db, exam, dim1 = d['db'], d['exam'], d['dimensions'][0]
        arrhythmia = d['nodes']['arrhythmia']

        def total(hierarchy_id=None):
            return db.get_temporal_trends_by_dimension(
                exam.id, dim1, hierarchy_id=hierarchy_id)['total']

        base_all, base_node = total(), total(arrhythmia.id)

        # Teeth check, and a regression guard for a separate defect: the
        # window was ``date('now', '-N weeks')``, and SQLite has no
        # 'weeks' modifier, so it was NULL and BOTH queries returned zero
        # rows for every input. Every filter assertion below was vacuous
        # until that was fixed -- 0 == 0 whatever you add.
        assert base_all > 0 and base_node > 0, (
            f"Both queries must see the fixture's entries before any "
            f"filter can be shown to work; got all={base_all}, "
            f"node={base_node}. Check the date window."
        )

        _add_entry(db, d['session'].id, 450,
                   [(arrhythmia.id, 'secondary', None)])
        assert (total(), total(arrhythmia.id)) == (base_all, base_node), (
            "A secondary tag moved the trend line."
        )

        other = db.create_exam_context(
            exam_name="Unrelated Exam T", exam_description="elsewhere")
        _add_entry(db, _session_for(db, other.id, db.user_id, "x"), 451,
                   [(arrhythmia.id, 'primary', None)])
        assert (total(), total(arrhythmia.id)) == (base_all, base_node), (
            "Another exam's entry moved the trend line -- there was no "
            "review_sessions join at all. Both the hierarchy_id and the "
            "all-nodes query need the predicate; a filter in only one of "
            "them passes assertions written against the other."
        )

        _add_entry(db, _session_for(db, exam.id, db.user_id + 1, "y"), 452,
                   [(arrhythmia.id, 'primary', None)])
        assert (total(), total(arrhythmia.id)) == (base_all, base_node), (
            "Another user's entry moved the trend line."
        )

    def test_triple_dimension_ignores_secondary_tags_and_other_scopes(
        self, db_with_multi_dim_exam,
    ):
        d = db_with_multi_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2, dim3 = d['dimensions']
        n = d['nodes']

        def combos():
            return {r['combination']: r['count']
                    for r in db.get_triple_dimension_performance(
                        exam.id, dim1, dim2, dim3)}

        base = combos()

        _add_entry(db, d['session'].id, 460,
                   [(n['neuro'].id, 'secondary', None),
                    (n['diagnosis'].id, 'secondary', None),
                    (n['inpatient'].id, 'secondary', None)])
        assert combos() == base, (
            "Secondary tags produced a 3-way combination. All three axes "
            "were unfiltered, so the error was multiplicative."
        )

        other = db.create_exam_context(
            exam_name="Unrelated Exam 3", exam_description="elsewhere")
        _add_entry(db, _session_for(db, other.id, db.user_id, "x"), 461,
                   [(n['neuro'].id, 'primary', None),
                    (n['diagnosis'].id, 'primary', None),
                    (n['inpatient'].id, 'primary', None)])
        assert combos() == base, (
            "Another exam's entry produced a combination -- the query had "
            "no review_sessions join."
        )

        _add_entry(db, _session_for(db, exam.id, db.user_id + 1, "y"), 462,
                   [(n['neuro'].id, 'primary', None),
                    (n['diagnosis'].id, 'primary', None),
                    (n['inpatient'].id, 'primary', None)])
        assert combos() == base, "Another user's entry produced a combination."


class TestInteractionEffectsDenominator:
    """``detect_interaction_effects``' own COUNT(*) denominator.

    It is a flat count over ``question_entries``, not a rollup, so §5.4 is
    inapplicable to it (the marginals it divides come from
    ``get_dimension_performance``, which does aggregate and does honour
    §5.4). It filtered ``exam_context_id`` but not ``user_id``.
    """

    def test_another_users_entries_do_not_inflate_the_denominator(
        self, db_with_multi_dim_exam,
    ):
        d = db_with_multi_dim_exam
        db, exam = d['db'], d['exam']
        dim1, dim2 = d['dimensions'][0], d['dimensions'][1]
        n = d['nodes']

        def effects():
            return {(e['dim_a_value'], e['dim_b_value']): e['expected']
                    for e in db.detect_interaction_effects(exam.id, dim1, dim2)}

        base = effects()
        assert base, "Fixture precondition: some interactions must exist."

        # 20 entries belonging to somebody else, same exam.
        someone_else = _session_for(db, exam.id, db.user_id + 1, "not mine")
        for i in range(20):
            _add_entry(db, someone_else, 470 + i,
                       [(n['neuro'].id, 'primary', None),
                        (n['diagnosis'].id, 'primary', None)])

        assert effects() == base, (
            "Another user's entries changed the expected counts. The "
            "denominator counted every entry in the exam regardless of "
            "who wrote it, so every interaction magnitude was wrong."
        )
