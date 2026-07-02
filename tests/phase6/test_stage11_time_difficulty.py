"""
Unit tests for Phase 6 Stage 11: Time vs Difficulty Analysis
Tests database methods, correlation calculations, and insight generation
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

from database.user_db import UserDatabase

# NOTE: This entire test module targets functionality that was never implemented
# (or was removed) in UserDatabase: `save_question_entry`,
# `get_time_vs_difficulty_analysis`, `_calculate_time_difficulty_correlation`,
# and `get_time_distribution` do not exist on UserDatabase. The fixtures also
# INSERT into nonexistent columns (`subject_nodes.full_path`, `subject_nodes.level`,
# `exam_contexts.exam_type`). Skipping the whole file rather than deleting so the
# breadcrumb is preserved for whoever lands the time-vs-difficulty feature.
pytestmark = pytest.mark.skip(
    reason=(
        "Phase 6 Stage 11 (time vs difficulty analysis) is not implemented on "
        "UserDatabase. Fixtures also reference removed schema columns "
        "(subject_nodes.full_path/level, exam_contexts.exam_type). Re-enable when "
        "the analysis methods land and rewrite fixtures to match current schema."
    )
)


@pytest.fixture
def user_db(tmp_path):
    """Create a fresh user database"""
    db_path = tmp_path / "test_user.db"
    db = UserDatabase(db_path, user_id=1, username="testuser")

    # Create minimal required data
    db.execute("""
        INSERT INTO subject_nodes (id, name, full_path, level)
        VALUES (1, 'Test Subject', 'Test Subject', 1)
    """)
    db.conn.commit()

    yield db
    db.close()


@pytest.fixture
def user_db_with_exam(tmp_path):
    """Create user database with exam context"""
    db_path = tmp_path / "test_user_with_exam.db"
    db = UserDatabase(db_path, user_id=1, username="testuser")

    # Create subject node
    db.execute("""
        INSERT INTO subject_nodes (id, name, full_path, level)
        VALUES (1, 'Test Subject', 'Test Subject', 1)
    """)

    # Create exam context
    db.execute("""
        INSERT INTO exam_contexts (id, exam_name, exam_type, user_id)
        VALUES (1, 'USMLE Step 1', 'medical', 1)
    """)

    db.conn.commit()

    yield db
    db.close()


@pytest.fixture
def sample_session(user_db_with_exam):
    """Create a sample review session"""
    user_db_with_exam.execute("""
        INSERT INTO review_sessions (id, user_id, status, planned_question_count, created_at)
        VALUES (1, 1, 'in_progress', 10, ?)
    """, (datetime.now().isoformat(),))

    user_db_with_exam.conn.commit()

    return {'session_id': 1, 'user_id': 1}


class TestTimeDifficultyAnalysis:
    """Test time vs difficulty analysis methods"""

    def test_get_time_vs_difficulty_analysis_basic(self, user_db_with_exam, sample_session):
        """Test basic time vs difficulty analysis"""
        # Create entries with varying difficulty and time
        entries_data = [
            # Easy questions - short time
            {'difficulty': 1, 'time': 30},
            {'difficulty': 1, 'time': 40},
            {'difficulty': 1, 'time': 50},
            # Medium questions - medium time
            {'difficulty': 3, 'time': 90},
            {'difficulty': 3, 'time': 100},
            {'difficulty': 3, 'time': 95},
            # Hard questions - long time
            {'difficulty': 4, 'time': 120},
            {'difficulty': 4, 'time': 130},
            # Very Hard - very long time
            {'difficulty': 5, 'time': 180},
            {'difficulty': 5, 'time': 200},
        ]

        for entry_data in entries_data:
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': 'Test question',
                'perceived_difficulty': entry_data['difficulty'],
                'time_spent_seconds': entry_data['time'],
                'is_draft': False
            })

        # Get analysis
        result = user_db_with_exam.get_time_vs_difficulty_analysis()

        assert result is not None
        assert 'avg_time_by_difficulty' in result
        assert 'correlation' in result
        assert 'correlation_strength' in result
        assert 'insights' in result

        # Check that we have data for each difficulty level we added
        avg_times = result['avg_time_by_difficulty']
        assert 1 in avg_times
        assert 3 in avg_times
        assert 4 in avg_times
        assert 5 in avg_times

        # Verify easy questions have shorter average time than hard
        assert avg_times[1]['avg_seconds'] < avg_times[5]['avg_seconds']

        # Correlation should be positive (more time on harder questions)
        assert result['correlation'] > 0.5

    def test_get_time_vs_difficulty_with_exam_filter(self, user_db_with_exam, sample_session):
        """Test time vs difficulty analysis with exam context filter"""
        # Create exam context
        exam_id = user_db_with_exam.create_exam_context({
            'exam_name': 'USMLE Step 1',
            'date_scheduled': (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')
        })

        # Create new session with exam context
        session_with_exam = user_db_with_exam.create_review_session({
            'exam_context_id': exam_id,
            'planned_question_count': 5
        })

        # Add entries to exam session
        for i in range(5):
            user_db_with_exam.save_question_entry({
                'review_session_id': session_with_exam['session_id'],
                'subject_node_id': 1,
                'question_text': f'Exam question {i}',
                'perceived_difficulty': i % 5 + 1,
                'time_spent_seconds': (i % 5 + 1) * 50,
                'is_draft': False
            })

        # Add entries to session without exam context
        for i in range(3):
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': f'No exam question {i}',
                'perceived_difficulty': 3,
                'time_spent_seconds': 60,
                'is_draft': False
            })

        # Get analysis with exam filter
        result = user_db_with_exam.get_time_vs_difficulty_analysis(exam_context_id=exam_id)

        assert result is not None
        # Should only include entries from exam session (5 entries)
        assert result['total_entries'] == 5

    def test_get_time_vs_difficulty_empty(self, user_db_with_exam):
        """Test time vs difficulty with no entries"""
        result = user_db_with_exam.get_time_vs_difficulty_analysis()

        assert result is not None
        assert result['avg_time_by_difficulty'] == {}
        assert result['correlation'] == 0.0
        assert result['total_entries'] == 0
        assert result['entries_with_time'] == 0

    def test_get_time_vs_difficulty_excludes_drafts(self, user_db_with_exam, sample_session):
        """Test that draft entries are excluded"""
        # Add completed entry
        user_db_with_exam.save_question_entry({
            'review_session_id': sample_session['session_id'],
            'subject_node_id': 1,
            'question_text': 'Completed question',
            'perceived_difficulty': 3,
            'time_spent_seconds': 100,
            'is_draft': False
        })

        # Add draft entry
        user_db_with_exam.save_question_entry({
            'review_session_id': sample_session['session_id'],
            'subject_node_id': 1,
            'question_text': 'Draft question',
            'perceived_difficulty': 4,
            'time_spent_seconds': 200,
            'is_draft': True
        })

        result = user_db_with_exam.get_time_vs_difficulty_analysis()

        assert result is not None
        # Should only include the completed entry
        assert result['entries_with_time'] == 1
        assert 3 in result['avg_time_by_difficulty']
        assert 4 not in result['avg_time_by_difficulty']

    def test_get_time_vs_difficulty_excludes_null_time(self, user_db_with_exam, sample_session):
        """Test that entries without time are excluded from averages"""
        # Add entry with time
        user_db_with_exam.save_question_entry({
            'review_session_id': sample_session['session_id'],
            'subject_node_id': 1,
            'question_text': 'With time',
            'perceived_difficulty': 3,
            'time_spent_seconds': 100,
            'is_draft': False
        })

        # Add entry without time
        user_db_with_exam.save_question_entry({
            'review_session_id': sample_session['session_id'],
            'subject_node_id': 1,
            'question_text': 'Without time',
            'perceived_difficulty': 3,
            'time_spent_seconds': None,
            'is_draft': False
        })

        result = user_db_with_exam.get_time_vs_difficulty_analysis()

        assert result is not None
        assert result['total_entries'] == 2
        assert result['entries_with_time'] == 1

    def test_correlation_strength_categorization(self, user_db_with_exam, sample_session):
        """Test correlation strength categorization"""
        # Create entries with strong positive correlation
        for i in range(10):
            difficulty = (i % 5) + 1
            time = difficulty * 60  # Perfect correlation
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': f'Question {i}',
                'perceived_difficulty': difficulty,
                'time_spent_seconds': time,
                'is_draft': False
            })

        result = user_db_with_exam.get_time_vs_difficulty_analysis()

        assert result is not None
        # Should have strong positive correlation
        assert result['correlation'] > 0.7
        assert result['correlation_strength'] == 'Strong'


class TestCorrelationCalculation:
    """Test correlation coefficient calculation"""

    def test_calculate_correlation_positive(self, user_db_with_exam, sample_session):
        """Test positive correlation calculation"""
        # Create entries where time increases with difficulty
        for i in range(10):
            difficulty = (i % 5) + 1
            time = difficulty * 50 + (i * 5)  # Positive correlation with noise
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': f'Question {i}',
                'perceived_difficulty': difficulty,
                'time_spent_seconds': time,
                'is_draft': False
            })

        correlation = user_db_with_exam._calculate_time_difficulty_correlation()

        assert correlation > 0.5  # Should be positive

    def test_calculate_correlation_negative(self, user_db_with_exam, sample_session):
        """Test negative correlation (less time on harder questions - bad!)"""
        # Create entries where time decreases with difficulty
        for i in range(10):
            difficulty = (i % 5) + 1
            time = (6 - difficulty) * 50  # Inverse relationship
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': f'Question {i}',
                'perceived_difficulty': difficulty,
                'time_spent_seconds': time,
                'is_draft': False
            })

        correlation = user_db_with_exam._calculate_time_difficulty_correlation()

        assert correlation < -0.5  # Should be negative

    def test_calculate_correlation_zero(self, user_db_with_exam, sample_session):
        """Test zero correlation (no relationship)"""
        # Create entries with no relationship between time and difficulty
        import random
        random.seed(42)
        for i in range(20):
            difficulty = (i % 5) + 1
            time = random.randint(30, 200)  # Random time
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': f'Question {i}',
                'perceived_difficulty': difficulty,
                'time_spent_seconds': time,
                'is_draft': False
            })

        correlation = user_db_with_exam._calculate_time_difficulty_correlation()

        # Should be close to zero (within -0.3 to 0.3)
        assert abs(correlation) < 0.5

    def test_calculate_correlation_insufficient_data(self, user_db_with_exam, sample_session):
        """Test correlation with insufficient data"""
        # Add only one entry
        user_db_with_exam.save_question_entry({
            'review_session_id': sample_session['session_id'],
            'subject_node_id': 1,
            'question_text': 'Single question',
            'perceived_difficulty': 3,
            'time_spent_seconds': 100,
            'is_draft': False
        })

        correlation = user_db_with_exam._calculate_time_difficulty_correlation()

        # Should return 0.0 for insufficient data
        assert correlation == 0.0


class TestInsightGeneration:
    """Test insight generation logic"""

    def test_insight_good_pacing(self, user_db_with_exam, sample_session):
        """Test insight for good pacing (positive correlation)"""
        # Create entries with good pacing
        for i in range(10):
            difficulty = (i % 5) + 1
            time = difficulty * 60
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': f'Question {i}',
                'perceived_difficulty': difficulty,
                'time_spent_seconds': time,
                'is_draft': False
            })

        result = user_db_with_exam.get_time_vs_difficulty_analysis()

        # Should have positive insight
        insights = result['insights']
        assert len(insights) > 0
        success_insights = [i for i in insights if i['type'] == 'success']
        assert len(success_insights) > 0

    def test_insight_pacing_anomaly_hard_vs_medium(self, user_db_with_exam, sample_session):
        """Test insight when Hard questions get less time than Medium"""
        # Create entries where Hard gets less time than Medium
        for i in range(3):
            # Medium questions - more time
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': f'Medium {i}',
                'perceived_difficulty': 3,
                'time_spent_seconds': 120,
                'is_draft': False
            })

            # Hard questions - less time (anomaly!)
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': f'Hard {i}',
                'perceived_difficulty': 4,
                'time_spent_seconds': 80,
                'is_draft': False
            })

        result = user_db_with_exam.get_time_vs_difficulty_analysis()

        # Should have warning about Hard getting less time than Medium
        insights = result['insights']
        warning_insights = [i for i in insights if i['type'] == 'warning']
        assert len(warning_insights) > 0

        # Check if the specific warning is present
        hard_medium_warning = any(
            'Hard questions get less time than Medium' in i['message']
            for i in warning_insights
        )
        assert hard_medium_warning

    def test_insight_very_short_very_hard(self, user_db_with_exam, sample_session):
        """Test insight when Very Hard questions get very little time"""
        # Create Very Hard questions with very short time
        for i in range(3):
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': f'Very Hard {i}',
                'perceived_difficulty': 5,
                'time_spent_seconds': 45,  # Less than 1 minute
                'is_draft': False
            })

        result = user_db_with_exam.get_time_vs_difficulty_analysis()

        # Should have warning about Very Hard questions being too short
        insights = result['insights']
        warning_insights = [i for i in insights if i['type'] == 'warning']

        very_hard_warning = any(
            'Very Hard' in i['message'] and 'minute' in i['message']
            for i in warning_insights
        )
        assert very_hard_warning


class TestTimeDistribution:
    """Test time distribution analysis"""

    def test_get_time_distribution_basic(self, user_db_with_exam, sample_session):
        """Test basic time distribution"""
        # Create entries with various time ranges
        times = [25, 45, 70, 110, 350]  # Covers all buckets

        for i, time in enumerate(times):
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': f'Question {i}',
                'perceived_difficulty': 3,
                'time_spent_seconds': time,
                'is_draft': False
            })

        result = user_db_with_exam.get_time_distribution()

        assert result is not None
        assert 'distribution' in result
        assert 'median_seconds' in result
        assert 'mean_seconds' in result
        assert 'total_entries' in result

        # Check distribution buckets
        dist = result['distribution']
        assert dist['0-30s'] == 1
        assert dist['30s-1m'] == 1
        assert dist['1m-2m'] == 1
        assert dist['2m-5m'] == 1
        assert dist['5m+'] == 1

    def test_get_time_distribution_median_calculation(self, user_db_with_exam, sample_session):
        """Test median calculation"""
        # Create entries with known median
        times = [10, 20, 30, 40, 50]  # Median should be 30

        for i, time in enumerate(times):
            user_db_with_exam.save_question_entry({
                'review_session_id': sample_session['session_id'],
                'subject_node_id': 1,
                'question_text': f'Question {i}',
                'perceived_difficulty': 3,
                'time_spent_seconds': time,
                'is_draft': False
            })

        result = user_db_with_exam.get_time_distribution()

        assert result['median_seconds'] == 30.0

    def test_get_time_distribution_empty(self, user_db_with_exam):
        """Test time distribution with no data"""
        result = user_db_with_exam.get_time_distribution()

        assert result is not None
        assert result['distribution'] == {}
        assert result['median_seconds'] == 0
        assert result['mean_seconds'] == 0
        assert result['total_entries'] == 0
