"""WIMI Goals bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class GoalsBridgeMixin:
    """Bridge mixin for goal operations. Composed into DatabaseBridge."""

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getUserGoals(self, params_json: str) -> str:
        """
        Get user's active goals with current period progress.

        Args:
            params_json: JSON with optional exam_context_id

        Returns:
            JSON response with goals array
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json) if params_json else {}
            exam_context_id = params.get('examContextId') or params.get('exam_context_id')

            goals = self.user_db.get_user_goals(
                exam_context_id=exam_context_id
            )

            return serialize_response(True, data=goals)

        except Exception as e:
            self._log_error(
                f'Error getting user goals: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'params_json_preview': params_json[:200] if params_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to get user goals: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def setWeeklyGoal(self, target: int, params_json: str) -> str:
        """
        Set or update weekly questions goal.

        Args:
            target: Target number of questions per week
            params_json: JSON with optional exam_context_id

        Returns:
            JSON response with goal info
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json) if params_json else {}
            exam_context_id = params.get('examContextId') or params.get('exam_context_id')

            result = self.user_db.set_weekly_goal(
                target_questions=target,
                exam_context_id=exam_context_id
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error setting weekly goal: {e}',
                {
                    'target': target,
                    'exam_context_id': locals().get('exam_context_id'),
                    'params_json_preview': params_json[:200] if params_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to set weekly goal: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getGoalHistory(self, params_json: str) -> str:
        """
        Get history of goal completion.

        Args:
            params_json: JSON with optional exam_context_id and weeks

        Returns:
            JSON response with goal history array
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json) if params_json else {}
            exam_context_id = params.get('examContextId') or params.get('exam_context_id')
            weeks = params.get('weeks', 8)

            history = self.user_db.get_goal_history(
                exam_context_id=exam_context_id,
                weeks=weeks
            )

            return serialize_response(True, data=history)

        except Exception as e:
            self._log_error(
                f'Error getting goal history: {e}',
                {
                    'exam_context_id': locals().get('exam_context_id'),
                    'weeks': locals().get('weeks'),
                    'params_json_preview': params_json[:200] if params_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to get goal history: {e}')
