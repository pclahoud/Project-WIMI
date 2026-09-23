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

        Progress is **counted from the entries every time**, never read
        back from ``goal_periods.achieved_value`` (issue #70). The stored
        value was stamped by :meth:`_ensure_goal_period` at the moment
        the goal was created and nothing ever refreshed it, so a goal
        froze for the whole of the week it was set in -- the week a
        student is most likely to be watching it. Recomputing here means
        no write path has to remember to notify anything, which is what
        makes that staleness structurally impossible rather than merely
        fixed. See :meth:`_ensure_goal_period` for what the table is for
        now.

        This stays a pure read: the read-only ``wimi-db`` MCP server
        calls it (``src/mcp_server.py``).

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
                ug.created_at
            FROM user_goals ug
            WHERE ug.user_id = ? AND ug.is_active = TRUE
        """
        params = [self.user_id]

        if exam_context_id:
            query += " AND (ug.exam_context_id = ? OR ug.exam_context_id IS NULL)"
            params.append(exam_context_id)

        results = self.fetchall(query, tuple(params))

        goals = []
        for row in results:
            current_value = self._count_goal_progress_in_period(
                row['goal_type'], week_start, week_end,
                row['exam_context_id']
            )

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
                'exam_context_id': row['exam_context_id'],
                # Issue #12: goals are the one surface that still
                # excludes drafts -- "log 20 entries this week" means 20
                # finished ones. That exclusion is only honest if the
                # student can see what it left out, so the outstanding
                # drafts ride alongside the progress and the widget
                # renders them as "N drafts remaining".
                'drafts_remaining': self._count_drafts_in_period(
                    week_start, week_end, row['exam_context_id']
                ),
            })

        return goals

    def set_weekly_goal(
        self,
        target_questions: int,
        exam_context_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Set or update the weekly goal.

        The goal it creates is a ``weekly_entries`` goal: a target number
        of entries logged in the week, counted by
        :meth:`_count_entries_in_period` (issue #58). The parameter keeps
        its historical ``target_questions`` name so existing callers --
        the bridge slot, the plugin API -- are unaffected.

        Args:
            target_questions: Target number of entries to log per week
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

        # Check if this exam context already has a weekly goal
        existing_query = """
            SELECT id, target_value, goal_type FROM user_goals
            WHERE user_id = ? AND goal_type = 'weekly_entries' AND is_active = TRUE
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
            # Create new goal. 'weekly_entries' is the only weekly type
            # there is: see _count_goal_progress_in_period (issue #71).
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

        Like :meth:`get_user_goals`, every week's ``achieved`` is counted
        from the entries rather than read from
        ``goal_periods.achieved_value`` (issue #70). The stored row is
        consulted only for ``target_value`` -- the target the student had
        set in that week, which nothing else records.

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

        # Get the active weekly goal
        goal_query = """
            SELECT id, target_value, goal_type FROM user_goals
            WHERE user_id = ? AND goal_type = 'weekly_entries' AND is_active = TRUE
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

        # Get historical periods. ``target_value`` is the only column
        # read: achievement is recounted below (issue #70).
        history_query = """
            SELECT
                period_start,
                period_end,
                target_value
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

            achieved = self._count_goal_progress_in_period(
                goal['goal_type'], week_start, week_end, exam_context_id
            )
            target = period_data['target_value'] if period_data else goal['target_value']

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

    def _count_goal_progress_in_period(
        self,
        goal_type: Optional[str],
        start_date: date,
        end_date: date,
        exam_context_id: Optional[int] = None
    ) -> int:
        """
        Progress for one goal type over a period.

        The single place that decides which counter a goal type reads.
        Every progress path -- :meth:`get_user_goals` and
        :meth:`get_goal_history` -- comes through here. Both are reads,
        which is the point of issue #70: progress is counted when it is
        displayed, so there is no stored number to go stale and no write
        path that has to remember to refresh one.

        There is **one weekly goal type**: ``weekly_entries``, entries
        logged (issue #71, decided 2026-09-15). This used to fork on
        ``weekly_questions``, which counted ``review_sessions``' question
        totals instead -- a type ``user_goals``' CHECK constraint forbids
        and nothing has ever created, so the branch was unreachable code
        that read as live. That is the same shape as the bug #58 fixed, a
        type name and its behaviour disagreeing for months, so it is
        gone. Bringing questions-based goals back means a migration
        widening the constraint and a way to create the type, not a
        resurrection of the branch.

        ``goal_type`` stays in the signature because this is the funnel:
        before #58 four callers each dispatched for themselves and all
        four were wrong. A second type plugs in here, and nowhere else.

        Args:
            goal_type: The goal's ``goal_type`` column
            start_date: Start of the period (inclusive)
            end_date: End of the period (inclusive)
            exam_context_id: Optional exam context filter

        Returns:
            The progress value for that goal type over the period
        """
        return self._count_entries_in_period(
            start_date, end_date, exam_context_id
        )

    def _count_entries_in_period(
        self,
        start_date: date,
        end_date: date,
        exam_context_id: Optional[int] = None
    ) -> int:
        """
        Count entries logged in a date range.

        The counter behind every weekly goal since issue #58, and the
        only one since #71. It spent a while marked deprecated while
        every dispatch site sent ``weekly_entries`` to a question counter
        instead, which is how a goal named after entries came to count
        the question totals of review sessions.

        Keeps ``is_draft = FALSE``. Goals are the deliberate exception to
        issue #12's "drafts count everywhere" policy: "log 20 entries
        this week" means 20 *finished* entries, so an unfinished one is
        not progress. The drafts it skips are reported separately by
        :meth:`_count_drafts_in_period`.
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

    def _count_drafts_in_period(
        self,
        start_date: date,
        end_date: date,
        exam_context_id: Optional[int] = None
    ) -> int:
        """
        Count unfinished (draft) entries started in a date range.

        The exact complement of :meth:`_count_entries_in_period` -- same
        window, same date column, same exam scope, opposite ``is_draft``
        -- so "N drafts remaining" names entries the student started in
        this goal's own period and has not finished.

        Issue #12: goals keep excluding drafts, but a goal that silently
        ignores three drafts is the same information gap the issue is
        about, just moved. This is what closes it.

        Args:
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            exam_context_id: Optional exam context filter

        Returns:
            Number of draft entries created in the period
        """
        query = """
            SELECT COUNT(DISTINCT qe.id) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ?
                AND DATE(qe.created_at) >= ?
                AND DATE(qe.created_at) <= ?
                AND qe.is_draft = TRUE
        """
        params = [self.user_id, start_date.isoformat(), end_date.isoformat()]

        if exam_context_id:
            query += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)

        result = self.fetchone(query, tuple(params))
        return result['count'] if result else 0

    def _ensure_goal_period(
        self,
        goal_id: int,
        period_start: date,
        period_end: date,
        target_value: int
    ) -> int:
        """
        Ensure a goal period exists for the given dates.

        The row records **the target the student had set for that week**
        and nothing else. Achievement is not stamped here and is not
        stored: both read paths recount it from the entries every time
        (issue #70), so ``goal_periods.achieved_value`` is legacy -- it
        still holds numbers written before that fix, and nothing reads
        them. The week's target is genuine history because nothing else
        records it: raising the goal today must not rewrite what last
        week was measured against.

        Stamping achievement here is what froze goals for the week they
        were created in. The existing-period branch updated the target
        and left the stamp alone, so even re-saving the goal did not
        refresh it, and ``update_goal_progress`` -- the notifier that was
        supposed to -- had no callers anywhere in the repo.
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

        cursor = self.execute(
            """
            INSERT INTO goal_periods (goal_id, period_start, period_end, target_value)
            VALUES (?, ?, ?, ?)
            """,
            (goal_id, period_start.isoformat(), period_end.isoformat(),
             target_value)
        )
        return cursor.lastrowid
