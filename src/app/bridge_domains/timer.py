"""WIMI Timer round bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from ..bridge_helpers import serialize_response


class TimerBridgeMixin:
    """Bridge mixin for timer round operations. Composed into DatabaseBridge."""

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def createTimerRound(self, session_id: int, duration_minutes: int) -> str:
        """Create a new timer round (auto-ends any active round)."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            rnd = self.user_db.create_timer_round(session_id, duration_minutes)
            if not rnd:
                return serialize_response(False, error='Failed to create timer round')
            return serialize_response(True, data=rnd.to_dict())
        except Exception as e:
            self._log_error(
                f'Error creating timer round: {e}',
                {
                    'session_id': session_id,
                    'duration_minutes': duration_minutes,
                },
            )
            return serialize_response(False, error=f'Failed to create timer round: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getActiveTimerRound(self, session_id: int) -> str:
        """Get the active (not ended) timer round for a session."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            rnd = self.user_db.get_active_timer_round(session_id)
            return serialize_response(True, data=rnd.to_dict() if rnd else None)
        except Exception as e:
            self._log_error(
                f'Error getting active timer round: {e}',
                {'session_id': session_id},
            )
            return serialize_response(False, error=f'Failed to get active timer round: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getTimerRounds(self, session_id: int) -> str:
        """Get all timer rounds for a session."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            rounds = self.user_db.get_timer_rounds(session_id)
            return serialize_response(True, data=[r.to_dict() for r in rounds])
        except Exception as e:
            self._log_error(
                f'Error getting timer rounds: {e}',
                {'session_id': session_id},
            )
            return serialize_response(False, error=f'Failed to get timer rounds: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def endTimerRound(self, round_id: int) -> str:
        """End a timer round, calculating actual studied seconds."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            rnd = self.user_db.end_timer_round(round_id)
            if not rnd:
                return serialize_response(False, error='Round not found')
            return serialize_response(True, data=rnd.to_dict())
        except Exception as e:
            self._log_error(
                f'Error ending timer round: {e}',
                {'round_id': round_id},
            )
            return serialize_response(False, error=f'Failed to end timer round: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def pauseRoundTimer(self, round_id: int) -> str:
        """Pause a timer round."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            rnd = self.user_db.pause_round_timer(round_id)
            if not rnd:
                return serialize_response(False, error='Round not found')
            return serialize_response(True, data=rnd.to_dict())
        except Exception as e:
            self._log_error(
                f'Error pausing round timer: {e}',
                {'round_id': round_id},
            )
            return serialize_response(False, error=f'Failed to pause round timer: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def unpauseRoundTimer(self, round_id: int) -> str:
        """Unpause a timer round, accumulating break seconds."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            rnd = self.user_db.unpause_round_timer(round_id)
            if not rnd:
                return serialize_response(False, error='Round not found')
            return serialize_response(True, data=rnd.to_dict())
        except Exception as e:
            self._log_error(
                f'Error unpausing round timer: {e}',
                {'round_id': round_id},
            )
            return serialize_response(False, error=f'Failed to unpause round timer: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateTimerRound(self, round_id: int, updates_json: str) -> str:
        """Update a timer round's editable fields."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            updates = json.loads(updates_json)
            rnd = self.user_db.update_timer_round(round_id, updates)
            if not rnd:
                return serialize_response(False, error='Round not found')
            return serialize_response(True, data=rnd.to_dict())
        except Exception as e:
            self._log_error(
                f'Error updating timer round: {e}',
                {
                    'round_id': round_id,
                    'updates_json_len': len(updates_json),
                    'updates_json_preview': updates_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to update timer round: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteTimerRound(self, round_id: int) -> str:
        """Delete a timer round."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            deleted = self.user_db.delete_timer_round(round_id)
            return serialize_response(True, data={'deleted': deleted})
        except Exception as e:
            self._log_error(
                f'Error deleting timer round: {e}',
                {'round_id': round_id},
            )
            return serialize_response(False, error=f'Failed to delete timer round: {e}')
