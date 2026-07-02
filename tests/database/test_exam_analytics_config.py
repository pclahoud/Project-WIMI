"""
Tests for Per-Exam Analytics Profile.
Tests migration, get/update analytics config, and tag analytics dimension filter.
"""

import pytest
import json
from datetime import date
from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    """Create a database with exam, dimensions, subjects, and entries for analytics testing."""
    db_path = tmp_path / "test_user.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")
    db._ensure_phase7_schema()

    # Create exam context
    exam = db.create_exam_context(
        exam_name="Analytics Test Exam",
        exam_description="For analytics config testing",
        hierarchy_levels=["System", "Topic"]
    )

    # Create dimensions (create_dimension uses exam_id param and returns int)
    dim1_id = db.create_dimension(
        exam_id=exam.id,
        name="Clinical",
        display_order=1
    )
    dim2_id = db.create_dimension(
        exam_id=exam.id,
        name="Basic Science",
        display_order=2
    )

    # Create subjects in each dimension
    subj_clinical = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Cardiology",
        level_type="System",
        dimension_id=dim1_id
    )
    subj_basic = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Biochemistry",
        level_type="System",
        dimension_id=dim2_id
    )

    # Create source and session
    source = db.create_question_source(
        source_name="Test Source",
        source_type="textbook"
    )
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=10,
        total_incorrect=4,
        question_source_id=source.id,
        date_encountered=date.today()
    )

    # Create tags
    tag1 = db.create_tag(exam_context=exam.exam_name, tag_name="Knowledge Gap", tag_category="mistake_type")
    tag2 = db.create_tag(exam_context=exam.exam_name, tag_name="Silly Mistake", tag_category="mistake_type")

    # Create entries with subject mappings and tags
    entry1 = db.create_question_entry(
        review_session_id=session.id,
        user_answer="A",
        correct_answer="B",
        primary_subject_ids=[subj_clinical.id],
        tag_ids=[tag1.id]
    )
    entry2 = db.create_question_entry(
        review_session_id=session.id,
        user_answer="C",
        correct_answer="D",
        primary_subject_ids=[subj_basic.id],
        tag_ids=[tag2.id]
    )

    return {
        'db': db,
        'exam': exam,
        'dim1_id': dim1_id,
        'dim2_id': dim2_id,
        'subj_clinical': subj_clinical,
        'subj_basic': subj_basic,
        'session': session,
        'entry1': entry1,
        'entry2': entry2,
        'tag1': tag1,
        'tag2': tag2
    }


class TestAnalyticsConfigMigration:
    """Test that the analytics_config column migration works."""

    def test_column_exists(self, db):
        """analytics_config column should exist in exam_contexts."""
        udb = db['db']
        columns = udb.fetchall("PRAGMA table_info(exam_contexts)")
        column_names = {col['name'] for col in columns}
        assert 'analytics_config' in column_names


class TestGetExamAnalyticsConfig:
    """Test retrieving analytics config."""

    def test_get_config_null_returns_defaults(self, db):
        """Getting config when column is NULL should return defaults."""
        udb, exam = db['db'], db['exam']
        config = udb.get_exam_analytics_config(exam.id)

        assert config['default_dimension_id'] is None
        assert config['chart_visibility']['subject_sunburst'] is True
        assert config['chart_visibility']['tag_chart'] is True
        assert config['chart_visibility']['weight_analysis'] is True
        assert len(config['chart_visibility']) == 12

    def test_get_config_nonexistent_exam_raises(self, db):
        """Getting config for nonexistent exam should raise."""
        udb = db['db']
        with pytest.raises(Exception):
            udb.get_exam_analytics_config(99999)


class TestUpdateExamAnalyticsConfig:
    """Test updating analytics config."""

    def test_update_config_stores_and_returns(self, db):
        """Updating config should store and return the merged result."""
        udb, exam = db['db'], db['exam']
        updated = udb.update_exam_analytics_config(exam.id, {
            'default_dimension_id': db['dim1_id'],
            'chart_visibility': {'tag_chart': False}
        })

        assert updated['default_dimension_id'] == db['dim1_id']
        assert updated['chart_visibility']['tag_chart'] is False
        # Other visibility defaults should be preserved
        assert updated['chart_visibility']['subject_sunburst'] is True

    def test_partial_update_merges_with_defaults(self, db):
        """Partial update should merge with defaults, not replace."""
        udb, exam = db['db'], db['exam']

        # First update: set one chart to False
        udb.update_exam_analytics_config(exam.id, {
            'chart_visibility': {'activity_chart': False}
        })

        # Second update: set a different chart to False
        updated = udb.update_exam_analytics_config(exam.id, {
            'chart_visibility': {'streak_stats': False}
        })

        # Both should be False, rest should be True
        assert updated['chart_visibility']['activity_chart'] is False
        assert updated['chart_visibility']['streak_stats'] is False
        assert updated['chart_visibility']['subject_sunburst'] is True

    def test_update_config_round_trip(self, db):
        """Updated config should be retrievable."""
        udb, exam = db['db'], db['exam']
        udb.update_exam_analytics_config(exam.id, {
            'default_dimension_id': db['dim2_id']
        })

        config = udb.get_exam_analytics_config(exam.id)
        assert config['default_dimension_id'] == db['dim2_id']


class TestTagAnalyticsDimensionFilter:
    """Test tag analytics with dimension_id filter."""

    def test_tag_analytics_with_dimension_filter(self, db):
        """Filtering by dimension should only return tags for entries in that dimension."""
        udb, exam = db['db'], db['exam']

        # Filter to Clinical dimension (only entry1 has clinical subject)
        result = udb.get_tag_analytics(
            exam_context_id=exam.id,
            dimension_id=db['dim1_id']
        )
        tag_names = [t['name'] for t in result['top_tags']]
        assert 'Knowledge Gap' in tag_names
        assert 'Silly Mistake' not in tag_names

    def test_tag_analytics_without_dimension_filter(self, db):
        """Without dimension filter, all tags should be returned."""
        udb, exam = db['db'], db['exam']

        result = udb.get_tag_analytics(exam_context_id=exam.id)
        tag_names = [t['name'] for t in result['top_tags']]
        assert 'Knowledge Gap' in tag_names
        assert 'Silly Mistake' in tag_names
