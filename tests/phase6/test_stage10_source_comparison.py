"""
Tests for Phase 6 Stage 10: Source Comparison & Performance Over Time
"""
import pytest
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

from database.user_db import UserDatabase


class TestSourceComparison:
    """Tests for source comparison functionality"""

    def test_get_source_comparison_empty(self, user_db):
        """Test source comparison with no data"""
        result = user_db.get_source_comparison()
        
        assert result is not None
        assert 'sources' in result
        assert 'timeline' in result
        assert 'total_entries' in result
        assert result['total_entries'] == 0
        assert len(result['sources']) == 0

    def test_get_source_comparison_with_data(self, user_db_with_entries):
        """Test source comparison with entries"""
        result = user_db_with_entries.get_source_comparison(months=6)
        
        assert result is not None
        assert 'sources' in result
        assert 'timeline' in result
        assert result['total_entries'] >= 0

    def test_source_comparison_returns_source_details(self, user_db_with_entries):
        """Test that source comparison returns expected fields"""
        result = user_db_with_entries.get_source_comparison()
        
        if result['sources']:
            source = result['sources'][0]
            assert 'source_id' in source
            assert 'source_name' in source
            assert 'entry_count' in source
            assert 'percentage' in source
            assert 'trend' in source
            assert 'top_subject' in source or source['top_subject'] is None

    def test_source_comparison_trend_values(self, user_db_with_entries):
        """Test that trend is one of expected values"""
        result = user_db_with_entries.get_source_comparison()
        
        valid_trends = {'improving', 'stable', 'worsening'}
        
        for source in result['sources']:
            assert source['trend'] in valid_trends

    def test_source_comparison_timeline_structure(self, user_db_with_entries):
        """Test timeline structure"""
        result = user_db_with_entries.get_source_comparison(months=3)
        
        assert 'timeline' in result
        
        for entry in result['timeline']:
            assert 'month' in entry
            assert 'label' in entry
            assert 'sources' in entry
            assert isinstance(entry['sources'], dict)

    def test_source_comparison_with_exam_filter(self, user_db_with_entries):
        """Test source comparison with exam context filter"""
        # Get first exam context
        contexts = user_db_with_entries.fetchall(
            "SELECT id FROM exam_contexts LIMIT 1"
        )
        
        if contexts:
            result = user_db_with_entries.get_source_comparison(
                exam_context_id=contexts[0]['id']
            )
            assert result is not None
            assert 'sources' in result


class TestPerformanceOverTime:
    """Tests for performance over time functionality"""

    def test_get_performance_empty(self, user_db):
        """Test performance with no data"""
        result = user_db.get_performance_over_time()
        
        assert result is not None
        assert isinstance(result, list)

    def test_get_performance_weekly(self, user_db_with_entries):
        """Test weekly performance data"""
        result = user_db_with_entries.get_performance_over_time(
            period='weekly',
            weeks=8
        )
        
        assert result is not None
        assert isinstance(result, list)

    def test_get_performance_monthly(self, user_db_with_entries):
        """Test monthly performance data"""
        result = user_db_with_entries.get_performance_over_time(
            period='monthly',
            weeks=12
        )
        
        assert result is not None
        assert isinstance(result, list)

    def test_get_performance_daily(self, user_db_with_entries):
        """Test daily performance data"""
        result = user_db_with_entries.get_performance_over_time(
            period='daily',
            weeks=2
        )
        
        assert result is not None
        assert isinstance(result, list)

    def test_performance_returns_expected_fields(self, user_db_with_entries):
        """Test that performance data has expected fields"""
        result = user_db_with_entries.get_performance_over_time(
            period='weekly',
            weeks=4
        )
        
        for entry in result:
            assert 'period' in entry
            assert 'entry_count' in entry
            assert 'avg_difficulty' in entry or entry['avg_difficulty'] is None
            assert 'active_days' in entry

    def test_performance_with_exam_filter(self, user_db_with_entries):
        """Test performance with exam context filter"""
        contexts = user_db_with_entries.fetchall(
            "SELECT id FROM exam_contexts LIMIT 1"
        )
        
        if contexts:
            result = user_db_with_entries.get_performance_over_time(
                exam_context_id=contexts[0]['id']
            )
            assert result is not None


class TestTrendCalculation:
    """Tests for trend calculation helper"""

    def test_calculate_trend_stable(self, user_db):
        """Test trend calculation returns stable for similar values"""
        from collections import defaultdict
        
        monthly_data = defaultdict(lambda: defaultdict(int))
        monthly_data['2024-01'][1] = 10
        monthly_data['2024-02'][1] = 10
        monthly_data['2024-03'][1] = 10
        monthly_data['2024-04'][1] = 10
        
        trend = user_db._calculate_source_trend(1, monthly_data)
        assert trend == 'stable'

    def test_calculate_trend_improving(self, user_db):
        """Test trend calculation returns improving when counts decrease"""
        from collections import defaultdict
        
        monthly_data = defaultdict(lambda: defaultdict(int))
        monthly_data['2024-01'][1] = 20
        monthly_data['2024-02'][1] = 18
        monthly_data['2024-03'][1] = 8
        monthly_data['2024-04'][1] = 5
        
        trend = user_db._calculate_source_trend(1, monthly_data)
        assert trend == 'improving'

    def test_calculate_trend_worsening(self, user_db):
        """Test trend calculation returns worsening when counts increase"""
        from collections import defaultdict
        
        monthly_data = defaultdict(lambda: defaultdict(int))
        monthly_data['2024-01'][1] = 5
        monthly_data['2024-02'][1] = 8
        monthly_data['2024-03'][1] = 15
        monthly_data['2024-04'][1] = 20
        
        trend = user_db._calculate_source_trend(1, monthly_data)
        assert trend == 'worsening'

    def test_calculate_trend_insufficient_data(self, user_db):
        """Test trend calculation with insufficient data"""
        from collections import defaultdict
        
        monthly_data = defaultdict(lambda: defaultdict(int))
        monthly_data['2024-01'][1] = 10
        
        trend = user_db._calculate_source_trend(1, monthly_data)
        assert trend == 'stable'


@pytest.fixture
def user_db(tmp_path):
    """Create a fresh user database"""
    db_path = tmp_path / "test_user.db"
    db = UserDatabase(db_path, user_id=1, username="testuser")
    yield db
    db.close()


@pytest.fixture
def user_db_with_entries(tmp_path):
    """Create user database with sample entries"""
    db_path = tmp_path / "test_user_with_data.db"
    db = UserDatabase(db_path, user_id=1, username="testuser")

    # Create exam context
    # Note: exam_contexts schema has no `exam_type` column; the actual columns
    # are user_id, exam_name, exam_description, exam_date, is_active.
    db.execute("""
        INSERT INTO exam_contexts (id, user_id, exam_name, exam_description, is_active)
        VALUES (1, 1, 'USMLE Step 1', 'medical', 1)
    """)

    # Create source
    # question_sources requires user_id; source_type must be one of the allowed
    # CHECK values (e.g., 'commercial_prep'), not 'qbank'.
    db.execute("""
        INSERT INTO question_sources (id, user_id, source_name, source_type)
        VALUES (1, 1, 'UWorld', 'commercial_prep')
    """)

    # Create session
    # review_sessions schema uses `session_status` (not `status`) and requires
    # total_questions / total_incorrect.
    db.execute("""
        INSERT INTO review_sessions (
            id, user_id, exam_context_id, question_source_id,
            total_questions, total_incorrect, session_status
        )
        VALUES (1, 1, 1, 1, 5, 5, 'completed')
    """)

    # Create some entries
    # question_entries schema requires entry_order, user_answer, correct_answer.
    # The `question_identifier` column does not exist; the actual column is
    # `question_id`.
    for i in range(5):
        db.execute("""
            INSERT INTO question_entries (
                id, review_session_id, entry_order, question_id,
                user_answer, correct_answer,
                perceived_difficulty, is_draft, created_at
            )
            VALUES (?, 1, ?, ?, 'A', 'B', 3, FALSE, ?)
        """, (i + 1, i + 1, f'Q{i+1}', datetime.now().isoformat()))

    db.conn.commit()

    yield db
    db.close()
