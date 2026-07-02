"""WIMI Goals database operations."""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta

from ..exceptions import ValidationError
from app_logging import ErrorCategory


class GoalsMixin:
    """Mixin for goals operations. Composed into UserDatabase."""

    def get_user_goals(
        self,
        exam_context_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get user's active goals with current period progress.

        Args:
            exam_context_id: Optional exam context filter

        Returns:
            List of goal dictionaries with progress info
        """
        from datetime import timedelta

        today = datetime.now().date()

        # Get week boundaries (Monday to Sunday)
        days_since_monday = today.weekday()
        week_start = today - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)

        # Base query for active goals
        query = """
            SELECT
                ug.id as goal_id,
                ug.goal_type,
                ug.target_value,
                ug.exam_context_id,
                ug.is_active,
                ug.created_at,
                gp.id as period_id,
                gp.period_start,
                gp.period_end,
                gp.achieved_value,
                gp.is_complete
            FROM user_goals ug
            LEFT JOIN goal_periods gp ON ug.id = gp.goal_id
                AND gp.period_start = ?
            WHERE ug.user_id = ? AND ug.is_active = TRUE
        """
        params = [week_start.isoformat(), self.user_id]

        if exam_context_id:
            query += " AND (ug.exam_context_id = ? OR ug.exam_context_id IS NULL)"
            params.append(exam_context_id)

        results = self.fetchall(query, tuple(params))

        goals = []
        for row in results:
            # Calculate current progress if period doesn't exist
            if row['period_id'] is None:
                # Weekly goals now track questions answered (sum of total_questions from sessions)
                if row['goal_type'] in ('weekly_questions', 'weekly_entries'):
                    current_value = self._count_questions_in_period(
                        week_start, week_end,
                        row['exam_context_id']
                    )
                else:
                    # Other goal types may use different counting
                    current_value = self._count_entries_in_period(
                        week_start, week_end,
                        row['exam_context_id']
                    )
            else:
                current_value = row['achieved_value'] or 0

            target = row['target_value']
            progress_pct = (current_value / target * 100) if target > 0 else 0
            is_complete = current_value >= target

            goals.append({
                'goal_id': row['goal_id'],
                'goal_type': row['goal_type'],
                'target_value': target,
                'current_value': current_value,
                'period_start': week_start.isoformat(),
                'period_end': week_end.isoformat(),
                'progress_pct': round(progress_pct, 1),
                'is_complete': is_complete,
                'exam_context_id': row['exam_context_id']
            })

        return goals

    def set_weekly_goal(
        self,
        target_questions: int,
        exam_context_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Set or update weekly questions goal.

        Args:
            target_questions: Target number of questions to answer per week
            exam_context_id: Optional exam context for goal

        Returns:
            Dictionary with goal info and success message
        """
        from datetime import timedelta

        if target_questions < 1 or target_questions > 1000:
            raise ValidationError("Target must be between 1 and 1000")

        today = datetime.now().date()
        days_since_monday = today.weekday()
        week_start = today - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)

        # Check if goal already exists (check both new and legacy types)
        existing_query = """
            SELECT id, target_value, goal_type FROM user_goals
            WHERE user_id = ? AND goal_type IN ('weekly_questions', 'weekly_entries') AND is_active = TRUE
        """
        params = [self.user_id]

        if exam_context_id:
            existing_query += " AND exam_context_id = ?"
            params.append(exam_context_id)
        else:
            existing_query += " AND exam_context_id IS NULL"

        existing = self.fetchone(existing_query, tuple(params))

        if existing:
            # Update existing goal
            self.execute(
                "UPDATE user_goals SET target_value = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (target_questions, existing['id'])
            )
            goal_id = existing['id']
            message = 'Goal updated successfully'
        else:
            # Create new goal (use 'weekly_entries' type for backward compatibility)
            cursor = self.execute(
                """
                INSERT INTO user_goals (user_id, goal_type, target_value, exam_context_id)
                VALUES (?, 'weekly_entries', ?, ?)
                """,
                (self.user_id, target_questions, exam_context_id)
            )
            goal_id = cursor.lastrowid
            message = 'Goal created successfully'

        # Ensure current period exists
        self._ensure_goal_period(goal_id, week_start, week_end, target_questions)

        self.conn.commit()

        return {
            'goal_id': goal_id,
            'target_value': target_questions,
            'message': message
        }

    def get_goal_history(
        self,
        exam_context_id: Optional[int] = None,
        weeks: int = 8
    ) -> List[Dict[str, Any]]:
        """
        Get history of goal completion.

        Args:
            exam_context_id: Optional exam context filter
            weeks: Number of weeks to include

        Returns:
            List of weekly goal performance records
        """
        from datetime import timedelta

        today = datetime.now().date()
        days_since_monday = today.weekday()
        current_week_start = today - timedelta(days=days_since_monday)

        # Get the active goal (support both new and legacy types)
        goal_query = """
            SELECT id, target_value, goal_type FROM user_goals
            WHERE user_id = ? AND goal_type IN ('weekly_questions', 'weekly_entries') AND is_active = TRUE
        """
        params = [self.user_id]

        if exam_context_id:
            goal_query += " AND exam_context_id = ?"
            params.append(exam_context_id)
        else:
            goal_query += " AND exam_context_id IS NULL"

        goal = self.fetchone(goal_query, tuple(params))

        if not goal:
            return []

        # Determine counting method based on goal type
        # Weekly goals now track questions answered
        use_questions_counting = goal['goal_type'] in ('weekly_questions', 'weekly_entries')

        # Get historical periods
        history_query = """
            SELECT
                period_start,
                period_end,
                target_value,
                achieved_value,
                is_complete
            FROM goal_periods
            WHERE goal_id = ?
            ORDER BY period_start DESC
            LIMIT ?
        """
        periods = self.fetchall(history_query, (goal['id'], weeks))

        history = []

        # Generate weeks even if no period record exists
        for i in range(weeks):
            week_start = current_week_start - timedelta(weeks=i)
            week_end = week_start + timedelta(days=6)

            # Find matching period
            period_data = None
            for p in periods:
                if p['period_start'] == week_start.isoformat():
                    period_data = p
                    break

            if period_data:
                achieved = period_data['achieved_value']
                target = period_data['target_value']
            else:
                # Calculate using appropriate method
                if use_questions_counting:
                    achieved = self._count_questions_in_period(
                        week_start, week_end, exam_context_id
                    )
                else:
                    # Legacy: count entries
                    achieved = self._count_entries_in_period(
                        week_start, week_end, exam_context_id
                    )
                target = goal['target_value']

            completion_pct = (achieved / target * 100) if target > 0 else 0

            history.append({
                'week_start': week_start.isoformat(),
                'week_end': week_end.isoformat(),
                'target': target,
                'achieved': achieved,
                'completed': achieved >= target,
                'completion_pct': round(completion_pct, 1)
            })

        return history

    def _count_entries_in_period(
        self,
        start_date: date,
        end_date: date,
        exam_context_id: Optional[int] = None
    ) -> int:
        """
        Count entries in a date range.
        DEPRECATED: Use _count_questions_in_period for weekly_questions goals.
        """
        query = """
            SELECT COUNT(DISTINCT qe.id) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ?
                AND DATE(qe.created_at) >= ?
                AND DATE(qe.created_at) <= ?
                AND qe.is_draft = FALSE
        """
        params = [self.user_id, start_date.isoformat(), end_date.isoformat()]

        if exam_context_id:
            query += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)

        result = self.fetchone(query, tuple(params))
        return result['count'] if result else 0

    def _count_questions_in_period(
        self,
        start_date: date,
        end_date: date,
        exam_context_id: Optional[int] = None
    ) -> int:
        """
        Count total questions answered in a date range.

        Questions are counted from the total_questions field in review_sessions,
        summed for all sessions where date_encountered falls within the period.

        Args:
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            exam_context_id: Optional exam context filter

        Returns:
            Total number of questions answered in the period
        """
        query = """
            SELECT COALESCE(SUM(rs.total_questions), 0) as total
            FROM review_sessions rs
            WHERE rs.user_id = ?
                AND DATE(rs.date_encountered) >= ?
                AND DATE(rs.date_encountered) <= ?
        """
        params = [self.user_id, start_date.isoformat(), end_date.isoformat()]

        if exam_context_id:
            query += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)

        result = self.fetchone(query, tuple(params))
        return result['total'] if result and result['total'] else 0

    def _ensure_goal_period(
        self,
        goal_id: int,
        period_start: date,
        period_end: date,
        target_value: int
    ) -> int:
        """
        Ensure a goal period exists for the given dates.
        """
        # Check if period exists
        existing = self.fetchone(
            "SELECT id FROM goal_periods WHERE goal_id = ? AND period_start = ?",
            (goal_id, period_start.isoformat())
        )

        if existing:
            # Update target if changed
            self.execute(
                "UPDATE goal_periods SET target_value = ? WHERE id = ?",
                (target_value, existing['id'])
            )
            return existing['id']
        else:
            # Calculate current achievement based on goal type
            goal = self.fetchone(
                "SELECT exam_context_id, goal_type FROM user_goals WHERE id = ?",
                (goal_id,)
            )

            # Use appropriate counting method
            # Weekly goals now track questions answered
            if goal and goal['goal_type'] in ('weekly_questions', 'weekly_entries'):
                achieved = self._count_questions_in_period(
                    period_start, period_end,
                    goal['exam_context_id'] if goal else None
                )
            else:
                # Other goal types use entry count
                achieved = self._count_entries_in_period(
                    period_start, period_end,
                    goal['exam_context_id'] if goal else None
                )

            cursor = self.execute(
                """
                INSERT INTO goal_periods (goal_id, period_start, period_end, target_value, achieved_value, is_complete)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (goal_id, period_start.isoformat(), period_end.isoformat(),
                 target_value, achieved, achieved >= target_value)
            )
            return cursor.lastrowid

    def update_goal_progress(self, exam_context_id: Optional[int] = None) -> None:
        """
        Update goal progress for current period.
        Called when a new entry is created or review session is completed.
        """
        from datetime import timedelta

        today = datetime.now().date()
        days_since_monday = today.weekday()
        week_start = today - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)

        # Get active goals with goal_type
        query = """
            SELECT ug.id, ug.target_value, ug.exam_context_id, ug.goal_type, gp.id as period_id
            FROM user_goals ug
            LEFT JOIN goal_periods gp ON ug.id = gp.goal_id AND gp.period_start = ?
            WHERE ug.user_id = ? AND ug.is_active = TRUE
        """
        goals = self.fetchall(query, (week_start.isoformat(), self.user_id))

        for goal in goals:
            # Check if this goal applies to this exam context
            if goal['exam_context_id'] and goal['exam_context_id'] != exam_context_id:
                continue

            # Count using appropriate method based on goal type
            # Weekly goals now track questions answered
            if goal['goal_type'] in ('weekly_questions', 'weekly_entries'):
                achieved = self._count_questions_in_period(
                    week_start, week_end, goal['exam_context_id']
                )
            else:
                # Other goal types use entry count
                achieved = self._count_entries_in_period(
                    week_start, week_end, goal['exam_context_id']
                )

            if goal['period_id']:
                # Update existing period
                is_complete = achieved >= goal['target_value']
                self.execute(
                    """
                    UPDATE goal_periods
                    SET achieved_value = ?, is_complete = ?,
                        completed_at = CASE WHEN ? AND completed_at IS NULL THEN CURRENT_TIMESTAMP ELSE completed_at END
                    WHERE id = ?
                    """,
                    (achieved, is_complete, is_complete, goal['period_id'])
                )
            else:
                # Create period record
                self._ensure_goal_period(
                    goal['id'], week_start, week_end, goal['target_value']
                )

        self.conn.commit()
