"""
Tests for Per-Session Duration Override.
Tests migration, create session with duration, and serialization.
"""

import pytest
from datetime import date
from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    """Create a database with basic exam/session data."""
    db_path = tmp_path / "test_user.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")
    db._ensure_phase7_schema()

    exam = db.create_exam_context(
        exam_name="Test Exam",
        exam_description="For duration testing",
        hierarchy_levels=["System", "Topic"]
    )

    source = db.create_question_source(
        source_name="Test Source",
        source_type="textbook"
    )

    return {'db': db, 'exam': exam, 'source': source}


class TestSessionDurationMigration:
    """Test that the session_duration_minutes column migration works."""

    def test_column_exists(self, db):
        """session_duration_minutes column should exist after migration."""
        udb = db['db']
        columns = udb.fetchall("PRAGMA table_info(review_sessions)")
        column_names = {col['name'] for col in columns}
        assert 'session_duration_minutes' in column_names


class TestSessionDurationCreateSession:
    """Test creating sessions with various duration values."""

    def test_create_session_with_duration(self, db):
        """Creating a session with a duration stores it correctly."""
        udb, exam, source = db['db'], db['exam'], db['source']
        session = udb.create_review_session(
            exam_context_id=exam.id,
            total_questions=10,
            total_incorrect=3,
            question_source_id=source.id,
            date_encountered=date.today(),
            session_duration_minutes=45
        )
        assert session.session_duration_minutes == 45

    def test_create_session_with_null_duration(self, db):
        """Creating a session with None duration stores NULL."""
        udb, exam, source = db['db'], db['exam'], db['source']
        session = udb.create_review_session(
            exam_context_id=exam.id,
            total_questions=10,
            total_incorrect=3,
            question_source_id=source.id,
            date_encountered=date.today(),
            session_duration_minutes=None
        )
        assert session.session_duration_minutes is None

    def test_create_session_without_duration_param(self, db):
        """Creating a session without the duration param defaults to NULL."""
        udb, exam, source = db['db'], db['exam'], db['source']
        session = udb.create_review_session(
            exam_context_id=exam.id,
            total_questions=10,
            total_incorrect=3,
            question_source_id=source.id,
            date_encountered=date.today()
        )
        assert session.session_duration_minutes is None

    def test_session_dict_includes_duration(self, db):
        """The ReviewSession model should include session_duration_minutes."""
        udb, exam, source = db['db'], db['exam'], db['source']
        session = udb.create_review_session(
            exam_context_id=exam.id,
            total_questions=10,
            total_incorrect=3,
            question_source_id=source.id,
            date_encountered=date.today(),
            session_duration_minutes=60
        )
        # Re-fetch to verify round-trip
        fetched = udb.get_review_session(session.id)
        assert fetched.session_duration_minutes == 60
