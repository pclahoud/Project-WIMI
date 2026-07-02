"""WIMI Sessions database operations."""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from ..base_db import DatabaseIntegrityError
from ..exceptions import ValidationError
from app_logging import ErrorCategory


class SessionsMixin:
    """Mixin for session operations. Composed into UserDatabase."""

    def create_review_session(
        self,
        exam_context_id: int,
        total_questions: int,
        total_incorrect: int,
        question_source_id: Optional[int] = None,
        session_name: Optional[str] = None,
        date_encountered: Optional[date] = None,
        session_duration_minutes: Optional[int] = None
    ) -> 'ReviewSession':
        """
        Create a new review session.

        Args:
            exam_context_id: ID of the exam context
            total_questions: Total questions in the practice session
            total_incorrect: Number of incorrect answers
            question_source_id: Optional source ID
            session_name: Optional session name (auto-generated if None)
            date_encountered: Date of the practice session (defaults to today)

        Returns:
            ReviewSession object
        """
        from ..models import ReviewSession
        from ..exceptions import ReviewSessionError

        self._ensure_phase4_schema()

        # Validate exam context exists
        exam_context = self.get_exam_context_config(exam_context_id)
        if not exam_context:
            raise ReviewSessionError(f"Exam context {exam_context_id} not found")

        # Validate question source if provided
        if question_source_id:
            source = self.get_question_source(question_source_id)
            if not source:
                raise ReviewSessionError(f"Question source {question_source_id} not found")

        # Generate session name if not provided
        if not session_name:
            source_name = "Practice"
            if question_source_id:
                source = self.get_question_source(question_source_id)
                if source:
                    source_name = source.source_name
            encounter_date = date_encountered or date.today()
            session_name = f"{source_name} - {encounter_date.strftime('%b %d, %Y')}"

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO review_sessions (
                        user_id, exam_context_id, question_source_id,
                        session_name, date_encountered, total_questions, total_incorrect,
                        session_duration_minutes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.user_id, exam_context_id, question_source_id,
                    session_name,
                    (date_encountered or date.today()).isoformat(),
                    total_questions, total_incorrect,
                    session_duration_minutes
                ))

                session_id = cursor.lastrowid

                # Auto-create round 1 for timed sessions
                if session_duration_minutes:
                    self.execute("""
                        INSERT INTO session_timer_rounds
                            (review_session_id, round_number, duration_minutes)
                        VALUES (?, 1, ?)
                    """, (session_id, session_duration_minutes))

                if self.error_logger:
                    self.error_logger.info(
                        f"Created review session: {session_name} (ID: {session_id})",
                        category=ErrorCategory.DATABASE
                    )

                return self.get_review_session(session_id)

        except DatabaseIntegrityError as e:
            raise ReviewSessionError(f"Failed to create review session: {e}") from e

    def get_review_session(self, session_id: int) -> Optional['ReviewSession']:
        """Get review session by ID with exam and source names"""
        from ..models import ReviewSession

        row = self.fetchone("""
            SELECT rs.*, ec.exam_name, qs.source_name
            FROM review_sessions rs
            LEFT JOIN exam_contexts ec ON rs.exam_context_id = ec.id
            LEFT JOIN question_sources qs ON rs.question_source_id = qs.id
            WHERE rs.id = ?
        """, (session_id,))

        return ReviewSession.from_db_row(row) if row else None

    def get_review_sessions(
        self,
        exam_context_id: Optional[int] = None,
        include_completed: bool = True,
        limit: Optional[int] = None
    ) -> List['ReviewSession']:
        """
        Get review sessions for the user.

        Args:
            exam_context_id: Optional filter by exam context
            include_completed: Include completed sessions
            limit: Maximum number of sessions to return

        Returns:
            List of ReviewSession objects, most recent first
        """
        from ..models import ReviewSession

        self._ensure_phase4_schema()

        query = """
            SELECT rs.*, ec.exam_name, qs.source_name
            FROM review_sessions rs
            LEFT JOIN exam_contexts ec ON rs.exam_context_id = ec.id
            LEFT JOIN question_sources qs ON rs.question_source_id = qs.id
            WHERE rs.user_id = ?
        """
        params = [self.user_id]

        if exam_context_id:
            query += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)

        if not include_completed:
            query += " AND rs.session_status != 'completed'"

        query += " ORDER BY rs.last_activity_at DESC"

        if limit:
            query += f" LIMIT {limit}"

        rows = self.fetchall(query, tuple(params))
        return [ReviewSession.from_db_row(row) for row in rows]

    def update_review_session(
        self,
        session_id: int,
        **kwargs
    ) -> 'ReviewSession':
        """
        Update a review session.

        Args:
            session_id: ID of the session to update
            **kwargs: Fields to update

        Returns:
            Updated ReviewSession object
        """
        updates = []
        params = []

        allowed_fields = {
            'session_name', 'session_status', 'entries_completed', 'completed_at',
            'total_incorrect', 'total_questions', 'date_encountered', 'question_source_id'
        }

        # Validate total_questions >= total_incorrect if total_questions is being changed
        if 'total_questions' in kwargs:
            session = self.get_review_session(session_id)
            if session:
                current_incorrect = kwargs.get('total_incorrect', session.total_incorrect)
                if kwargs['total_questions'] < current_incorrect:
                    raise ValueError(
                        f"total_questions ({kwargs['total_questions']}) cannot be less than "
                        f"total_incorrect ({current_incorrect})"
                    )

        # Validate total_incorrect >= entries_completed if total_incorrect is being changed
        if 'total_incorrect' in kwargs:
            session = self.get_review_session(session_id)
            if session:
                current_completed = kwargs.get('entries_completed', session.entries_completed)
                if kwargs['total_incorrect'] < current_completed:
                    raise ValueError(
                        f"total_incorrect ({kwargs['total_incorrect']}) cannot be less than "
                        f"entries_completed ({current_completed})"
                    )

        for field, value in kwargs.items():
            if field in allowed_fields:
                if field == 'completed_at' and value:
                    updates.append(f"{field} = ?")
                    params.append(value.isoformat() if isinstance(value, datetime) else value)
                else:
                    updates.append(f"{field} = ?")
                    params.append(value)

        if not updates:
            return self.get_review_session(session_id)

        params.append(session_id)

        with self.transaction():
            self.execute(f"""
                UPDATE review_sessions
                SET {', '.join(updates)}
                WHERE id = ?
            """, tuple(params))

        return self.get_review_session(session_id)

    def increment_session_entries_completed(self, session_id: int) -> 'ReviewSession':
        """Increment the entries_completed count for a session"""
        with self.transaction():
            self.execute("""
                UPDATE review_sessions
                SET entries_completed = entries_completed + 1
                WHERE id = ?
            """, (session_id,))

            # Check if session is now complete
            session = self.get_review_session(session_id)
            if session and session.is_complete:
                self.execute("""
                    UPDATE review_sessions
                    SET session_status = 'completed', completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (session_id,))

        return self.get_review_session(session_id)

    def pause_session_timer(self, session_id: int) -> Optional['ReviewSession']:
        """Pause the session timer by recording the current UTC time.

        Idempotent: no-op if already paused (timer_paused_at IS NOT NULL).
        """
        with self.transaction():
            self.execute("""
                UPDATE review_sessions
                SET timer_paused_at = datetime('now')
                WHERE id = ? AND timer_paused_at IS NULL
            """, (session_id,))
        return self.get_review_session(session_id)

    def unpause_session_timer(self, session_id: int) -> Optional['ReviewSession']:
        """Unpause the session timer, accumulating break seconds.

        Calculates seconds between timer_paused_at and now, adds to
        total_break_seconds, and clears timer_paused_at. No-op if not paused.
        """
        session = self.get_review_session(session_id)
        if not session or not session.timer_paused_at:
            return session

        with self.transaction():
            self.execute("""
                UPDATE review_sessions
                SET total_break_seconds = total_break_seconds +
                    CAST((julianday('now') - julianday(timer_paused_at)) * 86400 AS INTEGER),
                    timer_paused_at = NULL
                WHERE id = ? AND timer_paused_at IS NOT NULL
            """, (session_id,))
        return self.get_review_session(session_id)

    def delete_review_session(self, session_id: int) -> bool:
        """
        Delete a review session and all its entries.

        Args:
            session_id: ID of the session to delete

        Returns:
            True if deleted successfully

        Raises:
            ReviewSessionNotFoundError: If session not found
        """
        from ..exceptions import ReviewSessionNotFoundError

        session = self.get_review_session(session_id)
        if not session:
            raise ReviewSessionNotFoundError(f"Review session {session_id} not found")

        with self.transaction():
            # Delete all entries (cascades to mappings, tags, media)
            self.execute(
                "DELETE FROM question_entries WHERE review_session_id = ?",
                (session_id,)
            )

            # Delete the session
            self.execute(
                "DELETE FROM review_sessions WHERE id = ?",
                (session_id,)
            )

            if self.error_logger:
                self.error_logger.info(
                    f"Deleted review session {session_id}",
                    category=ErrorCategory.DATABASE
                )

        return True
