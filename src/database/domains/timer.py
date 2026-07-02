"""WIMI Timer database operations."""

from typing import Optional

from ..exceptions import ValidationError


class TimerMixin:
    """Mixin for timer operations. Composed into UserDatabase."""

    def create_timer_round(self, session_id: int, duration_minutes: int) -> Optional['TimerRound']:
        """Create a new timer round for a session.

        Auto-ends any active round and auto-increments round_number.
        """
        from ..models import TimerRound

        with self.transaction():
            # End any active round first
            active = self.get_active_timer_round(session_id)
            if active:
                self.end_timer_round(active.id)

            # Determine next round number
            row = self.fetchone(
                "SELECT COALESCE(MAX(round_number), 0) AS max_rn "
                "FROM session_timer_rounds WHERE review_session_id = ?",
                (session_id,)
            )
            next_rn = (row['max_rn'] if row else 0) + 1

            cursor = self.execute("""
                INSERT INTO session_timer_rounds
                    (review_session_id, round_number, duration_minutes)
                VALUES (?, ?, ?)
            """, (session_id, next_rn, duration_minutes))

            return self.get_timer_round(cursor.lastrowid)

    def get_timer_round(self, round_id: int) -> Optional['TimerRound']:
        """Get a timer round by its ID."""
        from ..models import TimerRound
        row = self.fetchone(
            "SELECT * FROM session_timer_rounds WHERE id = ?", (round_id,)
        )
        return TimerRound.from_db_row(row) if row else None

    def get_active_timer_round(self, session_id: int) -> Optional['TimerRound']:
        """Get the latest active (not ended) round for a session."""
        from ..models import TimerRound
        row = self.fetchone(
            "SELECT * FROM session_timer_rounds "
            "WHERE review_session_id = ? AND ended_at IS NULL "
            "ORDER BY round_number DESC LIMIT 1",
            (session_id,)
        )
        return TimerRound.from_db_row(row) if row else None

    def get_timer_rounds(self, session_id: int) -> list:
        """Get all timer rounds for a session, ordered by round_number."""
        from ..models import TimerRound
        rows = self.fetchall(
            "SELECT * FROM session_timer_rounds "
            "WHERE review_session_id = ? ORDER BY round_number",
            (session_id,)
        )
        return [TimerRound.from_db_row(r) for r in rows]

    def update_timer_round(self, round_id: int, updates: dict) -> Optional['TimerRound']:
        """Update a timer round's editable fields.

        Args:
            round_id: The round to update
            updates: Dict with optional 'duration_minutes' key

        Returns:
            Updated TimerRound or None if not found
        """
        from ..models import TimerRound
        rnd = self.get_timer_round(round_id)
        if not rnd:
            return None

        set_clauses = []
        params = []

        if 'duration_minutes' in updates:
            dur = int(updates['duration_minutes'])
            if dur < 1:
                raise ValidationError("duration_minutes must be >= 1")
            set_clauses.append("duration_minutes = ?")
            params.append(dur)

        if 'actual_studied_seconds' in updates:
            secs = int(updates['actual_studied_seconds'])
            if secs < 0:
                raise ValidationError("actual_studied_seconds must be >= 0")
            set_clauses.append("actual_studied_seconds = ?")
            params.append(secs)

        if not set_clauses:
            return rnd

        params.append(round_id)
        with self.transaction():
            self.execute(
                f"UPDATE session_timer_rounds SET {', '.join(set_clauses)} WHERE id = ?",
                tuple(params)
            )
        return self.get_timer_round(round_id)

    def delete_timer_round(self, round_id: int) -> bool:
        """Delete a timer round.

        If no active rounds remain after deletion, clears session-level
        timer_paused_at to prevent stale state.

        Returns:
            True if a row was deleted, False if not found
        """
        rnd = self.get_timer_round(round_id)
        if not rnd:
            return False

        session_id = rnd.review_session_id

        with self.transaction():
            cursor = self.execute(
                "DELETE FROM session_timer_rounds WHERE id = ?",
                (round_id,)
            )

            # If no active rounds remain, clear session-level timer state
            remaining = self.fetchone(
                "SELECT COUNT(*) as cnt FROM session_timer_rounds "
                "WHERE review_session_id = ? AND ended_at IS NULL",
                (session_id,)
            )
            if remaining['cnt'] == 0:
                self.execute(
                    "UPDATE review_sessions SET timer_paused_at = NULL "
                    "WHERE id = ?",
                    (session_id,)
                )

            return cursor.rowcount > 0

    def end_timer_round(self, round_id: int) -> Optional['TimerRound']:
        """End a timer round, calculating actual_studied_seconds.

        If the round is paused, unpauses first. Idempotent — no-op if
        already ended.
        """
        rnd = self.get_timer_round(round_id)
        if not rnd or rnd.ended_at is not None:
            return rnd

        # Unpause first if paused
        if rnd.timer_paused_at:
            self.unpause_round_timer(round_id)
            rnd = self.get_timer_round(round_id)

        with self.transaction():
            self.execute("""
                UPDATE session_timer_rounds
                SET ended_at = datetime('now'),
                    actual_studied_seconds = MIN(
                        CAST((julianday('now') - julianday(started_at)) * 86400 AS INTEGER)
                            - total_break_seconds,
                        duration_minutes * 60
                    )
                WHERE id = ? AND ended_at IS NULL
            """, (round_id,))
        return self.get_timer_round(round_id)

    def pause_round_timer(self, round_id: int) -> Optional['TimerRound']:
        """Pause a timer round. Idempotent — no-op if already paused or ended."""
        rnd = self.get_timer_round(round_id)
        if not rnd or rnd.ended_at is not None or rnd.timer_paused_at is not None:
            return rnd

        with self.transaction():
            self.execute("""
                UPDATE session_timer_rounds
                SET timer_paused_at = datetime('now'),
                    actual_studied_seconds = MAX(0, MIN(
                        CAST((julianday('now') - julianday(started_at)) * 86400 AS INTEGER)
                            - total_break_seconds,
                        duration_minutes * 60
                    ))
                WHERE id = ? AND timer_paused_at IS NULL AND ended_at IS NULL
            """, (round_id,))
        return self.get_timer_round(round_id)

    def unpause_round_timer(self, round_id: int) -> Optional['TimerRound']:
        """Unpause a timer round, accumulating break seconds. No-op if not paused."""
        rnd = self.get_timer_round(round_id)
        if not rnd or not rnd.timer_paused_at:
            return rnd

        with self.transaction():
            self.execute("""
                UPDATE session_timer_rounds
                SET total_break_seconds = total_break_seconds +
                    CAST((julianday('now') - julianday(timer_paused_at)) * 86400 AS INTEGER),
                    timer_paused_at = NULL
                WHERE id = ? AND timer_paused_at IS NOT NULL
            """, (round_id,))
        return self.get_timer_round(round_id)
