"""WIMI analytics operations."""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from app_logging import ErrorCategory


class AnalyticsMixin:
    """Mixin for analytics. Composed into UserDatabase."""

    def get_analytics_overview(
        self,
        exam_context_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get high-level analytics overview for the dashboard.

        Args:
            exam_context_id: Filter by exam context (optional)

        Returns:
            Dictionary with overview statistics:
            {
                'total_entries': int,
                'completed_entries': int,
                'draft_entries': int,
                'total_sessions': int,
                'completed_sessions': int,
                'this_week': int,
                'last_week': int,
                'week_change': int,
                'this_month': int,
                'avg_difficulty': float,
                'completion_rate': float
            }
        """
        from datetime import datetime, timedelta

        # Base query conditions
        where_conditions = ["rs.user_id = ?"]
        params = [self.user_id]

        if exam_context_id:
            where_conditions.append("rs.exam_context_id = ?")
            params.append(exam_context_id)

        where_clause = " AND ".join(where_conditions)

        # Total entries
        total_query = f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN qe.is_draft = 0 THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN qe.is_draft = 1 THEN 1 ELSE 0 END) as drafts
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause}
        """
        total_row = self.fetchone(total_query, tuple(params))

        total_entries = total_row['total'] or 0
        completed_entries = total_row['completed'] or 0
        draft_entries = total_row['drafts'] or 0

        # Session statistics
        session_query = f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN session_status = 'completed' THEN 1 ELSE 0 END) as completed
            FROM review_sessions rs
            WHERE {where_clause}
        """
        session_row = self.fetchone(session_query, tuple(params))

        total_sessions = session_row['total'] or 0
        completed_sessions = session_row['completed'] or 0

        # This week (last 7 days)
        today = datetime.now().date()
        week_ago = today - timedelta(days=7)
        two_weeks_ago = today - timedelta(days=14)
        month_ago = today - timedelta(days=30)

        this_week_query = f"""
            SELECT COUNT(*) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause} AND rs.date_encountered >= ?
        """
        this_week = self.fetchone(this_week_query, tuple(params + [week_ago.isoformat()]))['count'] or 0

        # Last week (7-14 days ago)
        last_week_query = f"""
            SELECT COUNT(*) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause} AND rs.date_encountered >= ? AND rs.date_encountered < ?
        """
        last_week = self.fetchone(last_week_query, tuple(params + [two_weeks_ago.isoformat(), week_ago.isoformat()]))['count'] or 0

        # This month
        this_month_query = f"""
            SELECT COUNT(*) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause} AND rs.date_encountered >= ?
        """
        this_month = self.fetchone(this_month_query, tuple(params + [month_ago.isoformat()]))['count'] or 0

        # Average difficulty
        difficulty_query = f"""
            SELECT AVG(perceived_difficulty) as avg_difficulty
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause} AND qe.perceived_difficulty IS NOT NULL
        """
        avg_difficulty = self.fetchone(difficulty_query, tuple(params))['avg_difficulty'] or 0.0

        # Completion rate
        completion_rate = (completed_entries / total_entries * 100) if total_entries > 0 else 0.0

        # Week change
        week_change = this_week - last_week if last_week > 0 else this_week

        return {
            'total_entries': total_entries,
            'completed_entries': completed_entries,
            'draft_entries': draft_entries,
            'total_sessions': total_sessions,
            'completed_sessions': completed_sessions,
            'this_week': this_week,
            'last_week': last_week,
            'week_change': week_change,
            'this_month': this_month,
            'avg_difficulty': round(avg_difficulty, 2),
            'completion_rate': round(completion_rate, 1)
        }

    def get_subject_analytics(
        self,
        exam_context_id: Optional[int] = None,
        limit: int = 10,
        include_children: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get mistake counts by subject for visualization.

        Args:
            exam_context_id: Filter by exam context (optional)
            limit: Maximum number of subjects to return
            include_children: Include child subject counts in parent totals.
                When True, each subject's total_mistake_count includes mistakes
                from all descendant subjects in the hierarchy.

        Returns:
            List of dictionaries with subject analytics:
            [
                {
                    'subject_id': int,
                    'subject_name': str,
                    'full_path': str,
                    'mistake_count': int,        # Direct mistakes only
                    'total_mistake_count': int,  # Including descendants (if include_children)
                    'percentage': float,
                    'exam_weight': float,
                    'avg_difficulty': float,
                    'last_mistake_date': str,
                    'trend': str ('up', 'down', 'stable')
                },
                ...
            ]
        """
        from datetime import datetime, timedelta

        where_conditions = ["rs.user_id = ?"]
        params = [self.user_id]

        if exam_context_id:
            where_conditions.append("rs.exam_context_id = ?")
            params.append(exam_context_id)

        where_clause = " AND ".join(where_conditions)

        # Get total entries for percentage calculation
        total_query = f"""
            SELECT COUNT(*) as total
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause}
        """
        total_entries = self.fetchone(total_query, tuple(params))['total'] or 1

        # Get ALL subjects with their direct mistake counts (no LIMIT yet)
        # Include parent_id for hierarchy aggregation
        subject_query = f"""
            SELECT
                sn.id as subject_id,
                sn.parent_id,
                sn.name as subject_name,
                (COALESCE(sn.exam_weight_low, 0) + COALESCE(sn.exam_weight_high, sn.exam_weight_low, 0)) / 2.0 as exam_weight,
                COALESCE(sn.exam_weight_low, 0) as exam_weight_low,
                COALESCE(sn.exam_weight_high, sn.exam_weight_low, 0) as exam_weight_high,
                COUNT(DISTINCT qe.id) as mistake_count,
                AVG(qe.perceived_difficulty) as avg_difficulty,
                MAX(rs.date_encountered) as last_mistake_date
            FROM subject_nodes sn
            JOIN entry_subject_mappings esm ON sn.id = esm.subject_node_id
            JOIN question_entries qe ON esm.question_entry_id = qe.id
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause} AND esm.mapping_type = 'primary'
            GROUP BY sn.id, sn.parent_id, sn.name, sn.exam_weight_low, sn.exam_weight_high
        """
        subject_rows = self.fetchall(subject_query, tuple(params))

        # If include_children, aggregate counts up through hierarchy
        if include_children and subject_rows:
            # Build nodes list for aggregation
            nodes_for_aggregation = [
                {
                    'id': row['subject_id'],
                    'parent_id': row['parent_id'],
                    'direct_count': row['mistake_count']
                }
                for row in subject_rows
            ]
            totals = self._aggregate_hierarchy_counts(nodes_for_aggregation, count_field='direct_count')
        else:
            totals = {row['subject_id']: row['mistake_count'] for row in subject_rows}

        # Build intermediate results with totals
        subjects_with_totals = []
        for row in subject_rows:
            subject_id = row['subject_id']
            direct_count = row['mistake_count']
            total_count = totals.get(subject_id, direct_count)
            subjects_with_totals.append({
                'subject_id': subject_id,
                'subject_name': row['subject_name'],
                'mistake_count': direct_count,
                'total_mistake_count': total_count,
                'exam_weight': row['exam_weight'] or 0.0,
                'exam_weight_low': row.get('exam_weight_low', 0.0) or 0.0,
                'exam_weight_high': row.get('exam_weight_high', 0.0) or 0.0,
                'avg_difficulty': row['avg_difficulty'],
                'last_mistake_date': row['last_mistake_date']
            })

        # Sort by total_mistake_count (or mistake_count if not aggregating) and apply limit
        sort_key = 'total_mistake_count' if include_children else 'mistake_count'
        subjects_with_totals.sort(key=lambda x: x[sort_key], reverse=True)
        subjects_with_totals = subjects_with_totals[:limit]

        # Calculate trends (last 7 days vs previous 7 days)
        week_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
        two_weeks_ago = (datetime.now() - timedelta(days=14)).date().isoformat()

        results = []
        for subj in subjects_with_totals:
            subject_id = subj['subject_id']
            # Use total for percentage if aggregating, otherwise direct
            count_for_percentage = subj['total_mistake_count'] if include_children else subj['mistake_count']
            percentage = (count_for_percentage / total_entries * 100) if total_entries > 0 else 0

            # Get full path
            full_path = self._build_subject_path(subject_id)

            # Calculate trend (based on direct counts for this node)
            recent_query = f"""
                SELECT COUNT(*) as count
                FROM question_entries qe
                JOIN review_sessions rs ON qe.review_session_id = rs.id
                JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
                WHERE {where_clause}
                    AND esm.subject_node_id = ?
                    AND rs.date_encountered >= ?
            """
            recent_count = self.fetchone(recent_query, tuple(params + [subject_id, week_ago]))['count'] or 0

            previous_query = f"""
                SELECT COUNT(*) as count
                FROM question_entries qe
                JOIN review_sessions rs ON qe.review_session_id = rs.id
                JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
                WHERE {where_clause}
                    AND esm.subject_node_id = ?
                    AND rs.date_encountered >= ?
                    AND rs.date_encountered < ?
            """
            previous_count = self.fetchone(previous_query, tuple(params + [subject_id, two_weeks_ago, week_ago]))['count'] or 0

            # Determine trend
            if recent_count > previous_count:
                trend = 'up'
            elif recent_count < previous_count:
                trend = 'down'
            else:
                trend = 'stable'

            results.append({
                'subject_id': subject_id,
                'subject_name': subj['subject_name'],
                'full_path': full_path,
                'mistake_count': subj['mistake_count'],
                'total_mistake_count': subj['total_mistake_count'],
                'percentage': round(percentage, 1),
                'exam_weight': subj['exam_weight'],
                'exam_weight_low': subj['exam_weight_low'],
                'exam_weight_high': subj['exam_weight_high'],
                'avg_difficulty': round(subj['avg_difficulty'] or 0.0, 2),
                'last_mistake_date': subj['last_mistake_date'],
                'trend': trend
            })

        return results

    def get_tag_analytics(
        self,
        exam_context_id: Optional[int] = None,
        group_by_parent: bool = True,
        dimension_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get mistake type distribution by tags.

        Args:
            exam_context_id: Filter by exam context (optional)
            group_by_parent: Group tags by parent tag group
            dimension_id: Filter entries to those with a subject mapping in this dimension (optional)

        Returns:
            Dictionary with tag analytics:
            {
                'total_tagged': int,
                'by_group': {
                    'Mistake Type': [...],
                    'Priority': [...],
                    'Status': [...]
                },
                'top_tags': [...]
            }
        """
        where_conditions = ["rs.user_id = ?"]
        params = [self.user_id]

        if exam_context_id:
            where_conditions.append("rs.exam_context_id = ?")
            params.append(exam_context_id)

        # Filter to entries that have a subject mapping in the specified dimension
        if dimension_id:
            where_conditions.append("""
                qe.id IN (
                    SELECT esm.question_entry_id
                    FROM entry_subject_mappings esm
                    JOIN subject_nodes sn ON esm.subject_node_id = sn.id
                    WHERE sn.dimension_id = ?
                )
            """)
            params.append(dimension_id)

        where_clause = " AND ".join(where_conditions)

        # Get total tagged entries
        total_query = f"""
            SELECT COUNT(DISTINCT qe.id) as total
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_tags et ON qe.id = et.question_entry_id
            WHERE {where_clause}
        """
        total_tagged = self.fetchone(total_query, tuple(params))['total'] or 0

        # Get tag counts grouped by category (parent_id column doesn't exist in schema)
        if group_by_parent:
            tag_query = f"""
                SELECT
                    t.id as tag_id,
                    t.tag_name,
                    t.color_hex,
                    COALESCE(t.tag_category, 'other') as group_name,
                    COUNT(DISTINCT qe.id) as count
                FROM tags t
                JOIN entry_tags et ON t.id = et.tag_id
                JOIN question_entries qe ON et.question_entry_id = qe.id
                JOIN review_sessions rs ON qe.review_session_id = rs.id
                WHERE {where_clause}
                GROUP BY t.id, t.tag_name, t.color_hex, t.tag_category
                ORDER BY count DESC
            """
            tag_rows = self.fetchall(tag_query, tuple(params))

            # Group by parent
            by_group = {}
            for row in tag_rows:
                group_name = row['group_name']
                if group_name not in by_group:
                    by_group[group_name] = []

                by_group[group_name].append({
                    'tag_id': row['tag_id'],
                    'name': row['tag_name'],
                    'color': row['color_hex'],
                    'count': row['count'],
                    'percentage': round(row['count'] / total_tagged * 100, 1) if total_tagged > 0 else 0
                })
        else:
            by_group = {}

        # Get top tags (limit 10)
        top_tags_query = f"""
            SELECT
                t.id as tag_id,
                t.tag_name,
                t.color_hex,
                COUNT(DISTINCT qe.id) as count
            FROM tags t
            JOIN entry_tags et ON t.id = et.tag_id
            JOIN question_entries qe ON et.question_entry_id = qe.id
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause}
            GROUP BY t.id, t.tag_name, t.color_hex
            ORDER BY count DESC
            LIMIT 10
        """
        top_tags = self.fetchall(top_tags_query, tuple(params))

        return {
            'total_tagged': total_tagged,
            'by_group': by_group,
            'top_tags': [
                {
                    'tag_id': row['tag_id'],
                    'name': row['tag_name'],
                    'color': row['color_hex'],
                    'count': row['count'],
                    'percentage': round(row['count'] / total_tagged * 100, 1) if total_tagged > 0 else 0
                }
                for row in top_tags
            ]
        }

    def get_difficulty_distribution(
        self,
        exam_context_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get distribution of entries by difficulty level.

        Args:
            exam_context_id: Filter by exam context (optional)

        Returns:
            Dictionary with difficulty distribution:
            {
                'distribution': {
                    1: {'count': int, 'percentage': float, 'label': 'Easy'},
                    2: {'count': int, 'percentage': float, 'label': 'Moderate'},
                    3: {'count': int, 'percentage': float, 'label': 'Medium'},
                    4: {'count': int, 'percentage': float, 'label': 'Hard'},
                    5: {'count': int, 'percentage': float, 'label': 'Very Hard'}
                },
                'average': float,
                'total_rated': int
            }
        """
        where_conditions = ["rs.user_id = ?"]
        params = [self.user_id]

        if exam_context_id:
            where_conditions.append("rs.exam_context_id = ?")
            params.append(exam_context_id)

        where_clause = " AND ".join(where_conditions)

        # Get difficulty distribution
        difficulty_query = f"""
            SELECT
                perceived_difficulty,
                COUNT(*) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause} AND perceived_difficulty IS NOT NULL
            GROUP BY perceived_difficulty
            ORDER BY perceived_difficulty
        """
        rows = self.fetchall(difficulty_query, tuple(params))

        # Build distribution
        labels = {
            1: 'Easy',
            2: 'Moderate',
            3: 'Medium',
            4: 'Hard',
            5: 'Very Hard'
        }

        distribution = {}
        total_rated = 0
        total_score = 0

        for level in range(1, 6):
            distribution[level] = {'count': 0, 'percentage': 0.0, 'label': labels[level]}

        for row in rows:
            level = row['perceived_difficulty']
            count = row['count']
            distribution[level]['count'] = count
            total_rated += count
            total_score += level * count

        # Calculate percentages
        for level in distribution:
            if total_rated > 0:
                distribution[level]['percentage'] = round(distribution[level]['count'] / total_rated * 100, 1)

        # Calculate average
        average = (total_score / total_rated) if total_rated > 0 else 0.0

        return {
            'distribution': distribution,
            'average': round(average, 2),
            'total_rated': total_rated
        }

    def get_activity_over_time(
        self,
        exam_context_id: Optional[int] = None,
        period: str = '30d',
        granularity: str = 'day'
    ) -> List[Dict[str, Any]]:
        """
        Get entry counts over time for trend charts.

        Args:
            exam_context_id: Filter by exam context (optional)
            period: Time period ('7d', '30d', '90d', '1y', 'all')
            granularity: Time granularity ('day', 'week', 'month')

        Returns:
            List of data points:
            [
                {
                    'date': str,
                    'label': str,
                    'count': int,
                    'cumulative': int
                },
                ...
            ]
        """
        from datetime import datetime, timedelta

        where_conditions = ["rs.user_id = ?"]
        params = [self.user_id]

        if exam_context_id:
            where_conditions.append("rs.exam_context_id = ?")
            params.append(exam_context_id)

        # Determine date range
        today = datetime.now().date()
        if period == '7d':
            start_date = today - timedelta(days=7)
        elif period == '30d':
            start_date = today - timedelta(days=30)
        elif period == '90d':
            start_date = today - timedelta(days=90)
        elif period == '1y':
            start_date = today - timedelta(days=365)
        else:  # 'all'
            start_date = None

        if start_date:
            where_conditions.append("rs.date_encountered >= ?")
            params.append(start_date.isoformat())

        where_clause = " AND ".join(where_conditions)

        # Determine grouping format
        if granularity == 'day':
            date_format = '%Y-%m-%d'
            label_format = '%b %d'
        elif granularity == 'week':
            date_format = '%Y-%W'  # Year-Week
            label_format = 'Week %W'
        else:  # 'month'
            date_format = '%Y-%m'
            label_format = '%b %Y'

        # Get activity data
        activity_query = f"""
            SELECT
                strftime('{date_format}', rs.date_encountered) as period,
                rs.date_encountered,
                COUNT(*) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause}
            GROUP BY period
            ORDER BY period
        """
        rows = self.fetchall(activity_query, tuple(params))

        # Build result with cumulative count
        result = []
        cumulative = 0

        for row in rows:
            date_str = row['date_encountered']
            count = row['count']
            cumulative += count

            # Parse date for label
            date_obj = datetime.fromisoformat(date_str).date()
            label = date_obj.strftime(label_format)

            result.append({
                'date': date_str,
                'label': label,
                'count': count,
                'cumulative': cumulative
            })

        return result

    def get_study_streak(
        self,
        exam_context_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Calculate study streak information.

        Args:
            exam_context_id: Filter by exam context (optional)

        Returns:
            Dictionary with streak information:
            {
                'current_streak': int,
                'longest_streak': int,
                'streak_at_risk': bool,
                'last_entry_date': str,
                'days_since_last_entry': int
            }
        """
        from datetime import datetime, timedelta

        where_conditions = ["rs.user_id = ?"]
        params = [self.user_id]

        if exam_context_id:
            where_conditions.append("rs.exam_context_id = ?")
            params.append(exam_context_id)

        where_clause = " AND ".join(where_conditions)

        # Get all unique dates with entries
        dates_query = f"""
            SELECT DISTINCT date(rs.date_encountered) as entry_date
            FROM review_sessions rs
            WHERE {where_clause}
            ORDER BY entry_date DESC
        """
        rows = self.fetchall(dates_query, tuple(params))

        if not rows:
            return {
                'current_streak': 0,
                'longest_streak': 0,
                'streak_at_risk': False,
                'last_entry_date': None,
                'days_since_last_entry': None
            }

        dates = [datetime.fromisoformat(row['entry_date']).date() for row in rows]
        today = datetime.now().date()
        last_entry = dates[0]
        days_since_last = (today - last_entry).days

        # Calculate current streak
        current_streak = 0
        check_date = today

        # If last entry was today or yesterday, start counting
        if days_since_last <= 1:
            for date in dates:
                if (check_date - date).days <= 1:
                    current_streak += 1
                    check_date = date
                else:
                    break

        # Calculate longest streak
        longest_streak = 0
        temp_streak = 1

        for i in range(len(dates) - 1):
            current_date = dates[i]
            next_date = dates[i + 1]
            diff = (current_date - next_date).days

            if diff == 1:
                temp_streak += 1
                longest_streak = max(longest_streak, temp_streak)
            else:
                temp_streak = 1

        longest_streak = max(longest_streak, temp_streak, current_streak)

        # Check if streak is at risk (no entry today)
        streak_at_risk = (current_streak > 0 and days_since_last >= 1)

        return {
            'current_streak': current_streak,
            'longest_streak': longest_streak,
            'streak_at_risk': streak_at_risk,
            'last_entry_date': last_entry.isoformat(),
            'days_since_last_entry': days_since_last
        }

    def get_patterns_and_insights(
        self,
        exam_context_id: Optional[int] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Detect patterns and generate actionable insights.

        Args:
            exam_context_id: Filter by exam context (optional)
            limit: Maximum number of insights to return

        Returns:
            List of insights with pattern detection:
            [
                {
                    'type': str,  # Pattern type identifier
                    'title': str,
                    'description': str,
                    'severity': str ('info', 'warning', 'success'),
                    'actionable': str,  # Suggested action
                    'data': Dict  # Additional data
                },
                ...
            ]
        """
        from datetime import datetime, timedelta

        insights = []

        # Get overview data for patterns
        overview = self.get_analytics_overview(exam_context_id)
        subject_data = self.get_subject_analytics(exam_context_id, limit=5)
        tag_data = self.get_tag_analytics(exam_context_id)
        difficulty_data = self.get_difficulty_distribution(exam_context_id)
        streak_data = self.get_study_streak(exam_context_id)

        # Pattern 1: Streak at risk
        if streak_data['streak_at_risk']:
            insights.append({
                'type': 'STREAK_AT_RISK',
                'title': f"{streak_data['current_streak']}-day streak at risk!",
                'description': f"You haven't logged any mistakes today. Your current {streak_data['current_streak']}-day streak will break if you don't study today.",
                'severity': 'warning',
                'actionable': 'Log a review session today to maintain your streak.',
                'data': streak_data
            })

        # Pattern 2: Subject with increasing mistakes
        if subject_data:
            for subject in subject_data[:2]:  # Check top 2 subjects
                if subject['trend'] == 'up':
                    insights.append({
                        'type': 'SUBJECT_INCREASE',
                        'title': f"Increasing mistakes in {subject['subject_name']}",
                        'description': f"You're making more mistakes in {subject['full_path']} recently ({subject['mistake_count']} total, {subject['percentage']}% of all mistakes).",
                        'severity': 'warning',
                        'actionable': f"Review {subject['subject_name']} concepts and past mistakes.",
                        'data': subject
                    })

        # Pattern 3: Subject weight mismatch
        if subject_data:
            for subject in subject_data[:3]:
                if subject['exam_weight'] > 0 and subject['percentage'] > subject['exam_weight'] * 1.5:
                    insights.append({
                        'type': 'SUBJECT_WEIGHT_MISMATCH',
                        'title': f"High mistakes in {subject['subject_name']}",
                        'description': f"This subject represents {subject['exam_weight']}% of the exam but {subject['percentage']}% of your mistakes.",
                        'severity': 'warning',
                        'actionable': f"Focus extra study time on {subject['subject_name']}.",
                        'data': subject
                    })

        # Pattern 4: Difficulty skew (mostly hard questions)
        if difficulty_data['total_rated'] > 10:
            hard_percentage = (difficulty_data['distribution'][4]['count'] + difficulty_data['distribution'][5]['count']) / difficulty_data['total_rated'] * 100
            if hard_percentage > 60:
                insights.append({
                    'type': 'DIFFICULTY_SKEW',
                    'title': 'Most mistakes are on hard questions',
                    'description': f"{int(hard_percentage)}% of your mistakes are rated as hard or very hard (avg difficulty: {difficulty_data['average']}/5).",
                    'severity': 'info',
                    'actionable': 'This is normal - focus on understanding hard concepts deeply.',
                    'data': difficulty_data
                })

        # Pattern 5: Tag high frequency
        if tag_data['top_tags']:
            top_tag = tag_data['top_tags'][0]
            if top_tag['percentage'] > 30:
                insights.append({
                    'type': 'TAG_HIGH_FREQUENCY',
                    'title': f"'{top_tag['name']}' appears in {top_tag['percentage']}% of mistakes",
                    'description': f"This mistake type is very common in your practice ({top_tag['count']} occurrences).",
                    'severity': 'warning',
                    'actionable': f"Review entries tagged with '{top_tag['name']}' to identify common patterns.",
                    'data': top_tag
                })

        # Pattern 6: Progress (positive week change)
        if overview['week_change'] < -5:
            insights.append({
                'type': 'PROGRESS',
                'title': 'Great progress this week!',
                'description': f"You logged {abs(overview['week_change'])} fewer mistakes this week compared to last week.",
                'severity': 'success',
                'actionable': 'Keep up the good work! Your practice is paying off.',
                'data': {'week_change': overview['week_change']}
            })

        # Pattern 7: Incomplete sessions
        if overview['total_sessions'] > 0:
            completion_rate = overview['completed_sessions'] / overview['total_sessions'] * 100
            if completion_rate < 50:
                insights.append({
                    'type': 'SESSION_INCOMPLETE',
                    'title': 'Many incomplete review sessions',
                    'description': f"Only {int(completion_rate)}% of your sessions are marked complete ({overview['completed_sessions']}/{overview['total_sessions']}).",
                    'severity': 'warning',
                    'actionable': 'Try to complete review sessions to get better analytics.',
                    'data': {'completion_rate': completion_rate}
                })

        # Pattern 8: Long streak achievement
        if streak_data['current_streak'] >= 7:
            insights.append({
                'type': 'STREAK_ACHIEVEMENT',
                'title': f"\U0001f525 {streak_data['current_streak']}-day streak!",
                'description': f"You've studied for {streak_data['current_streak']} days in a row. Longest streak: {streak_data['longest_streak']} days.",
                'severity': 'success',
                'actionable': 'Amazing consistency! Keep it up.',
                'data': streak_data
            })

        # Sort by severity (warning > info > success) and limit
        severity_order = {'warning': 0, 'info': 1, 'success': 2}
        insights.sort(key=lambda x: severity_order.get(x['severity'], 3))

        return insights[:limit]
