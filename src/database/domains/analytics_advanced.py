"""WIMI advanced analytics operations."""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta
from app_logging import ErrorCategory


# ---------------------------------------------------------------------------
# Stage 9 — confidence multipliers keyed on ``subject_edges.weight_source``.
# Tunable in one place so the analytics layer can recalibrate without
# touching every call site.
#
# Rationale per WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 9":
# * ``official`` — pulled from a real exam outline; treat as ground truth.
# * ``user_explicit`` — user anchored this value via Stage 6 setExplicitWeight;
#   strong signal but not as authoritative as the published outline.
# * ``user_defined`` — user typed it during creation/edit but didn't anchor.
# * ``derived`` — system computed from sibling rebalance.
# * ``user_estimate`` — back-of-envelope, lowest confidence.
# ---------------------------------------------------------------------------
_WEIGHT_SOURCE_CONFIDENCE = {
    'official': 1.0,
    'user_explicit': 0.7,
    'user_defined': 0.55,
    'derived': 0.5,
    'user_estimate': 0.4,
}

# Default confidence multiplier when ``weight_source`` is NULL/unknown.
# Matches ``derived`` because that's the safest pessimistic default for
# any source we cannot identify (pre-Stage-2 legacy rows).
_WEIGHT_SOURCE_DEFAULT_CONFIDENCE = 0.5


class AdvancedAnalyticsMixin:
    """Mixin for advanced analytics. Composed into UserDatabase."""

    def get_subject_deep_dive(
        self,
        subject_id: int,
        exam_context_id: Optional[int] = None,
        primary_parent_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get comprehensive analytics for a specific subject.

        This method aggregates entries from all descendant nodes, so viewing
        a parent subject (e.g., "Cardiovascular system") will include counts
        from all child subjects (e.g., "Heart failure", "Valvular heart disease").

        Args:
            subject_id: ID of the subject to analyze
            exam_context_id: Optional exam context filter
            primary_parent_id: Optional multi-parent context filter. When set,
                narrow the rollup to entries that route through this parent's
                subtree. Lenient semantic — entries with
                ``esm.primary_parent_id IS NULL`` are still included (the user
                is implicitly claiming this parent context for ambiguous
                rows); entries with an explicit ``esm.primary_parent_id`` are
                included only when that value sits in ``primary_parent_id``'s
                subtree. Stage 9 follow-up per
                ``WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md`` /
                ``HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``; wires the
                multi-parent context selector on the subject deep-dive page.

        Returns:
            Dictionary with subject analytics:
            {
                'subject_id': int,
                'subject_name': str,
                'full_path': str,
                'exam_weight': float,
                'total_mistakes': int,  # Aggregated from all descendants
                'direct_mistakes': int,  # Only directly tagged to this subject
                'percentage': float,
                'avg_difficulty': float,
                'last_mistake_date': str,
                'this_week': int,
                'last_week': int,
                'timeline': [{'label': str, 'count': int}, ...],
                'child_subjects': [{'subject_id': int, 'subject_name': str, 'mistake_count': int, 'total_mistake_count': int}, ...],
                'mistake_types': [{'tag_name': str, 'color': str, 'count': int, 'percentage': float}, ...],
                'recent_entries': [{'entry_id': int, 'date_encountered': str, 'subject_name': str, 'reflection': str, 'explanation': str}, ...],
                'sibling_subjects': [{'subject_id': int, 'subject_name': str, 'mistake_count': int}, ...]
            }
        """
        from datetime import datetime, timedelta

        # Get subject basic info
        subject_query = """
            SELECT
                sn.id,
                sn.name as subject_name,
                sn.level_type as level,
                sn.parent_id,
                (COALESCE(sn.exam_weight_low, 0) + COALESCE(sn.exam_weight_high, sn.exam_weight_low, 0)) / 2.0 as exam_weight,
                COALESCE(sn.exam_weight_low, 0) as exam_weight_low,
                COALESCE(sn.exam_weight_high, sn.exam_weight_low, 0) as exam_weight_high
            FROM subject_nodes sn
            WHERE sn.id = ?
        """
        subject = self.fetchone(subject_query, (subject_id,))

        if not subject:
            return None

        # Build full path
        full_path = self._build_subject_path(subject_id)

        # Build CTE for finding all descendants (including self).
        # Polyhierarchy migration: descend via subject_edges (junction
        # table). UNION (not UNION ALL) so accidental data cycles do
        # not produce infinite recursion; aggregations below use
        # COUNT(DISTINCT entry_id) to avoid inflation when a leaf is
        # reachable through multiple paths.
        #
        # Stage 9 follow-up: when primary_parent_id is supplied, a second
        # CTE (parent_context_descendants) is emitted in the same WITH
        # block so the agg WHERE can narrow to entries whose explicit
        # primary_parent_id lives in the chosen parent's subtree.
        if primary_parent_id is not None:
            descendants_cte = """
                WITH RECURSIVE descendants AS (
                    SELECT id FROM subject_nodes WHERE id = ? AND status = 'active'
                    UNION
                    SELECT sn.id FROM subject_nodes sn
                    JOIN subject_edges se ON se.child_id = sn.id
                    JOIN descendants d ON se.parent_id = d.id
                    WHERE sn.status = 'active'
                ),
                parent_context_descendants AS (
                    SELECT id FROM subject_nodes WHERE id = ? AND status = 'active'
                    UNION
                    SELECT sn.id FROM subject_nodes sn
                    JOIN subject_edges se ON se.child_id = sn.id
                    JOIN parent_context_descendants d ON se.parent_id = d.id
                    WHERE sn.status = 'active'
                )
            """
            cte_seed_params = [subject_id, primary_parent_id]
        else:
            descendants_cte = """
                WITH RECURSIVE descendants AS (
                    SELECT id FROM subject_nodes WHERE id = ? AND status = 'active'
                    UNION
                    SELECT sn.id FROM subject_nodes sn
                    JOIN subject_edges se ON se.child_id = sn.id
                    JOIN descendants d ON se.parent_id = d.id
                    WHERE sn.status = 'active'
                )
            """
            cte_seed_params = [subject_id]

        # Build WHERE clause for aggregated queries (uses descendants CTE).
        #
        # Two predicates depending on whether a parent context is
        # selected. This diverges from polyhierarchy plan §5.4's strict
        # rollup (which scopes explicit-context entries to that
        # parent's chain only) — the deep-dive page is a *view*, and
        # users expect the view to show everything tagged on the
        # subject by default, then narrow by parent context. See the
        # Stage 9 polish design discussion captured in
        # ``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``.
        #
        # No filter ("All parents"): every entry tagged on the subject
        # or its descendants AND every entry routed to this subtree via
        # an explicit primary_parent. Primary_parent context is
        # ignored — this is the most permissive view.
        #
        # Filter = P: entries that route through P's chain. NULL-
        # context entries on the subject pass (they're ambiguous and
        # the user is implicitly claiming P's context for them);
        # explicit-context entries must point into P's subtree (so
        # they genuinely route through P).
        if primary_parent_id is None:
            agg_where_conditions = [
                "rs.user_id = ?",
                "(esm.subject_node_id IN (SELECT id FROM descendants) "
                "OR (esm.primary_parent_id IS NOT NULL "
                "AND esm.primary_parent_id IN (SELECT id FROM descendants)))",
            ]
        else:
            agg_where_conditions = [
                "rs.user_id = ?",
                "("
                "(esm.primary_parent_id IS NULL "
                "AND esm.subject_node_id IN (SELECT id FROM descendants))"
                " OR "
                "(esm.primary_parent_id IS NOT NULL "
                "AND esm.primary_parent_id IN (SELECT id FROM parent_context_descendants))"
                ")",
            ]
        agg_params = list(cte_seed_params) + [self.user_id]  # CTE seeds first, then WHERE

        # Build WHERE clause for direct-only queries.
        # When primary_parent_id is set, apply the same lenient filter so
        # the "direct mistakes" stat narrows consistently with the
        # aggregated rollup.
        direct_where_conditions = ["rs.user_id = ?", "esm.subject_node_id = ?"]
        direct_params = [self.user_id, subject_id]
        if primary_parent_id is not None:
            direct_where_conditions.append(
                "(esm.primary_parent_id IS NULL "
                "OR esm.primary_parent_id IN (SELECT id FROM parent_context_descendants))"
            )

        if exam_context_id:
            agg_where_conditions.append("rs.exam_context_id = ?")
            agg_params.append(exam_context_id)
            direct_where_conditions.append("rs.exam_context_id = ?")
            direct_params.append(exam_context_id)

        agg_where_clause = " AND ".join(agg_where_conditions)
        direct_where_clause = " AND ".join(direct_where_conditions)

        # Direct queries need the parent_context_descendants CTE when
        # the lenient filter is active. The descendants CTE itself is
        # unused by direct queries but kept inline for symmetry — its
        # cost is negligible and SQLite optimizes away unreferenced
        # CTEs.
        if primary_parent_id is not None:
            direct_cte = """
                WITH RECURSIVE parent_context_descendants AS (
                    SELECT id FROM subject_nodes WHERE id = ? AND status = 'active'
                    UNION
                    SELECT sn.id FROM subject_nodes sn
                    JOIN subject_edges se ON se.child_id = sn.id
                    JOIN parent_context_descendants d ON se.parent_id = d.id
                    WHERE sn.status = 'active'
                )
            """
            direct_full_params = [primary_parent_id] + direct_params
        else:
            direct_cte = ""
            direct_full_params = direct_params

        # Get total mistakes (aggregated from all descendants)
        total_query = f"""
            {descendants_cte}
            SELECT COUNT(DISTINCT qe.id) as total
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            WHERE {agg_where_clause} AND esm.mapping_type = 'primary'
        """
        total_result = self.fetchone(total_query, tuple(agg_params))
        total_mistakes = total_result['total'] or 0

        # Get direct mistakes (only this subject)
        direct_query = f"""
            {direct_cte}
            SELECT COUNT(DISTINCT qe.id) as total
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            WHERE {direct_where_clause} AND esm.mapping_type = 'primary'
        """
        direct_result = self.fetchone(direct_query, tuple(direct_full_params))
        direct_mistakes = direct_result['total'] or 0

        # Get overall total for percentage
        overall_total_query = """
            SELECT COUNT(DISTINCT qe.id) as total
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ?
        """
        overall_params = [self.user_id]
        if exam_context_id:
            overall_total_query += " AND rs.exam_context_id = ?"
            overall_params.append(exam_context_id)
        overall_total = self.fetchone(overall_total_query, tuple(overall_params))['total'] or 1

        # Get average difficulty and last mistake date (aggregated from descendants)
        stats_query = f"""
            {descendants_cte}
            SELECT
                AVG(qe.perceived_difficulty) as avg_difficulty,
                MAX(rs.date_encountered) as last_mistake_date
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            WHERE {agg_where_clause} AND esm.mapping_type = 'primary'
        """
        stats = self.fetchone(stats_query, tuple(agg_params))

        # Get this week and last week counts (aggregated from descendants)
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())
        last_week_start = week_start - timedelta(days=7)

        this_week_query = f"""
            {descendants_cte}
            SELECT COUNT(DISTINCT qe.id) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            WHERE {agg_where_clause} AND esm.mapping_type = 'primary'
                AND rs.date_encountered >= ?
        """
        this_week = self.fetchone(this_week_query, tuple(agg_params + [week_start.isoformat()]))['count'] or 0

        last_week_query = f"""
            {descendants_cte}
            SELECT COUNT(DISTINCT qe.id) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            WHERE {agg_where_clause} AND esm.mapping_type = 'primary'
                AND rs.date_encountered >= ?
                AND rs.date_encountered < ?
        """
        last_week = self.fetchone(last_week_query, tuple(agg_params + [last_week_start.isoformat(), week_start.isoformat()]))['count'] or 0

        # Get timeline (last 8 weeks) - aggregated from descendants
        timeline = []
        for i in range(7, -1, -1):
            week_end = week_start - timedelta(days=i * 7)
            week_begin = week_end - timedelta(days=7)

            week_query = f"""
                {descendants_cte}
                SELECT COUNT(DISTINCT qe.id) as count
                FROM question_entries qe
                JOIN review_sessions rs ON qe.review_session_id = rs.id
                JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
                WHERE {agg_where_clause} AND esm.mapping_type = 'primary'
                    AND rs.date_encountered >= ?
                    AND rs.date_encountered < ?
            """
            count = self.fetchone(week_query, tuple(agg_params + [week_begin.isoformat(), week_end.isoformat()]))['count'] or 0

            timeline.append({
                'label': f'W{i+1}' if i > 0 else 'This',
                'count': count
            })

        # Get child subjects with aggregated counts from their descendants
        # For each direct child, we need to count entries in that child's entire subtree
        child_query = """
            SELECT sn.id as subject_id, sn.name as subject_name
            FROM subject_nodes sn
            WHERE sn.parent_id = ? AND sn.status = 'active'
        """
        direct_children = self.fetchall(child_query, (subject_id,))

        child_subjects = []
        for child in direct_children:
            # Build CTE for this child's descendants. Polyhierarchy
            # migration: descend via subject_edges with UNION dedup.
            #
            # Stage 9 follow-up — when the page is filtered to a single
            # parent context, append parent_context_descendants here
            # too so per-child counts narrow consistently with the
            # parent-level total.
            # Mirrors the agg predicate's two-branch shape so per-child
            # counts narrow consistently with the parent-level total.
            # See the comment block on agg_where_conditions for the
            # "Show everything always" semantic.
            child_cte_parts = [
                f"""child_descendants AS (
                    SELECT id FROM subject_nodes WHERE id = {child['subject_id']} AND status = 'active'
                    UNION
                    SELECT sn.id FROM subject_nodes sn
                    JOIN subject_edges se ON se.child_id = sn.id
                    JOIN child_descendants d ON se.parent_id = d.id
                    WHERE sn.status = 'active'
                )"""
            ]
            child_extra_params = []
            if primary_parent_id is not None:
                child_cte_parts.append(
                    """parent_context_descendants AS (
                        SELECT id FROM subject_nodes WHERE id = ? AND status = 'active'
                        UNION
                        SELECT sn.id FROM subject_nodes sn
                        JOIN subject_edges se ON se.child_id = sn.id
                        JOIN parent_context_descendants d ON se.parent_id = d.id
                        WHERE sn.status = 'active'
                    )"""
                )
                child_extra_params.append(primary_parent_id)
                child_predicate = (
                    "((esm.primary_parent_id IS NULL "
                    "AND esm.subject_node_id IN (SELECT id FROM child_descendants))"
                    " OR (esm.primary_parent_id IS NOT NULL "
                    "AND esm.primary_parent_id IN (SELECT id FROM parent_context_descendants)))"
                )
            else:
                child_predicate = (
                    "(esm.subject_node_id IN (SELECT id FROM child_descendants) "
                    "OR (esm.primary_parent_id IS NOT NULL "
                    "AND esm.primary_parent_id IN (SELECT id FROM child_descendants)))"
                )
            child_cte = "WITH RECURSIVE " + ", ".join(child_cte_parts)
            child_count_query = f"""
                {child_cte}
                SELECT COUNT(DISTINCT qe.id) as total_count
                FROM question_entries qe
                JOIN review_sessions rs ON qe.review_session_id = rs.id
                JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
                WHERE rs.user_id = ?
                    AND {child_predicate}
                    AND esm.mapping_type = 'primary'
            """
            child_count_params = child_extra_params + [self.user_id]
            if exam_context_id:
                child_count_query = child_count_query.replace(
                    "AND esm.mapping_type = 'primary'",
                    "AND esm.mapping_type = 'primary' AND rs.exam_context_id = ?"
                )
                child_count_params.append(exam_context_id)

            result = self.fetchone(child_count_query, tuple(child_count_params))
            total_count = result['total_count'] or 0

            if total_count > 0:
                child_subjects.append({
                    'subject_id': child['subject_id'],
                    'subject_name': child['subject_name'],
                    'mistake_count': total_count,  # Now shows aggregated count
                    'total_mistake_count': total_count
                })

        # Sort by count descending and limit to 5
        child_subjects.sort(key=lambda x: x['mistake_count'], reverse=True)
        child_subjects = child_subjects[:5]

        # Get mistake types (tags) - aggregated from descendants
        tags_query = f"""
            {descendants_cte}
            SELECT
                t.tag_name,
                t.color_hex,
                COUNT(DISTINCT qe.id) as count
            FROM tags t
            JOIN entry_tags et ON t.id = et.tag_id
            JOIN question_entries qe ON et.question_entry_id = qe.id
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            WHERE {agg_where_clause} AND esm.mapping_type = 'primary'
            GROUP BY t.id, t.tag_name, t.color_hex
            ORDER BY count DESC
            LIMIT 5
        """
        mistake_types = self.fetchall(tags_query, tuple(agg_params))

        # Calculate percentages for tags
        for tag in mistake_types:
            tag['percentage'] = round(tag['count'] / total_mistakes * 100, 1) if total_mistakes > 0 else 0

        # Get recent entries - aggregated from descendants
        entries_query = f"""
            {descendants_cte}
            SELECT
                qe.id as entry_id,
                rs.date_encountered,
                sn.name as subject_name,
                qe.reflection,
                qe.explanation
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            JOIN subject_nodes sn ON esm.subject_node_id = sn.id
            WHERE {agg_where_clause} AND esm.mapping_type = 'primary'
            ORDER BY rs.date_encountered DESC
            LIMIT 5
        """
        recent_entries = self.fetchall(entries_query, tuple(agg_params))

        # Get sibling subjects (same parent)
        siblings_query = """
            SELECT
                sn.id as subject_id,
                sn.name as subject_name,
                COUNT(DISTINCT qe.id) as mistake_count
            FROM subject_nodes sn
            LEFT JOIN entry_subject_mappings esm ON sn.id = esm.subject_node_id
            LEFT JOIN question_entries qe ON esm.question_entry_id = qe.id
            LEFT JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE sn.parent_id = (SELECT parent_id FROM subject_nodes WHERE id = ?)
                AND sn.id != ?
        """
        sibling_params = [subject_id, subject_id]
        if exam_context_id:
            siblings_query += " AND (rs.exam_context_id = ? OR rs.exam_context_id IS NULL)"
            sibling_params.append(exam_context_id)
        if not exam_context_id:
            # Need to filter by user through review_sessions
            siblings_query += " AND (rs.user_id = ? OR rs.user_id IS NULL)"
            sibling_params.append(self.user_id)
        siblings_query += " GROUP BY sn.id, sn.name HAVING mistake_count > 0 ORDER BY mistake_count DESC LIMIT 3"

        sibling_subjects = self.fetchall(siblings_query, tuple(sibling_params))

        # Stage 9 polish — orientation fields for the multi-parent
        # selector. Both are cheap to compute and let the page render a
        # dynamic breadcrumb + an explanatory banner that turns the
        # selector from "looks broken on leaves" into "tells the user
        # what view they're in and what data they're not seeing".
        path_via_parent = self._build_path_via_parent(
            subject_id, primary_parent_id
        ) if primary_parent_id is not None else None

        # Count entries on THIS subject that would be hidden by the
        # current view. Under "Show everything always" semantics, the
        # no-filter view hides nothing tagged on the subject, so this
        # count is 0. When a parent context is active, the count is
        # entries on the subject with an explicit primary_parent that
        # routes through a DIFFERENT parent (so they're visible on
        # that parent's deep-dive but not on this view). The banner
        # uses this to surface "N more entries exist with explicit
        # contexts elsewhere".
        if primary_parent_id is None:
            entries_scoped_elsewhere = 0
        else:
            scoped_elsewhere_query = f"""
                {descendants_cte}
                SELECT COUNT(DISTINCT qe.id) AS n
                FROM question_entries qe
                JOIN review_sessions rs ON qe.review_session_id = rs.id
                JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
                WHERE rs.user_id = ?
                  AND esm.subject_node_id = ?
                  AND esm.primary_parent_id IS NOT NULL
                  AND esm.primary_parent_id NOT IN (SELECT id FROM parent_context_descendants)
                  AND esm.mapping_type = 'primary'
            """
            scoped_params = list(cte_seed_params) + [self.user_id, subject_id]
            scoped_elsewhere_row = self.fetchone(
                scoped_elsewhere_query, tuple(scoped_params)
            )
            entries_scoped_elsewhere = (
                scoped_elsewhere_row['n'] if scoped_elsewhere_row else 0
            ) or 0

        return {
            'subject_id': subject_id,
            'subject_name': subject['subject_name'],
            'full_path': full_path,
            'path_via_parent': path_via_parent,
            'entries_scoped_elsewhere': entries_scoped_elsewhere,
            'exam_weight': subject['exam_weight'],
            'exam_weight_low': subject.get('exam_weight_low', 0.0) or 0.0,
            'exam_weight_high': subject.get('exam_weight_high', 0.0) or 0.0,
            'total_mistakes': total_mistakes,  # Aggregated from all descendants
            'direct_mistakes': direct_mistakes,  # Only directly tagged to this subject
            'percentage': round(total_mistakes / overall_total * 100, 1) if overall_total > 0 else 0,
            'avg_difficulty': round(stats['avg_difficulty'], 1) if stats['avg_difficulty'] else None,
            'last_mistake_date': stats['last_mistake_date'],
            'this_week': this_week,
            'last_week': last_week,
            'timeline': timeline,
            'child_subjects': child_subjects,
            'mistake_types': mistake_types,
            'recent_entries': recent_entries,
            'sibling_subjects': sibling_subjects
        }

    def _build_path_via_parent(
        self, subject_id: int, primary_parent_id: int
    ) -> Optional[str]:
        """Return the breadcrumb path from root → primary_parent_id →
        ... → subject_id, formatted as ``A > B > ... > Subject``.

        Picks the first path returned by :meth:`EdgesMixin.get_paths_to_root`
        that includes ``primary_parent_id`` (paths are primary-first, then
        deterministic). Returns ``None`` when no such path exists (the
        caller asked for a context that isn't actually an ancestor — the
        page should fall back to ``full_path``).
        """
        paths = self.get_paths_to_root(subject_id)
        candidate = next(
            (p for p in paths if primary_parent_id in p), None
        )
        if not candidate:
            return None
        rows = self.fetchall(
            f"SELECT id, name FROM subject_nodes "
            f"WHERE id IN ({','.join('?' * len(candidate))})",
            tuple(candidate),
        )
        names = {row['id']: row['name'] for row in rows}
        return ' > '.join(names.get(nid, f'#{nid}') for nid in candidate)

    # =============================================================================
    # STAGE 7: HEATMAP & STREAK TRACKING METHODS
    # =============================================================================

    def get_activity_heatmap(
        self,
        exam_context_id: Optional[int] = None,
        weeks: int = 16
    ) -> Dict[str, Any]:
        """
        Get activity data for GitHub-style heatmap visualization.

        Args:
            exam_context_id: Optional exam context filter
            weeks: Number of weeks to include (default 16)

        Returns:
            {
                'days': [
                    {'date': '2025-12-25', 'count': 5, 'level': 3},
                    ...
                ],
                'current_streak': 7,
                'longest_streak': 14,
                'total_active_days': 45,
                'week_start': 'sunday'
            }
        """
        from datetime import timedelta

        today = datetime.now().date()

        # Calculate start date (weeks ago, aligned to Sunday)
        days_since_sunday = (today.weekday() + 1) % 7
        this_sunday = today - timedelta(days=days_since_sunday)
        start_date = this_sunday - timedelta(weeks=weeks - 1, days=6)

        # Get all entry counts by date
        query = """
            SELECT
                DATE(rs.date_encountered) as entry_date,
                COUNT(DISTINCT qe.id) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ?
                AND DATE(rs.date_encountered) >= ?
                AND DATE(rs.date_encountered) <= ?
        """
        params = [self.user_id, start_date.isoformat(), today.isoformat()]

        if exam_context_id:
            query += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)

        query += " GROUP BY DATE(rs.date_encountered)"

        results = self.fetchall(query, tuple(params))

        # Create a dict for quick lookup
        date_counts = {row['entry_date']: row['count'] for row in results}

        # Find max count for level calculation
        max_count = max(date_counts.values()) if date_counts else 0

        # Generate all days in range
        days = []
        current_date = start_date
        while current_date <= today:
            count = date_counts.get(current_date.isoformat(), 0)

            # Calculate level (0-4)
            if count == 0:
                level = 0
            elif max_count > 0:
                ratio = count / max_count
                if ratio <= 0.25:
                    level = 1
                elif ratio <= 0.5:
                    level = 2
                elif ratio <= 0.75:
                    level = 3
                else:
                    level = 4
            else:
                level = 0

            days.append({
                'date': current_date.isoformat(),
                'count': count,
                'level': level
            })

            current_date += timedelta(days=1)

        # Calculate streak info
        streak_info = self._calculate_streak_info(exam_context_id)

        # Count total active days in range
        total_active_days = sum(1 for day in days if day['count'] > 0)

        return {
            'days': days,
            'current_streak': streak_info['current_streak'],
            'longest_streak': streak_info['longest_streak'],
            'total_active_days': total_active_days,
            'total_days': len(days),
            'week_start': 'sunday',
            'start_date': start_date.isoformat(),
            'end_date': today.isoformat()
        }

    def get_streak_info(
        self,
        exam_context_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get detailed streak information.

        Args:
            exam_context_id: Optional exam context filter

        Returns:
            {
                'current_streak': int,
                'longest_streak': int,
                'streak_start_date': str,
                'last_active_date': str,
                'is_active_today': bool,
                'streak_at_risk': bool
            }
        """
        return self._calculate_streak_info(exam_context_id)

    def _calculate_streak_info(
        self,
        exam_context_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Calculate streak information from entry data.

        A streak is consecutive days with at least one entry.
        """
        from datetime import timedelta

        today = datetime.now().date()

        # Get all unique dates with entries, ordered descending
        query = """
            SELECT DISTINCT DATE(rs.date_encountered) as entry_date
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ?
        """
        params = [self.user_id]

        if exam_context_id:
            query += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)

        query += " ORDER BY entry_date DESC"

        results = self.fetchall(query, tuple(params))

        if not results:
            return {
                'current_streak': 0,
                'longest_streak': 0,
                'streak_start_date': None,
                'last_active_date': None,
                'is_active_today': False,
                'streak_at_risk': False
            }

        # Convert to date objects
        active_dates = set()
        for row in results:
            if row['entry_date']:
                if isinstance(row['entry_date'], str):
                    active_dates.add(datetime.strptime(row['entry_date'], '%Y-%m-%d').date())
                else:
                    active_dates.add(row['entry_date'])

        if not active_dates:
            return {
                'current_streak': 0,
                'longest_streak': 0,
                'streak_start_date': None,
                'last_active_date': None,
                'is_active_today': False,
                'streak_at_risk': False
            }

        # Find the most recent active date
        last_active = max(active_dates)
        is_active_today = last_active == today

        # Calculate current streak
        # Start from today (or yesterday if not active today)
        check_date = today if is_active_today else today - timedelta(days=1)
        current_streak = 0
        streak_start_date = None

        # Check if we need to consider yesterday for current streak
        if not is_active_today:
            # Only count streak if yesterday was active
            if (today - timedelta(days=1)) not in active_dates:
                current_streak = 0
                streak_start_date = None
            else:
                check_date = today - timedelta(days=1)

        # Count consecutive days backwards
        if is_active_today or (today - timedelta(days=1)) in active_dates:
            while check_date in active_dates:
                current_streak += 1
                streak_start_date = check_date
                check_date -= timedelta(days=1)

        # Calculate longest streak (all time)
        sorted_dates = sorted(active_dates)
        longest_streak = 0
        temp_streak = 1

        for i in range(1, len(sorted_dates)):
            if (sorted_dates[i] - sorted_dates[i-1]).days == 1:
                temp_streak += 1
            else:
                longest_streak = max(longest_streak, temp_streak)
                temp_streak = 1
        longest_streak = max(longest_streak, temp_streak)

        # Streak is at risk if user was active yesterday but not today
        streak_at_risk = (
            not is_active_today and
            current_streak > 0 and
            (today - timedelta(days=1)) in active_dates
        )

        return {
            'current_streak': current_streak,
            'longest_streak': longest_streak,
            'streak_start_date': streak_start_date.isoformat() if streak_start_date else None,
            'last_active_date': last_active.isoformat() if last_active else None,
            'is_active_today': is_active_today,
            'streak_at_risk': streak_at_risk
        }

    # =============================================================================
    # STAGE 10: SOURCE COMPARISON METHODS
    # =============================================================================

    def get_source_comparison(
        self,
        exam_context_id: Optional[int] = None,
        months: int = 6
    ) -> Dict[str, Any]:
        """
        Get source comparison data with performance trends.

        Args:
            exam_context_id: Optional exam context filter
            months: Number of months to analyze

        Returns:
            Dictionary with source stats and trends
        """
        from datetime import timedelta
        from collections import defaultdict

        # Calculate date range
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=months * 30)

        # Get entries by source
        query = """
            SELECT
                qs.id as source_id,
                qs.source_name,
                COUNT(qe.id) as entry_count,
                AVG(qe.perceived_difficulty) as avg_difficulty,
                strftime('%Y-%m', qe.created_at) as month
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            LEFT JOIN question_sources qs ON rs.question_source_id = qs.id
            WHERE rs.user_id = ?
                AND qe.is_draft = FALSE
                AND DATE(qe.created_at) >= ?
        """
        params = [self.user_id, start_date.isoformat()]

        if exam_context_id:
            query += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)

        query += " GROUP BY qs.id, strftime('%Y-%m', qe.created_at) ORDER BY month"

        results = self.fetchall(query, tuple(params))

        # Process results
        sources = {}
        monthly_data = defaultdict(lambda: defaultdict(int))

        for row in results:
            source_id = row['source_id'] or 0
            source_name = row['source_name'] or 'Unspecified'
            month = row['month']

            if source_id not in sources:
                sources[source_id] = {
                    'source_id': source_id,
                    'source_name': source_name,
                    'total_entries': 0,
                    'avg_difficulty': 0,
                    'difficulty_sum': 0,
                    'difficulty_count': 0
                }

            sources[source_id]['total_entries'] += row['entry_count']
            if row['avg_difficulty']:
                sources[source_id]['difficulty_sum'] += row['avg_difficulty'] * row['entry_count']
                sources[source_id]['difficulty_count'] += row['entry_count']

            monthly_data[month][source_id] = row['entry_count']

        # Calculate averages and trends
        total_entries = sum(s['total_entries'] for s in sources.values())
        source_list = []

        for source_id, data in sources.items():
            if data['difficulty_count'] > 0:
                data['avg_difficulty'] = round(data['difficulty_sum'] / data['difficulty_count'], 1)

            # Calculate percentage
            pct = (data['total_entries'] / total_entries * 100) if total_entries > 0 else 0

            # Calculate trend (compare recent vs earlier)
            trend = self._calculate_source_trend(source_id, monthly_data)

            # Get top subject for this source
            top_subject = self._get_top_subject_for_source(source_id, exam_context_id)

            source_list.append({
                'source_id': source_id,
                'source_name': data['source_name'],
                'entry_count': data['total_entries'],
                'percentage': round(pct, 1),
                'avg_difficulty': data['avg_difficulty'],
                'trend': trend,
                'top_subject': top_subject
            })

        # Sort by entry count descending
        source_list.sort(key=lambda x: x['entry_count'], reverse=True)

        # Generate monthly timeline data for chart
        timeline = self._generate_source_timeline(monthly_data, sources, months)

        return {
            'sources': source_list,
            'timeline': timeline,
            'total_entries': total_entries,
            'months_analyzed': months
        }

    def _calculate_source_trend(
        self,
        source_id: int,
        monthly_data: dict
    ) -> str:
        """
        Calculate trend for a source based on monthly data.
        Returns: 'improving', 'stable', or 'worsening'
        """
        months = sorted(monthly_data.keys())
        if len(months) < 2:
            return 'stable'

        # Get recent vs earlier counts
        mid = len(months) // 2
        earlier_months = months[:mid] if mid > 0 else months[:1]
        recent_months = months[mid:] if mid > 0 else months[1:]

        earlier_avg = sum(monthly_data[m].get(source_id, 0) for m in earlier_months) / max(len(earlier_months), 1)
        recent_avg = sum(monthly_data[m].get(source_id, 0) for m in recent_months) / max(len(recent_months), 1)

        # For mistakes, fewer is better (improving)
        if recent_avg < earlier_avg * 0.8:
            return 'improving'
        elif recent_avg > earlier_avg * 1.2:
            return 'worsening'
        else:
            return 'stable'

    def _get_top_subject_for_source(
        self,
        source_id: int,
        exam_context_id: Optional[int] = None
    ) -> Optional[str]:
        """
        Get the most common subject for mistakes from a source.
        """
        query = """
            SELECT sn.name, COUNT(*) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            JOIN subject_nodes sn ON esm.subject_node_id = sn.id
            WHERE rs.user_id = ?
                AND qe.is_draft = FALSE
                AND esm.mapping_type = 'primary'
        """
        params = [self.user_id]

        if source_id:
            query += " AND rs.question_source_id = ?"
            params.append(source_id)
        else:
            query += " AND rs.question_source_id IS NULL"

        if exam_context_id:
            query += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)

        query += " GROUP BY sn.id ORDER BY count DESC LIMIT 1"

        result = self.fetchone(query, tuple(params))
        return result['name'] if result else None

    def _generate_source_timeline(
        self,
        monthly_data: dict,
        sources: dict,
        months: int
    ) -> List[Dict[str, Any]]:
        """
        Generate timeline data for the line chart.
        """
        from datetime import timedelta

        # Generate all months in range
        end_date = datetime.now().date()
        timeline = []

        for i in range(months, -1, -1):
            month_date = end_date - timedelta(days=i * 30)
            month_key = month_date.strftime('%Y-%m')
            month_label = month_date.strftime('%b %Y')

            month_entry = {
                'month': month_key,
                'label': month_label,
                'sources': {}
            }

            for source_id, source_data in sources.items():
                count = monthly_data.get(month_key, {}).get(source_id, 0)
                month_entry['sources'][source_data['source_name']] = count

            timeline.append(month_entry)

        return timeline

    def get_performance_over_time(
        self,
        exam_context_id: Optional[int] = None,
        period: str = 'weekly',
        weeks: int = 12
    ) -> List[Dict[str, Any]]:
        """
        Get performance metrics over time.

        Args:
            exam_context_id: Optional exam context filter
            period: 'daily', 'weekly', or 'monthly'
            weeks: Number of weeks to analyze

        Returns:
            List of period data with entry counts and difficulty
        """
        from datetime import timedelta

        end_date = datetime.now().date()
        start_date = end_date - timedelta(weeks=weeks)

        # Determine grouping
        if period == 'daily':
            date_format = '%Y-%m-%d'
        elif period == 'monthly':
            date_format = '%Y-%m'
        else:  # weekly
            date_format = '%Y-%W'

        query = f"""
            SELECT
                strftime('{date_format}', qe.created_at) as period,
                COUNT(qe.id) as entry_count,
                AVG(qe.perceived_difficulty) as avg_difficulty,
                COUNT(DISTINCT DATE(qe.created_at)) as active_days
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ?
                AND qe.is_draft = FALSE
                AND DATE(qe.created_at) >= ?
        """
        params = [self.user_id, start_date.isoformat()]

        if exam_context_id:
            query += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)

        query += f" GROUP BY strftime('{date_format}', qe.created_at) ORDER BY period"

        results = self.fetchall(query, tuple(params))

        performance = []
        for row in results:
            performance.append({
                'period': row['period'],
                'entry_count': row['entry_count'],
                'avg_difficulty': round(row['avg_difficulty'], 1) if row['avg_difficulty'] else None,
                'active_days': row['active_days']
            })

        return performance


    # =============================================================================
    # STAGE 13: SUBJECT VS EXAM WEIGHT ANALYSIS METHODS
    # =============================================================================

    def get_subject_exam_weight_analysis(
        self,
        exam_context_id: int
    ) -> Dict[str, Any]:
        """
        Compare mistake distribution against exam weight distribution.

        This analysis helps identify if study time is aligned with exam priorities.

        Args:
            exam_context_id: Exam context ID (required)

        Returns:
            {
                'subjects': [
                    {
                        'subject_id': int,
                        'subject_name': str,
                        'full_path': str,
                        'mistake_percentage': float,
                        'exam_weight': float,
                        'difference': float,
                        'quadrant': str,
                        'mistake_count': int
                    },
                    ...
                ],
                'quadrant_analysis': {
                    'priority': [...],
                    'well_maintained': [...],
                    'reduce_focus': [...],
                    'low_priority': [...]
                },
                'efficiency_score': float,
                'efficiency_rating': str,
                'total_mistakes': int,
                'weighted_subjects': int
            }
        """
        if not exam_context_id:
            raise ValueError("exam_context_id is required for weight analysis")

        # First get the exam_name for the context
        exam_config = self.get_exam_context_config(exam_context_id)
        if not exam_config:
            raise ValueError(f"Exam context {exam_context_id} not found")

        exam_name = exam_config.exam_name

        # Get mistake counts by subject
        # Using correct schema: entry_subject_mappings table, subject_nodes columns
        # Use midpoint for calculations, but also return low/high for display
        #
        # Stage 9: ``weight_source`` is now read from
        # ``subject_edges.weight_source`` (the polyhierarchy-canonical
        # column). When a node has multiple parent edges, the dominant
        # edge wins (highest ``relative_weight``, tie-break on
        # ``is_primary DESC, edge_id ASC``). We compute the dominant
        # source per node in a separate pass below so the main query
        # stays readable and we don't need a multi-column window
        # function that SQLite handles slowly. ``subject_nodes.weight_source``
        # is used as a defensive fallback when an edge has
        # ``weight_source=NULL`` (should not happen post-Stage-2 but
        # legacy data may exist).
        query = """
            SELECT
                sn.id as subject_id,
                sn.name as subject_name,
                sn.name as full_path,
                sn.weight_source as node_weight_source,
                (COALESCE(sn.exam_weight_low, 0) + COALESCE(sn.exam_weight_high, sn.exam_weight_low, 0)) / 2.0 as exam_weight,
                COALESCE(sn.exam_weight_low, 0) as exam_weight_low,
                COALESCE(sn.exam_weight_high, sn.exam_weight_low, 0) as exam_weight_high,
                COUNT(DISTINCT qe.id) as mistake_count
            FROM subject_nodes sn
            LEFT JOIN entry_subject_mappings esm ON sn.id = esm.subject_node_id
            LEFT JOIN question_entries qe ON esm.question_entry_id = qe.id
            LEFT JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE sn.exam_context = ?
                AND sn.status = 'active'
                AND COALESCE(sn.exam_weight_low, 0) > 0
                AND (qe.is_draft = FALSE OR qe.id IS NULL)
                AND (rs.user_id = ? OR qe.id IS NULL)
            GROUP BY sn.id, sn.name, sn.exam_weight_low, sn.exam_weight_high, sn.weight_source
            ORDER BY exam_weight DESC
        """

        results = self.fetchall(query, (exam_name, self.user_id))

        # Stage 9: dominant-edge weight_source per node. One query
        # over ``subject_edges`` returns the edge with the largest
        # ``relative_weight`` per child. We feed the q_typical hint
        # from the System range when available (so multi-parent ties
        # break toward the heavier-weighted parent context); for the
        # plain ``relative_weight`` ordering, ties resolve via
        # ``is_primary DESC, id ASC`` per the design doc.
        dominant_sources = self._get_dominant_edge_sources(exam_name)

        if not results:
            return {
                'subjects': [],
                'quadrant_analysis': {
                    'priority': [],
                    'well_maintained': [],
                    'reduce_focus': [],
                    'low_priority': []
                },
                'efficiency_score': 0,
                'efficiency_rating': 'No Data',
                'total_mistakes': 0,
                'weighted_subjects': 0,
                # Stage 9: keep the shape stable so the dashboard's
                # "Confidence breakdown" card can render an empty state
                # without null-checking the whole branch.
                'weight_source_distribution': {
                    'official': 0,
                    'user_explicit': 0,
                    'user_defined': 0,
                    'derived': 0,
                    'user_estimate': 0,
                    'total': 0,
                },
            }

        # Calculate total mistakes
        total_mistakes = sum(row['mistake_count'] for row in results)

        # Calculate mistake percentages
        subjects = []
        for row in results:
            mistake_pct = (row['mistake_count'] / total_mistakes * 100) if total_mistakes > 0 else 0
            weight_pct = row['exam_weight']  # This is now the midpoint
            weight_low = row['exam_weight_low']
            weight_high = row['exam_weight_high']
            difference = mistake_pct - weight_pct

            # Determine quadrant using range-aware categorization
            quadrant = self._categorize_subject_quadrant(mistake_pct, weight_low, weight_high)

            # Stage 9: pick the dominant edge's weight_source. Falls
            # back to the legacy node-level value when the node has no
            # incoming edges (System-level nodes always do) or all
            # edges have weight_source=NULL (pre-Stage-2 legacy data).
            subject_id = row['subject_id']
            ws = dominant_sources.get(subject_id)
            if ws is None:
                ws = row['node_weight_source'] or 'derived'

            subjects.append({
                'subject_id': subject_id,
                'subject_name': row['subject_name'],
                'full_path': row['full_path'],
                'mistake_percentage': round(mistake_pct, 1),
                'exam_weight': round(weight_pct, 1),  # Midpoint for calculations
                'exam_weight_low': round(weight_low, 1),  # Low bound for display
                'exam_weight_high': round(weight_high, 1),  # High bound for display
                'difference': round(difference, 1),
                'quadrant': quadrant,
                'mistake_count': row['mistake_count'],
                'weight_source': ws,
            })

        # Group by quadrant
        quadrant_analysis = {
            'priority': [s for s in subjects if s['quadrant'] == 'priority'],
            'well_maintained': [s for s in subjects if s['quadrant'] == 'well-maintained'],
            'reduce_focus': [s for s in subjects if s['quadrant'] == 'reduce-focus'],
            'low_priority': [s for s in subjects if s['quadrant'] == 'low-priority']
        }

        # Calculate efficiency score
        efficiency_score = self._calculate_efficiency_score(subjects)
        efficiency_rating = self._get_efficiency_rating(efficiency_score)

        # Stage 9 — bundle the weight_source distribution so dashboards
        # rendering the "Confidence breakdown" card don't need a
        # separate round trip. The breakdown counts every subject in the
        # ``subjects`` list (the ones with a weighted exam range > 0),
        # so it matches the rendered analytics surface exactly.
        weight_source_distribution = self._build_source_distribution(
            subjects
        )

        return {
            'subjects': subjects,
            'quadrant_analysis': quadrant_analysis,
            'efficiency_score': round(efficiency_score, 1),
            'efficiency_rating': efficiency_rating,
            'total_mistakes': total_mistakes,
            'weighted_subjects': len(subjects),
            'weight_source_distribution': weight_source_distribution,
        }

    def _categorize_subject_quadrant(
        self,
        mistake_pct: float,
        weight_low: float,
        weight_high: float
    ) -> str:
        """
        Categorize a subject into one of four quadrants with range-aware comparison.

        Args:
            mistake_pct: Percentage of total mistakes in this subject
            weight_low: Low bound of exam weight range
            weight_high: High bound of exam weight range

        Returns:
            Quadrant name: 'priority', 'well-maintained', 'reduce-focus', or 'low-priority'
        """
        HIGH_WEIGHT_THRESHOLD = 10.0
        OVER_REPRESENTED_THRESHOLD = 1.3

        # Use midpoint for threshold comparisons
        midpoint = (weight_low + weight_high) / 2.0

        # If mistake_pct falls within the weight range, be less strict about categorization
        is_within_range = weight_low <= mistake_pct <= weight_high

        is_high_weight = midpoint >= HIGH_WEIGHT_THRESHOLD

        # Use high bound for over-representation check to be conservative
        # (only flag as over-represented if clearly above the range)
        is_over_represented = mistake_pct > (weight_high * OVER_REPRESENTED_THRESHOLD)

        # Subjects within their weight range are considered well-aligned
        if is_within_range:
            if is_high_weight:
                return 'well-maintained'
            else:
                return 'low-priority'

        if is_high_weight and is_over_represented:
            return 'priority'
        elif is_high_weight and not is_over_represented:
            return 'well-maintained'
        elif not is_high_weight and is_over_represented:
            return 'reduce-focus'
        else:
            return 'low-priority'

    def _calculate_efficiency_score(
        self,
        subjects: List[Dict[str, Any]]
    ) -> float:
        """
        Calculate study efficiency score (0-100) with confidence weighting.

        Formula: 100 - Σ(penalty × confidence × weight_factor)

        Subjects with wider weight ranges have less certain efficiency scores,
        so their impact on the overall score is reduced.

        Stage 9 update: confidence is further multiplied by a per-source
        factor (see ``_WEIGHT_SOURCE_CONFIDENCE``). A narrow range backed
        by ``user_estimate`` should not score as confidently as a narrow
        range backed by ``official``. The final confidence used in the
        penalty term is ``min(range_derived_confidence,
        source_derived_confidence)`` so the *less* certain of the two
        signals dominates — adding a low-confidence source can never
        improve the score, only lower it.
        """
        if not subjects:
            return 0

        total_penalty = 0
        for subject in subjects:
            mistake_pct = subject['mistake_percentage']
            weight_low = subject.get('exam_weight_low', subject['exam_weight'])
            weight_high = subject.get('exam_weight_high', subject['exam_weight'])
            midpoint = (weight_low + weight_high) / 2.0
            range_width = weight_high - weight_low

            # If mistake_pct is within the range, reduce penalty
            if weight_low <= mistake_pct <= weight_high:
                # Within range: minimal penalty based on distance from midpoint
                deviation = abs(mistake_pct - midpoint)
            else:
                # Outside range: penalty based on distance from nearest bound
                if mistake_pct < weight_low:
                    deviation = weight_low - mistake_pct
                else:
                    deviation = mistake_pct - weight_high

            # Confidence factor: narrower ranges = higher confidence (1.0 max)
            # Range of 0 = 100% confidence, range of 10+ = 50% confidence minimum
            range_confidence = max(0.5, 1 - (range_width / 20.0))

            # Stage 9 — source-derived confidence. Subjects without a
            # ``weight_source`` field (e.g. legacy fixtures or tests
            # built before Stage 9) fall back to the pessimistic default
            # so the new factor never silently *raises* a legacy score.
            source = subject.get('weight_source')
            source_confidence = _WEIGHT_SOURCE_CONFIDENCE.get(
                source, _WEIGHT_SOURCE_DEFAULT_CONFIDENCE
            )

            # The penalty uses the MIN of the two so the less certain
            # of the two signals dominates: a narrow range backed by
            # ``user_estimate`` is *less* confident than a wide range
            # backed by ``official`` because the official outline is
            # ground truth even when fuzzy.
            confidence = min(range_confidence, source_confidence)

            # Weight factor: higher weight subjects have more impact
            weight_factor = midpoint / 100

            penalty = deviation * confidence * weight_factor
            total_penalty += penalty

        score = max(0, 100 - total_penalty)
        return score

    def _get_efficiency_rating(
        self,
        score: float
    ) -> str:
        """Convert efficiency score to a rating."""
        if score >= 85:
            return 'Excellent'
        elif score >= 70:
            return 'Good'
        elif score >= 50:
            return 'Fair'
        else:
            return 'Needs Improvement'

    # =============================================================================
    # STAGE 9: WEIGHT-SOURCE-AWARE ANALYTICS HELPERS
    # =============================================================================

    def _get_dominant_edge_sources(
        self, exam_name: str
    ) -> Dict[int, str]:
        """Return ``{child_id: dominant_weight_source}`` for an exam's edges.

        Stage 9 (WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md). The "dominant"
        edge is the one with the highest ``relative_weight`` under that
        child node; ties are broken by ``is_primary DESC, id ASC`` so the
        canonical primary edge wins when weights are equal.

        Why this exists
        ---------------
        After the polyhierarchy migration, a single subject node can
        appear under multiple parent edges, each with its own
        ``weight_source`` (e.g. PE under Respiratory might be
        ``'official'`` while PE under Pregnancy is ``'derived'``). The
        analytics row for a node needs a single source label, so we
        pick the edge that contributes the most weight to that node's
        rollup — that is the source the user has actually committed to.

        Args:
            exam_name: The ``subject_nodes.exam_context`` value used to
                scope edges to the exam under analysis.

        Returns:
            Dict mapping ``child_id -> weight_source`` (string). Children
            with no incoming edge are simply absent — callers should
            fall back to ``subject_nodes.weight_source`` for those.
        """
        # SQLite has no QUALIFY clause, so we use a self-join with
        # row_number() simulated via the ORDER BY in a sub-select.
        # This pattern works on every SQLite version WIMI supports
        # (3.35+) because window functions have been available since
        # 3.25. Filtering edges by exam_name lets us return the same
        # source map for repeated calls without scanning the whole
        # subject_edges table.
        rows = self.fetchall(
            """
            WITH ranked_edges AS (
                SELECT
                    se.id           AS edge_id,
                    se.child_id     AS child_id,
                    se.weight_source AS weight_source,
                    se.relative_weight AS relative_weight,
                    se.is_primary   AS is_primary,
                    ROW_NUMBER() OVER (
                        PARTITION BY se.child_id
                        ORDER BY
                            COALESCE(se.relative_weight, 0) DESC,
                            se.is_primary DESC,
                            se.id ASC
                    ) AS rn
                FROM subject_edges se
                JOIN subject_nodes child_sn ON child_sn.id = se.child_id
                WHERE child_sn.exam_context = ?
                  AND child_sn.status = 'active'
            )
            SELECT child_id, weight_source
            FROM ranked_edges
            WHERE rn = 1 AND weight_source IS NOT NULL
            """,
            (exam_name,),
        )
        return {row['child_id']: row['weight_source'] for row in rows}

    def _build_source_distribution(
        self, subjects: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """Count subjects by their ``weight_source`` for the breakdown card."""
        counts: Dict[str, int] = {
            'official': 0,
            'user_explicit': 0,
            'user_defined': 0,
            'derived': 0,
            'user_estimate': 0,
        }
        for subj in subjects:
            src = subj.get('weight_source') or 'derived'
            if src not in counts:
                # Unknown source value — bucket under 'derived' so the
                # totals always reconcile.
                counts['derived'] += 1
            else:
                counts[src] += 1
        counts['total'] = sum(
            v for k, v in counts.items() if k != 'total'
        )
        return counts

    def get_weight_source_breakdown(
        self,
        exam_context_id: int,
    ) -> Dict[str, int]:
        """Return per-source subject counts for the analytics dashboard.

        Stage 9 (WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md). Powers the
        "Confidence breakdown" card on the analytics dashboard:

            Weight Sources
              ● 12 official
              ⚓ 8 user-anchored
              ○ 30 derived
              ⊘ 5 estimated

        For each subject node in the exam, we identify the dominant
        edge (highest ``relative_weight``, tie-break on ``is_primary
        DESC, edge_id ASC``) and count by that edge's
        ``weight_source``. Nodes without an incoming edge fall back to
        the legacy ``subject_nodes.weight_source`` column. Nodes whose
        weight range is zero (``exam_weight_low <= 0``) are excluded —
        they don't show up in the weight analysis and would inflate the
        "derived" bucket misleadingly.

        Args:
            exam_context_id: The exam context whose subjects are counted.

        Returns:
            Dict with keys ``official``, ``user_explicit``,
            ``user_defined``, ``derived``, ``user_estimate``, ``total``.
            ``total`` is the sum of the other five buckets, never
            including itself.

        Raises:
            ValueError: When ``exam_context_id`` does not exist.
        """
        exam_config = self.get_exam_context_config(exam_context_id)
        if not exam_config:
            raise ValueError(f"Exam context {exam_context_id} not found")
        exam_name = exam_config.exam_name

        dominant_sources = self._get_dominant_edge_sources(exam_name)

        # Pull every node in the exam that carries a non-zero weight
        # range. Mirrors the filter in get_subject_exam_weight_analysis
        # so the breakdown counts the same population the dashboard
        # actually displays.
        nodes = self.fetchall(
            """
            SELECT sn.id, sn.weight_source AS node_weight_source
            FROM subject_nodes sn
            WHERE sn.exam_context = ?
              AND sn.status = 'active'
              AND COALESCE(sn.exam_weight_low, 0) > 0
            """,
            (exam_name,),
        )

        subjects: List[Dict[str, Any]] = []
        for row in nodes:
            sid = row['id']
            ws = dominant_sources.get(sid)
            if ws is None:
                ws = row['node_weight_source'] or 'derived'
            subjects.append({'subject_id': sid, 'weight_source': ws})

        return self._build_source_distribution(subjects)

    def get_study_efficiency_trends(
        self,
        exam_context_id: int,
        weeks: int = 8
    ) -> Dict[str, Any]:
        """
        Get efficiency score trends over time.

        Args:
            exam_context_id: Exam context ID
            weeks: Number of weeks to analyze

        Returns:
            Efficiency trends data
        """
        current_analysis = self.get_subject_exam_weight_analysis(exam_context_id)

        return {
            'weekly_scores': [],
            'current_score': current_analysis['efficiency_score'],
            'previous_score': 0,
            'change': 0,
            'trend': 'stable'
        }
