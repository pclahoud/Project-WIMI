"""WIMI Review Session bridge operations."""
import json
from datetime import date

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class SessionBridgeMixin:
    """Bridge mixin for review session operations. Composed into DatabaseBridge."""

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createReviewSession(self, session_data_json: str) -> str:
        """
        Create a new review session.

        Args:
            session_data_json: JSON string with session data

        Returns:
            JSON response with created session
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = json.loads(session_data_json)

            date_encountered = None
            if data.get('date_encountered'):
                date_encountered = date.fromisoformat(data['date_encountered'])

            duration = data.get('session_duration_minutes')
            if duration is not None:
                duration = int(duration) if duration else None
                if duration == 0:
                    duration = None

            session = self.user_db.create_review_session(
                exam_context_id=data['exam_context_id'],
                question_source_id=data.get('question_source_id'),
                session_name=data.get('session_name'),
                date_encountered=date_encountered,
                total_questions=data['total_questions'],
                total_incorrect=data['total_incorrect'],
                session_duration_minutes=duration
            )

            return serialize_response(True, data={
                'id': session.id,
                'user_id': session.user_id,
                'exam_context_id': session.exam_context_id,
                'question_source_id': session.question_source_id,
                'session_name': session.session_name,
                'date_encountered': session.date_encountered,
                'total_questions': session.total_questions,
                'total_incorrect': session.total_incorrect,
                'entries_completed': session.entries_completed,
                'session_status': session.session_status,
                'started_at': session.started_at,
                'last_activity_at': session.last_activity_at,
                'session_duration_minutes': session.session_duration_minutes
            })

        except Exception as e:
            self._log_error(
                f'Error creating review session: {e}',
                {
                    'session_data_json_len': len(session_data_json),
                    'session_data_json_preview': session_data_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to create session: {e}')

    @pyqtSlot(int, bool, result=str)
    @instrumented_slot
    def getReviewSessions(self, exam_context_id: int, include_complete: bool = True) -> str:
        """
        Get review sessions for an exam context.

        Args:
            exam_context_id: Exam context ID
            include_complete: Whether to include completed sessions

        Returns:
            JSON response with list of sessions
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            sessions = self.user_db.get_review_sessions(
                exam_context_id=exam_context_id,
                include_completed=include_complete
            )

            data = []
            for s in sessions:
                ar = self.user_db.get_active_timer_round(s.id)
                data.append({
                    'id': s.id,
                    'user_id': s.user_id,
                    'exam_context_id': s.exam_context_id,
                    'question_source_id': s.question_source_id,
                    'session_name': s.session_name,
                    'date_encountered': s.date_encountered,
                    'total_questions': s.total_questions,
                    'total_incorrect': s.total_incorrect,
                    'entries_completed': s.entries_completed,
                    'session_status': s.session_status,
                    'started_at': s.started_at,
                    'completed_at': s.completed_at,
                    'last_activity_at': s.last_activity_at,
                    'session_duration_minutes': s.session_duration_minutes,
                    'total_break_seconds': s.total_break_seconds,
                    'timer_paused_at': s.timer_paused_at,
                    'active_round': ar.to_dict() if ar else None
                })

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting review sessions: {e}',
                {
                    'exam_context_id': exam_context_id,
                    'include_complete': include_complete,
                },
            )
            return serialize_response(False, error=f'Failed to get sessions: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getReviewSession(self, session_id: int) -> str:
        """
        Get a review session by ID.

        Args:
            session_id: Session ID

        Returns:
            JSON response with session data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            session = self.user_db.get_review_session(session_id)

            if not session:
                return serialize_response(False, error='Session not found')

            active_round = self.user_db.get_active_timer_round(session.id)
            return serialize_response(True, data={
                'id': session.id,
                'user_id': session.user_id,
                'exam_context_id': session.exam_context_id,
                'question_source_id': session.question_source_id,
                'session_name': session.session_name,
                'date_encountered': session.date_encountered,
                'total_questions': session.total_questions,
                'total_incorrect': session.total_incorrect,
                'entries_completed': session.entries_completed,
                'session_status': session.session_status,
                'started_at': session.started_at,
                'completed_at': session.completed_at,
                'last_activity_at': session.last_activity_at,
                'session_duration_minutes': session.session_duration_minutes,
                'total_break_seconds': session.total_break_seconds,
                'timer_paused_at': session.timer_paused_at,
                'active_round': active_round.to_dict() if active_round else None
            })

        except Exception as e:
            self._log_error(
                f'Error getting review session: {e}',
                {'session_id': session_id},
            )
            return serialize_response(False, error=f'Failed to get session: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateReviewSession(self, session_id: int, updates_json: str) -> str:
        """
        Update a review session.

        Args:
            session_id: Session ID
            updates_json: JSON string with updates

        Returns:
            JSON response with updated session
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            updates = json.loads(updates_json)
            session = self.user_db.update_review_session(session_id, **updates)

            return serialize_response(True, data={
                'id': session.id,
                'user_id': session.user_id,
                'exam_context_id': session.exam_context_id,
                'question_source_id': session.question_source_id,
                'session_name': session.session_name,
                'date_encountered': session.date_encountered,
                'total_questions': session.total_questions,
                'total_incorrect': session.total_incorrect,
                'entries_completed': session.entries_completed,
                'session_status': session.session_status,
                'started_at': session.started_at,
                'completed_at': session.completed_at,
                'last_activity_at': session.last_activity_at,
                'session_duration_minutes': session.session_duration_minutes,
                'total_break_seconds': session.total_break_seconds,
                'timer_paused_at': session.timer_paused_at
            })

        except Exception as e:
            self._log_error(
                f'Error updating review session: {e}',
                {
                    'session_id': session_id,
                    'updates_json_len': len(updates_json),
                    'updates_json_preview': updates_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to update session: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteReviewSession(self, session_id: int) -> str:
        """
        Delete a review session and all its entries.

        Args:
            session_id: Session ID

        Returns:
            JSON response with delete result
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            self.user_db.delete_review_session(session_id)
            return serialize_response(True, data={'id': session_id, 'deleted': True})

        except Exception as e:
            self._log_error(
                f'Error deleting review session: {e}',
                {'session_id': session_id},
            )
            return serialize_response(False, error=f'Failed to delete session: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def pauseSessionTimer(self, session_id: int) -> str:
        """Pause the session timer (set timer_paused_at)."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            session = self.user_db.pause_session_timer(session_id)
            if not session:
                return serialize_response(False, error='Session not found')
            return serialize_response(True, data={
                'total_break_seconds': session.total_break_seconds,
                'timer_paused_at': session.timer_paused_at
            })
        except Exception as e:
            self._log_error(
                f'Error pausing session timer: {e}',
                {'session_id': session_id},
            )
            return serialize_response(False, error=f'Failed to pause timer: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def unpauseSessionTimer(self, session_id: int) -> str:
        """Unpause the session timer (accumulate break seconds, clear timer_paused_at)."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            session = self.user_db.unpause_session_timer(session_id)
            if not session:
                return serialize_response(False, error='Session not found')
            return serialize_response(True, data={
                'total_break_seconds': session.total_break_seconds,
                'timer_paused_at': session.timer_paused_at
            })
        except Exception as e:
            self._log_error(
                f'Error unpausing session timer: {e}',
                {'session_id': session_id},
            )
            return serialize_response(False, error=f'Failed to unpause timer: {e}')
