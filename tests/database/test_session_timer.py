"""
Tests for Session Countdown Timer: break pause/unpause persistence.
Tests migration columns, pause/unpause methods, idempotency, and edge cases.
Also tests multi-round timer functionality (session_timer_rounds).
"""

import pytest
import time
from datetime import date
from database.user_db import UserDatabase
from database.exceptions import ValidationError


@pytest.fixture
def db(tmp_path):
    """Create a database with a review session for timer testing."""
    db_path = tmp_path / "test_user.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")
    db._ensure_phase7_schema()

    exam = db.create_exam_context(
        exam_name="Timer Test Exam",
        exam_description="For timer testing",
        hierarchy_levels=["System", "Topic"]
    )

    session = db.create_review_session(
        exam_context_id=exam.id,
        session_name="Timer Session",
        date_encountered=date.today(),
        total_questions=10,
        total_incorrect=5,
        session_duration_minutes=30
    )

    db._test_exam = exam
    db._test_session = session
    return db


class TestTimerMigration:
    """Test that migration adds the required columns."""

    def test_total_break_seconds_column_exists(self, db):
        columns = db.fetchall("PRAGMA table_info(review_sessions)")
        col_names = {col['name'] for col in columns}
        assert 'total_break_seconds' in col_names

    def test_timer_paused_at_column_exists(self, db):
        columns = db.fetchall("PRAGMA table_info(review_sessions)")
        col_names = {col['name'] for col in columns}
        assert 'timer_paused_at' in col_names

    def test_default_total_break_seconds_is_zero(self, db):
        session = db.get_review_session(db._test_session.id)
        assert session.total_break_seconds == 0

    def test_default_timer_paused_at_is_none(self, db):
        session = db.get_review_session(db._test_session.id)
        assert session.timer_paused_at is None


class TestPauseSessionTimer:
    """Test pause_session_timer method."""

    def test_pause_sets_timer_paused_at(self, db):
        session = db.pause_session_timer(db._test_session.id)
        assert session.timer_paused_at is not None

    def test_double_pause_is_idempotent(self, db):
        session1 = db.pause_session_timer(db._test_session.id)
        paused_at_1 = session1.timer_paused_at

        # Second pause should not change the timestamp
        time.sleep(0.1)
        session2 = db.pause_session_timer(db._test_session.id)
        assert session2.timer_paused_at == paused_at_1

    def test_pause_does_not_change_break_seconds(self, db):
        session = db.pause_session_timer(db._test_session.id)
        assert session.total_break_seconds == 0


class TestUnpauseSessionTimer:
    """Test unpause_session_timer method."""

    def test_unpause_clears_timer_paused_at(self, db):
        db.pause_session_timer(db._test_session.id)
        session = db.unpause_session_timer(db._test_session.id)
        assert session.timer_paused_at is None

    def test_unpause_accumulates_break_seconds(self, db):
        db.pause_session_timer(db._test_session.id)
        # Wait a moment so break duration > 0
        time.sleep(1.1)
        session = db.unpause_session_timer(db._test_session.id)
        assert session.total_break_seconds >= 1

    def test_unpause_without_pause_is_noop(self, db):
        session = db.unpause_session_timer(db._test_session.id)
        assert session.total_break_seconds == 0
        assert session.timer_paused_at is None

    def test_multiple_pause_unpause_accumulates(self, db):
        # First pause/unpause cycle
        db.pause_session_timer(db._test_session.id)
        time.sleep(1.1)
        session1 = db.unpause_session_timer(db._test_session.id)
        first_break = session1.total_break_seconds

        # Second pause/unpause cycle
        db.pause_session_timer(db._test_session.id)
        time.sleep(1.1)
        session2 = db.unpause_session_timer(db._test_session.id)
        assert session2.total_break_seconds > first_break


class TestSessionWithoutDuration:
    """Test that sessions without a duration still work with pause/unpause."""

    def test_pause_works_without_duration(self, db):
        session_no_dur = db.create_review_session(
            exam_context_id=db._test_exam.id,
            session_name="No Limit Session",
            date_encountered=date.today(),
            total_questions=5,
            total_incorrect=2
        )
        result = db.pause_session_timer(session_no_dur.id)
        assert result.timer_paused_at is not None


# =========================================================================
# Timer Rounds Tests
# =========================================================================


class TestTimerRoundsTable:
    """Test that the session_timer_rounds table exists and migration works."""

    def test_table_exists(self, db):
        tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {row['name'] for row in tables}
        assert 'session_timer_rounds' in table_names

    def test_migration_creates_round_1_for_timed_session(self, db):
        """The fixture's timed session should already have round 1 via create_review_session."""
        rounds = db.get_timer_rounds(db._test_session.id)
        assert len(rounds) == 1
        assert rounds[0].round_number == 1
        assert rounds[0].duration_minutes == 30

    def test_untimed_session_has_no_rounds(self, db):
        session = db.create_review_session(
            exam_context_id=db._test_exam.id,
            session_name="Untimed Session",
            date_encountered=date.today(),
            total_questions=5,
            total_incorrect=3
        )
        rounds = db.get_timer_rounds(session.id)
        assert len(rounds) == 0

    def test_migration_backfills_existing_timed_session(self, db):
        """Simulate an old DB without timer_rounds, then run migration."""
        # Create a second timed session (round 1 auto-created)
        session2 = db.create_review_session(
            exam_context_id=db._test_exam.id,
            session_name="Old Session",
            date_encountered=date.today(),
            total_questions=10,
            total_incorrect=5,
            session_duration_minutes=45
        )

        # Drop timer_rounds to simulate pre-migration state
        db.execute("DROP TABLE IF EXISTS session_timer_rounds")
        db.conn.commit()

        # Re-run migration — should recreate table and backfill
        table_names = {r['name'] for r in db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        db._ensure_timer_rounds_table(table_names)

        rounds = db.get_timer_rounds(session2.id)
        assert len(rounds) == 1
        assert rounds[0].round_number == 1
        assert rounds[0].duration_minutes == 45


class TestCreateTimerRound:
    """Test create_timer_round and auto-creation on session creation."""

    def test_auto_creates_round_1(self, db):
        active = db.get_active_timer_round(db._test_session.id)
        assert active is not None
        assert active.round_number == 1
        assert active.is_active

    def test_create_second_round(self, db):
        rnd2 = db.create_timer_round(db._test_session.id, 15)
        assert rnd2.round_number == 2
        assert rnd2.duration_minutes == 15
        assert rnd2.is_active

    def test_auto_ends_previous_round(self, db):
        rnd1 = db.get_active_timer_round(db._test_session.id)
        db.create_timer_round(db._test_session.id, 20)
        rnd1_after = db.get_timer_round(rnd1.id)
        assert rnd1_after.ended_at is not None

    def test_round_number_increments(self, db):
        db.create_timer_round(db._test_session.id, 10)
        rnd3 = db.create_timer_round(db._test_session.id, 10)
        assert rnd3.round_number == 3

    def test_round_to_dict(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        d = rnd.to_dict()
        assert d['id'] == rnd.id
        assert d['round_number'] == 1
        assert d['duration_minutes'] == 30
        assert d['ended_at'] is None


class TestGetActiveTimerRound:
    """Test get_active_timer_round."""

    def test_returns_active_round(self, db):
        active = db.get_active_timer_round(db._test_session.id)
        assert active is not None
        assert active.ended_at is None

    def test_returns_none_when_all_ended(self, db):
        active = db.get_active_timer_round(db._test_session.id)
        db.end_timer_round(active.id)
        assert db.get_active_timer_round(db._test_session.id) is None

    def test_returns_none_for_untimed_session(self, db):
        session = db.create_review_session(
            exam_context_id=db._test_exam.id,
            session_name="Untimed",
            date_encountered=date.today(),
            total_questions=5,
            total_incorrect=2
        )
        assert db.get_active_timer_round(session.id) is None


class TestGetTimerRounds:
    """Test get_timer_rounds returns all rounds in order."""

    def test_returns_all_rounds_ordered(self, db):
        db.create_timer_round(db._test_session.id, 10)
        db.create_timer_round(db._test_session.id, 15)
        rounds = db.get_timer_rounds(db._test_session.id)
        assert len(rounds) == 3
        assert [r.round_number for r in rounds] == [1, 2, 3]


class TestEndTimerRound:
    """Test end_timer_round."""

    def test_sets_ended_at(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        ended = db.end_timer_round(rnd.id)
        assert ended.ended_at is not None

    def test_calculates_studied_seconds(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        # Sleep briefly so actual_studied_seconds > 0
        time.sleep(0.5)
        ended = db.end_timer_round(rnd.id)
        assert ended.actual_studied_seconds >= 0

    def test_idempotent_end(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        ended1 = db.end_timer_round(rnd.id)
        ended2 = db.end_timer_round(rnd.id)
        assert ended1.ended_at == ended2.ended_at

    def test_end_handles_paused_state(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        db.pause_round_timer(rnd.id)
        ended = db.end_timer_round(rnd.id)
        assert ended.ended_at is not None
        assert ended.timer_paused_at is None  # unpause happened first

    def test_studied_seconds_capped_at_duration(self, db):
        """actual_studied_seconds should not exceed duration_minutes * 60."""
        rnd = db.get_active_timer_round(db._test_session.id)
        ended = db.end_timer_round(rnd.id)
        assert ended.actual_studied_seconds <= rnd.duration_minutes * 60


class TestPauseUnpauseRoundTimer:
    """Test pause_round_timer and unpause_round_timer."""

    def test_pause_sets_timer_paused_at(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        paused = db.pause_round_timer(rnd.id)
        assert paused.timer_paused_at is not None

    def test_double_pause_is_idempotent(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        p1 = db.pause_round_timer(rnd.id)
        time.sleep(0.1)
        p2 = db.pause_round_timer(rnd.id)
        assert p1.timer_paused_at == p2.timer_paused_at

    def test_unpause_clears_timer_paused_at(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        db.pause_round_timer(rnd.id)
        unpaused = db.unpause_round_timer(rnd.id)
        assert unpaused.timer_paused_at is None

    def test_unpause_accumulates_break_seconds(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        db.pause_round_timer(rnd.id)
        time.sleep(1.1)
        unpaused = db.unpause_round_timer(rnd.id)
        assert unpaused.total_break_seconds >= 1

    def test_unpause_without_pause_is_noop(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        result = db.unpause_round_timer(rnd.id)
        assert result.total_break_seconds == 0
        assert result.timer_paused_at is None

    def test_pause_ended_round_is_noop(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        db.end_timer_round(rnd.id)
        result = db.pause_round_timer(rnd.id)
        assert result.timer_paused_at is None  # unchanged — no-op

    def test_multiple_pause_unpause_accumulates(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        db.pause_round_timer(rnd.id)
        time.sleep(1.1)
        u1 = db.unpause_round_timer(rnd.id)
        first = u1.total_break_seconds

        db.pause_round_timer(rnd.id)
        time.sleep(1.1)
        u2 = db.unpause_round_timer(rnd.id)
        assert u2.total_break_seconds > first


class TestUpdateDeleteTimerRound:
    """Tests for update_timer_round and delete_timer_round."""

    def test_update_timer_round_duration(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        updated = db.update_timer_round(rnd.id, {'duration_minutes': 45})
        assert updated is not None
        assert updated.duration_minutes == 45

    def test_update_timer_round_invalid(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        with pytest.raises(ValidationError):
            db.update_timer_round(rnd.id, {'duration_minutes': 0})

    def test_update_timer_round_nonexistent(self, db):
        result = db.update_timer_round(99999, {'duration_minutes': 10})
        assert result is None

    def test_delete_timer_round(self, db):
        rnd = db.get_active_timer_round(db._test_session.id)
        assert db.delete_timer_round(rnd.id) is True
        assert db.get_timer_round(rnd.id) is None

    def test_delete_timer_round_nonexistent(self, db):
        assert db.delete_timer_round(99999) is False

    def test_delete_preserves_other_rounds(self, db):
        # End current round and create a second one
        rnd1 = db.get_active_timer_round(db._test_session.id)
        db.end_timer_round(rnd1.id)
        rnd2 = db.create_timer_round(db._test_session.id, 20)

        # Delete the first round
        db.delete_timer_round(rnd1.id)

        # Second round should still exist
        remaining = db.get_timer_rounds(db._test_session.id)
        assert len(remaining) == 1
        assert remaining[0].id == rnd2.id

    def test_delete_all_rounds_clears_session_timer_state(self, db):
        """Deleting all rounds should clear session-level timer_paused_at."""
        session_id = db._test_session.id
        rnd = db.get_active_timer_round(session_id)

        # Pause the session so session-level timer_paused_at is set
        db.pause_session_timer(session_id)
        session = db.fetchone(
            "SELECT timer_paused_at FROM review_sessions WHERE id = ?",
            (session_id,)
        )
        assert session['timer_paused_at'] is not None

        # Delete the only round
        db.delete_timer_round(rnd.id)

        # Session-level timer_paused_at should be cleared
        session = db.fetchone(
            "SELECT timer_paused_at FROM review_sessions WHERE id = ?",
            (session_id,)
        )
        assert session['timer_paused_at'] is None

    def test_delete_active_round_clears_session_state(self, db):
        """Delete the only active (paused) round — session state should clear."""
        session_id = db._test_session.id
        rnd1 = db.get_active_timer_round(session_id)

        # End round 1, create round 2
        db.end_timer_round(rnd1.id)
        rnd2 = db.create_timer_round(session_id, 15)

        # Pause the session timer (sets session-level timer_paused_at)
        db.pause_session_timer(session_id)

        # Delete round 2 (the only active round)
        db.delete_timer_round(rnd2.id)

        # No active rounds remain — session state should be cleared
        session = db.fetchone(
            "SELECT timer_paused_at FROM review_sessions WHERE id = ?",
            (session_id,)
        )
        assert session['timer_paused_at'] is None

    def test_delete_ended_round_preserves_active_state(self, db):
        """Deleting an ended round while another is active should preserve state."""
        session_id = db._test_session.id
        rnd1 = db.get_active_timer_round(session_id)

        # End round 1, create round 2 (active)
        db.end_timer_round(rnd1.id)
        rnd2 = db.create_timer_round(session_id, 20)

        # Pause the session timer (sets session-level timer_paused_at)
        db.pause_session_timer(session_id)

        # Delete the ended round 1
        db.delete_timer_round(rnd1.id)

        # Active round 2 still exists — session state should NOT be cleared
        session = db.fetchone(
            "SELECT timer_paused_at FROM review_sessions WHERE id = ?",
            (session_id,)
        )
        assert session['timer_paused_at'] is not None

        # Round 2 should still be there
        assert db.get_timer_round(rnd2.id) is not None


class TestTimerHotkeyPreferences:
    """Tests for timer hotkey preference columns."""

    def test_default_hotkey_values(self, db):
        prefs = db.get_preferences()
        assert prefs.hotkey_timer_pause_resume == 'Alt+P'
        assert prefs.hotkey_timer_new_round == 'Alt+N'
        assert prefs.hotkey_timer_end_round == 'Alt+E'

    def test_update_hotkey_preference(self, db):
        db.update_preferences(hotkey_timer_pause_resume='Ctrl+Shift+P')
        prefs = db.get_preferences()
        assert prefs.hotkey_timer_pause_resume == 'Ctrl+Shift+P'
        # Others unchanged
        assert prefs.hotkey_timer_new_round == 'Alt+N'
        assert prefs.hotkey_timer_end_round == 'Alt+E'

    def test_clear_hotkey(self, db):
        db.update_preferences(hotkey_timer_new_round='')
        prefs = db.get_preferences()
        assert prefs.hotkey_timer_new_round == ''

    def test_migration_adds_hotkey_columns(self, tmp_path):
        """Verify migration adds columns to an existing database without them."""
        db_path = tmp_path / "migration_test.db"
        db = UserDatabase(str(db_path), user_id=1, username="migrationuser")
        columns = db.fetchall("PRAGMA table_info(user_preferences)")
        col_names = {col['name'] for col in columns}
        assert 'hotkey_timer_pause_resume' in col_names
        assert 'hotkey_timer_new_round' in col_names
        assert 'hotkey_timer_end_round' in col_names
