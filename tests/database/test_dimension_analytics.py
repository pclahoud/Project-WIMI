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
