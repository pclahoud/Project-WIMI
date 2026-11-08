"""WIMI advanced analytics operations."""

import json
import math
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta
from app_logging import ErrorCategory


# ---------------------------------------------------------------------------
# Weight provenance and the efficiency score (settled in #133)
#
# ``weight_source`` describes the **measuring stick**, never the student.
# It does NOT appear in the efficiency score's arithmetic, in either
# direction. Stage 9 shipped a ``_WEIGHT_SOURCE_CONFIDENCE`` table that
# multiplied the *penalty*, so a weight WIMI could not vouch for produced
# a smaller penalty and therefore a **higher** score — the docstrings
# called that "pessimistic". It was deleted in #133 along with the
# companion ``range_confidence`` term, which had the identical direction
# problem. Do not reintroduce either; see the ``CLAUDE.md`` section
# "Weight confidence is not part of the efficiency score (settled in
# #133)" before touching ``_calculate_efficiency_score``.
#
# Provenance is still surfaced — it is simply *shown* rather than folded
# into a point estimate: the per-row markers, the "Weight Sources"
# breakdown card (``_build_source_distribution``) and, when the student
# turns it on, the uncertainty band (``_build_efficiency_band``).
# ---------------------------------------------------------------------------

#: Sources whose weights came from a published exam blueprint. Everything
#: else was typed, anchored or computed by somebody, and is what the
#: uncertainty band widens on.
_VERIFIED_WEIGHT_SOURCES = frozenset({'official'})


# ---------------------------------------------------------------------------
# Difficulty and time spent (#898, owner 2026-11-07)
#
# ``docs/planning/DIFFICULTY_TIME_CARD_PLAN.md`` is the spec. Rated 4-5 is
# hard, 1-2 easy, and 3 is a middle band in no quadrant. Fast and slow split
# at the median time of every timed mistake on the exam, and only once there
# are ``DT_MIN_TIMED`` of them.
# ---------------------------------------------------------------------------

DT_HARD = (4, 5)
DT_EASY = (1, 2)
DT_MIDDLE = 3
DT_MIN_TIMED = 10
DT_TOP_TYPES = 3

_DT_QUADRANTS = ('hard_fast', 'hard_slow', 'easy_fast', 'easy_slow')


def _dt_is_timed(t: Any) -> bool:
    """Timed means more than 0 seconds. A 0 can be stored and reads blank."""
    return (isinstance(t, (int, float)) and not isinstance(t, bool)
            and t > 0)


def _dt_is_rated(d: Any) -> bool:
    """Rated means an integer 1-5. Anything else is treated as no rating."""
    return isinstance(d, int) and not isinstance(d, bool) and 1 <= d <= 5


def _dt_median(sorted_times: List[Any]) -> Any:
    """Odd n: the middle value. Even n: the mean of the two middle values,
    so a half second is possible. An integral result is returned as an int."""
    n = len(sorted_times)
    mid = n // 2
    if n % 2:
        value = sorted_times[mid]
    else:
        value = (sorted_times[mid - 1] + sorted_times[mid]) / 2
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _dt_bucket(d: Any, t: Any, median: Any) -> str:
    """The one bucket an entry belongs to.

    ``median`` is None while there are too few timed mistakes to split, and
    then every rated 1/2/4/5 timed entry is ``unsplit``. Fast is ``t <
    median``, so the median entry itself is slow.
    """
    if not _dt_is_rated(d) or not _dt_is_timed(t):
        return 'not_placed'
    if d == DT_MIDDLE:
        return 'middle'
    if median is None:
        return 'unsplit'
    speed = 'fast' if t < median else 'slow'
    return ('hard_' if d in DT_HARD else 'easy_') + speed


def _dt_chunks(ids: List[int], size: int = 500):
    """Keep ``IN (...)`` under SQLite's host-parameter limit."""
    for start in range(0, len(ids), size):
        yield ids[start:start + size]


def _dt_check_accounting(payload: Dict[str, Any]) -> None:
    """Every mistake is in exactly one bucket, so none is dropped.

    quadrants (or unsplit) + middle + not placed = total, and the per-entry
    list agrees. Raised rather than ``assert``-ed so an optimised build still
    checks it.
    """
    buckets = payload['buckets']
    if payload['median']['available']:
        placed_in_split = sum(buckets[name]['count'] for name in _DT_QUADRANTS)
    else:
        placed_in_split = payload['unsplit']['count']
    summed = (placed_in_split + buckets['middle']['count']
              + buckets['not_placed']['count'])
    if summed != payload['total'] or len(payload['entries']) != payload['total']:
        raise AssertionError(
            f"difficulty/time accounting broken: buckets sum to {summed}, "
            f"{len(payload['entries'])} entries listed, total "
            f"{payload['total']}")


#: Every place the card can link from: the four quadrants, the two
#: fallback bands, and ``total`` for the card as a whole.
DT_LINK_BUCKETS = ('total',) + _DT_QUADRANTS + ('unsplit', 'middle',
                                                 'not_placed')


def _dt_link_number(value: Any) -> str:
    """A number as the URL carries it: ``94`` or ``94.5``, never ``94.0``.

    JavaScript's ``String()`` writes the same text for both, which is what
    keeps ``difficulty_time_links.js`` and this byte-identical.
    """
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def dt_entry_browser_params(payload: Dict[str, Any],
                            bucket: str) -> Dict[str, str]:
    """The entry browser URL parameters that land on one bucket of the card.

    A pure function of a :meth:`AdvancedAnalyticsMixin.get_difficulty_time_quadrants`
    payload (#898 Wave 1). The browser's total for these parameters equals
    the bucket's count -- its ``match.count`` when a type, several types or
    *No error type* is picked -- and
    ``tests/database/test_entry_browser_lands_on_the_card.py`` asserts that
    for every bucket and picker state on both scopes.

    **Wave 2 takes the JavaScript copy**, ``src/web/js/difficulty_time_links.js``
    (``WimiDifficultyTimeLinks.paramsFor`` / ``urlFor``), which is this
    function line for line; the regression scenario
    ``test_entry_browser_filters_by_difficulty_and_time.py`` compares the two
    on a real payload. Change both or neither.

    * The exam is always ``exam``. On the deep dive the scope adds
      ``counted_subject`` (and ``counted_parent``), the card's own counting
      population, never the browser's finding-rule ``subject``.
    * A quadrant is ``difficulty`` plus ``time_max`` (fast, exclusive) or
      ``time_min`` (slow, inclusive) at the median itself, not its rounded
      label, so the median entry lands on slow as the card puts it.
    * ``middle`` and ``unsplit`` need *timed* without a bound: ``time_min=0``
      is that, because either bound implies ``time_spent_seconds > 0``.
    * ``not_placed`` is ``missing=difficulty,time``: no rating OR no time.
    * The picker travels as ``tags`` (+ ``tag_mode=all`` when it matters)
      or ``untagged=1``.

    Raises:
        ValueError: an unknown bucket, or a quadrant while the card has no
            split.
    """
    if bucket not in DT_LINK_BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}")
    scope = payload['scope']
    params: Dict[str, str] = {'exam': str(scope['exam_context_id'])}
    if scope.get('subject_id') is not None:
        params['counted_subject'] = str(scope['subject_id'])
        if scope.get('primary_parent_id') is not None:
            params['counted_parent'] = str(scope['primary_parent_id'])

    if bucket in _DT_QUADRANTS:
        median = payload['median']
        if not median['available']:
            raise ValueError(f"{bucket} has no split to link to")
        levels = DT_HARD if bucket.startswith('hard_') else DT_EASY
        params['difficulty'] = ','.join(str(d) for d in levels)
        m = _dt_link_number(median['value_seconds'])
        if bucket.endswith('_fast'):
            params['time_max'] = m
        else:
            params['time_min'] = m
    elif bucket == 'unsplit':
        params['difficulty'] = ','.join(
            str(d) for d in sorted(DT_EASY + DT_HARD))
        params['time_min'] = '0'
    elif bucket == 'middle':
        params['difficulty'] = str(DT_MIDDLE)
        params['time_min'] = '0'
    elif bucket == 'not_placed':
        params['missing'] = 'difficulty,time'

    selection = payload.get('selection') or {}
    picked = selection.get('tag_ids') or []
    if selection.get('untagged'):
        params['untagged'] = '1'
    elif picked:
        params['tags'] = ','.join(str(t) for t in picked)
        if selection.get('match') == 'all' and len(picked) > 1:
            params['tag_mode'] = 'all'
    return params


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
                'path_omitted_ancestors': [str, ...],  # #301
                'dimension_id': int,     # #314, ABSENT when in no axis
                'dimension_name': str,   # #314, ABSENT when in no axis
                'notes': [{'note_id': int, 'entry_id': int,
                           'content_html': str, 'updated_at': str,
                           'attachment_count': int}, ...],  # #465, #848
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
                'mistake_types': [{'tag_name': str, 'color': str, 'description': str, 'count': int, 'percentage': float}, ...],
                'recent_entries': [{'entry_id': int, 'date_encountered': str, 'subject_name': str, 'reflection': str, 'explanation': str}, ...],
            }

        There is deliberately no ``sibling_subjects`` key. It fed the
        "Related Topics (Siblings)" panel, which issue #14 removed: the
        owner's "siblings" are *semantic relations* between topics
        (hypertension leads to hypertensive nephrosclerosis), and tree
        adjacency is at best a weak proxy for that — two topics can share
        a parent and have nothing to do with each other. The replacement
        feature is parked pending a design discussion about the authoring
        workflow; do not reinstate a structural query in the meantime.
        """
        from datetime import datetime, timedelta

        # Get subject basic info.
        #
        # No ``sn.parent_id``: the legacy single-parent column is not
        # read anywhere on this path any more (issue #14 removed its last
        # reader with the sibling panel). Keep it that way —
        # ``subject_edges`` is the canonical parent source per CLAUDE.md.
        subject_query = """
            SELECT
                sn.id,
                sn.name as subject_name,
                sn.level_type as level,
                (COALESCE(sn.exam_weight_low, 0) + COALESCE(sn.exam_weight_high, sn.exam_weight_low, 0)) / 2.0 as exam_weight,
                COALESCE(sn.exam_weight_low, 0) as exam_weight_low,
                COALESCE(sn.exam_weight_high, sn.exam_weight_low, 0) as exam_weight_high
            FROM subject_nodes sn
            WHERE sn.id = ?
        """
        subject = self.fetchone(subject_query, (subject_id,))

        if not subject:
            return None

        # WHICH AXIS THIS SUBJECT IS ON (#314, owner 2026-10-10). The page
        # heading was the bare subject name, so on a multi-dimensional exam
        # "18 to 65" could be a Patient Age group, a Site of Care value or a
        # topic -- and "Full path: 18 to 65" repeated it rather than
        # disambiguating, because a dimension root has nothing above it.
        #
        # Same shape as ``_base.py``'s ``_subject_with_dimension``, including
        # the two things that look optional and are not:
        #
        # - ``d.status = 'active'`` sits in the JOIN. Every read of
        #   ``exam_dimensions`` filters on status, partial adoption is worse
        #   than none, and ``test_dimension_soft_delete.py`` sweeps for it.
        # - the keys are **absent** rather than null when the subject is in no
        #   axis, so a reader can treat absence as "no axis" without comparing
        #   against None. That is this payload's existing convention for
        #   ``path_omitted_ancestors`` (#301).
        #
        # Guarded on the NAME rather than on ``dimension_id``: a node whose
        # dimension has been archived keeps its ``dimension_id`` and joins to
        # a NULL name, and emitting ``dimension_name: None`` would put the
        # word "in" in front of nothing on the page. #210's cascade means an
        # active subject should not be in that state, so this is cover rather
        # than a live path -- but it costs one predicate.
        dimension = self.fetchone("""
            SELECT sn.dimension_id, d.name AS dimension_name
            FROM subject_nodes sn
            LEFT JOIN exam_dimensions d
                   ON sn.dimension_id = d.id AND d.status = 'active'
            WHERE sn.id = ?
        """, (subject_id,))

        # Build full path
        full_path_info = self._build_subject_path_info(subject_id)
        full_path = full_path_info['path']

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

        # Get timeline (last 8 weeks) - aggregated from descendants.
        #
        # Bucket ``i`` is the half-open week ``[week_start - 7i, week_start - 7i + 7)``
        # so that ``i == 0`` ("This") is the *current* week — the same
        # ``[week_start, now]`` window the THIS WEEK card counts — and
        # ``i == 1`` is exactly the LAST WEEK card's window. Issue #5: an
        # earlier version anchored ``week_end`` at ``week_start`` and walked
        # backwards from there, which made "This" cover last week and left
        # the current week in no bucket at all, so every bar read 0 on a
        # database whose entries were all logged this week.
        timeline = []
        for i in range(7, -1, -1):
            week_begin = week_start - timedelta(days=i * 7)
            week_end = week_begin + timedelta(days=7)

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
        #
        # The LIST of direct children is sourced from ``subject_edges``, not
        # the legacy ``subject_nodes.parent_id`` column. The per-child counts
        # below were already polyhierarchy-aware, but the list they iterated
        # was not: a child attached to this subject only via ``subject_edges``
        # (e.g. added through ``addParent``) has a ``parent_id`` pointing
        # somewhere else — or NULL — so it was dropped from the breakdown
        # entirely. A silent omission, with nothing on the page signalling it.
        # m004 backfilled one edge per pre-existing ``parent_id``, and
        # ``create_subject_node`` dual-writes an edge, so the junction table is
        # a superset of the legacy column: nothing is lost by reading only it.
        child_query = """
            SELECT sn.id as subject_id, sn.name as subject_name
            FROM subject_nodes sn
            JOIN subject_edges se ON se.child_id = sn.id
            WHERE se.parent_id = ? AND sn.status = 'active'
            GROUP BY sn.id, sn.name
            ORDER BY MIN(se.display_order), sn.name
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
                t.description,
                COUNT(DISTINCT qe.id) as count
            FROM tags t
            JOIN entry_tags et ON t.id = et.tag_id
            JOIN question_entries qe ON et.question_entry_id = qe.id
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            WHERE {agg_where_clause} AND esm.mapping_type = 'primary'
            GROUP BY t.id, t.tag_name, t.color_hex, t.description
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

        # Stage 9 polish — orientation fields for the multi-parent
        # selector. Both are cheap to compute and let the page render a
        # dynamic breadcrumb + an explanatory banner that turns the
        # selector from "looks broken on leaves" into "tells the user
        # what view they're in and what data they're not seeing".
        via_parent = self._build_path_via_parent(
            subject_id, primary_parent_id
        ) if primary_parent_id is not None else None
        path_via_parent = via_parent['path'] if via_parent else None

        # #301: the archived ancestors the rendered breadcrumb no longer
        # names, for the hover tooltip. Keyed to the path the page will
        # ACTUALLY show -- `subject_deep_dive.js` prefers `path_via_parent`
        # over `full_path` -- so the page needs one key and no branch. Both
        # paths come from a status-filtered upward walk (`full_path` from
        # #301's, `path_via_parent` from #262's `get_paths_to_root`), so both
        # can be cut short and both are explained the same way: ask the
        # path's topmost node what was archived above it.
        if via_parent:
            path_omitted_ancestors = self._archived_ancestor_names(
                via_parent['node_ids'][0])
        else:
            path_omitted_ancestors = full_path_info['omitted_ancestors']

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

        payload: Dict[str, Any] = {
            'subject_id': subject_id,
            'subject_name': subject['subject_name'],
            'full_path': full_path,
            'path_via_parent': path_via_parent,
            # #301. One rule across every payload carrying this: the names
            # when the path was shortened, `null`/absent otherwise, NEVER an
            # empty list. The tooltip must appear only where something was
            # actually removed, so making "nothing to say" indistinguishable
            # from "something to say, but it is empty" is the one shape to
            # avoid.
            'path_omitted_ancestors': path_omitted_ancestors or None,
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
        }

        # Absent, not null, when the subject is in no axis -- see the query.
        if dimension and dimension['dimension_name']:
            payload['dimension_id'] = dimension['dimension_id']
            payload['dimension_name'] = dimension['dimension_name']

        # NOTES TAGGED WITH THIS SUBJECT (#465, owner 2026-10-10). This
        # payload carried no notes key at all, and the page's belief that it
        # did came from one class name: the Recent Entries row's third line
        # is classed `recent-entry-note` and falls back to the literal string
        # "No notes", while rendering the entry's reflection. A class name and
        # a fallback string were enough to convince README.md, a briefing, and
        # very nearly a published manual chapter.
        #
        # THE SET IS THE STRICT ONE: notes whose own `linked_subject_ids`
        # names this subject, NOT every note hanging off an entry tagged here,
        # and NOT inherited from descendants. That is the owner's choice of
        # three, and it is deliberately the OPPOSITE rule from the entries on
        # this same page -- `get_subject_deep_dive`'s agg WHERE is the most
        # permissive reading in the app, by design (§5.4 divergence, see this
        # method's own notes). A note is filed by hand at one subject; an
        # entry's rollup is derived. Do not "make them consistent".
        #
        # `get_notes_by_subjects` already implements exactly this, through
        # `json_each(linked_subject_ids)`, and had no caller anywhere. It is
        # reused rather than re-queried so the deep dive and the entry form's
        # "+ Add existing" picker cannot drift apart.
        #
        # `entry_id` is ABSENT, not null, for a note on no entry (#848, m036:
        # a note freed when its origin was deleted, or detached from it).
        # Same convention as `dimension_id` on this payload (#314) and the
        # serializer's `question_entry_id`: the page tests `'entry_id' in
        # note` rather than comparing against null. A row with an origin opens
        # the entry; a row without one opens the Quick note dialog on the note
        # (#848 Wave 2b).
        #
        # `attachment_count` is how many entries hold the note through the
        # m009 junction, computed by `get_notes_by_subjects` exactly as
        # `list_free_notes` computes it (`_notes_with_attachment_count`). The
        # row reads it to say "and 1 other" beside "Entry #N", so a note
        # shared with other entries does not read as belonging to one.
        notes = []
        for n in self.get_notes_by_subjects([subject_id], limit=20):
            note = {
                'note_id': n.id,
                'content_html': n.content_html,
                'updated_at': n.updated_at,
                'attachment_count': int(getattr(n, 'attachment_count', 0) or 0),
            }
            if n.question_entry_id is not None:
                note['entry_id'] = n.question_entry_id
            notes.append(note)
        payload['notes'] = notes

        return payload

    def _build_path_via_parent(
        self, subject_id: int, primary_parent_id: int
    ) -> Optional[Dict[str, Any]]:
        """Return the breadcrumb path from root → primary_parent_id →
        ... → subject_id as ``{'path': 'A > B > ... > Subject',
        'node_ids': [...]}``.

        Picks the first path returned by :meth:`EdgesMixin.get_paths_to_root`
        that includes ``primary_parent_id`` (paths are primary-first, then
        deterministic). Returns ``None`` when no such path exists (the
        caller asked for a context that isn't actually an ancestor — the
        page should fall back to ``full_path``).

        ``node_ids`` travels because #301's tooltip needs the **id** of the
        path's topmost node to ask what was archived above it. Recovering
        that from the rendered string by name would be a lookup against a
        column that is not unique — ``subject_nodes.name`` is unique only
        per exam and dimension and only over active rows — so two exams
        sharing a subject name would make the tooltip report the wrong
        exam's archived parent.
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
        return {
            'path': ' > '.join(
                names.get(nid, f'#{nid}') for nid in candidate),
            'node_ids': list(candidate),
        }

    # =============================================================================
    # DIFFICULTY AND TIME SPENT (#898)
    # =============================================================================

    def _deep_dive_counted_entries_sql(
        self, subject_id: int, primary_parent_id: Optional[int] = None
    ) -> 'tuple[str, list]':
        """The entries behind :meth:`get_subject_deep_dive`'s ``total_mistakes``.

        Returns ``(sql, params)`` for a statement selecting ``qe.id`` and
        ``rs.exam_context_id``, ending in a WHERE clause the caller may extend
        with ``AND ...``. It already carries ``rs.user_id = ?`` and
        ``esm.mapping_type = 'primary'``.

        **A copy, not a refactor (#898).** ``get_subject_deep_dive`` builds the
        same scope inline: the permissive subtree reading with no parent
        context, the lenient parent-context reading with one, and
        primary-only because that page *totals* mistakes (#13). The page is
        deliberately not rewritten onto this helper; instead
        ``test_difficulty_time_quadrants.py``'s parity tests compare this
        population with the page's own ``total_mistakes``, with and without
        a parent context. If the page's scope changes, change this with it,
        or those tests fail.
        """
        descend = """
                    SELECT id FROM subject_nodes WHERE id = ? AND status = 'active'
                    UNION
                    SELECT sn.id FROM subject_nodes sn
                    JOIN subject_edges se ON se.child_id = sn.id
                    JOIN {name} d ON se.parent_id = d.id
                    WHERE sn.status = 'active'
        """
        if primary_parent_id is None:
            cte = ("WITH RECURSIVE descendants AS ("
                   + descend.format(name='descendants') + ")")
            params: list = [subject_id]
            scope = (
                "(esm.subject_node_id IN (SELECT id FROM descendants) "
                "OR (esm.primary_parent_id IS NOT NULL "
                "AND esm.primary_parent_id IN (SELECT id FROM descendants)))"
            )
        else:
            cte = ("WITH RECURSIVE descendants AS ("
                   + descend.format(name='descendants') + "), "
                   "parent_context_descendants AS ("
                   + descend.format(name='parent_context_descendants') + ")")
            params = [subject_id, primary_parent_id]
            scope = (
                "("
                "(esm.primary_parent_id IS NULL "
                "AND esm.subject_node_id IN (SELECT id FROM descendants))"
                " OR "
                "(esm.primary_parent_id IS NOT NULL "
                "AND esm.primary_parent_id IN "
                "(SELECT id FROM parent_context_descendants))"
                ")"
            )
        sql = f"""
            {cte}
            SELECT DISTINCT qe.id AS id, rs.exam_context_id AS exam_context_id
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            WHERE rs.user_id = ? AND {scope} AND esm.mapping_type = 'primary'
        """
        params.append(self.user_id)
        return sql, params

    def get_difficulty_time_quadrants(
        self,
        exam_context_id: int,
        subject_id: Optional[int] = None,
        primary_parent_id: Optional[int] = None,
        tag_ids: Optional[List[int]] = None,
        untagged: bool = False,
        match: str = 'any',
    ) -> Dict[str, Any]:
        """Every mistake in scope, placed by its rating and its time spent.

        The rules are ``docs/planning/DIFFICULTY_TIME_CARD_PLAN.md``'s *Data
        rules*, decided on #898:

        * **Scope.** No ``subject_id``: every mistake in the exam's sessions
          for this user, drafts included (#12), no dimension filter. With
          one: exactly the population behind ``get_subject_deep_dive``'s
          ``total_mistakes`` (see :meth:`_deep_dive_counted_entries_sql`).
        * **Timed** means ``time_spent_seconds > 0``: a 0 can be stored and is
          shown blank everywhere. **Rated** means an integer 1-5.
        * **The median** is over every timed mistake of the *exam*, whatever
          the rating, the subject or the picker, so *fast* means the same on
          both pages. Fast is ``t < m``, slow ``t >= m``, so the median
          entry is slow. Under ``DT_MIN_TIMED`` timed mistakes there is no
          split: the four quadrants are ``None`` and ``unsplit`` holds the
          rated 1/2/4/5 timed mistakes instead.
        * **Buckets** are exclusive and exhaustive: the four quadrants (or
          ``unsplit``), ``middle`` (rated 3 and timed) and ``not_placed`` (no
          rating, or not timed). ``placed`` counts the quadrants (or
          ``unsplit``) only, so it is the mockup's "92 of 133 placed" and the
          denominator of each quadrant's share; the middle band is neither
          placed nor not placed. The
          sum is checked before returning; a mistake that falls through is
          an ``AssertionError``, never a quietly smaller card.
        * **Error types** count distinct entries per type per bucket, so they
          overlap. ``match='any'`` matches an entry carrying one of
          ``tag_ids``, ``'all'`` one carrying every one, and ``untagged``
          one carrying none (exclusive with ``tag_ids``). The ``types`` list
          is every type carried by a mistake in scope, flagged
          ``listed_on_exam``: removing a type from the exam's list decides
          only what can be added to an entry (#888), so it still counts.

        Raises:
            ValidationError: no such exam, ``untagged`` with ``tag_ids``,
                ``match`` other than ``'any'``/``'all'``, a parent context
                with no subject, no such subject, or a ``tag_ids`` value that
                is not an integer id.
        """
        from ..exceptions import ValidationError

        # ---------------------------------------------------- arguments
        if match not in ('any', 'all'):
            raise ValidationError(
                f"match must be 'any' or 'all', not {match!r}")
        picked: List[int] = []
        for tag_id in (tag_ids or []):
            if isinstance(tag_id, bool) or not isinstance(tag_id, int):
                raise ValidationError(
                    f"tag_ids must be integer error-type ids, not {tag_id!r}")
            if tag_id not in picked:
                picked.append(tag_id)
        untagged = bool(untagged)
        if untagged and picked:
            raise ValidationError(
                "No error type cannot be combined with picked error types")
        if primary_parent_id is not None and subject_id is None:
            raise ValidationError(
                "a parent context needs a subject")
        if not exam_context_id or not self.fetchone(
                "SELECT id FROM exam_contexts WHERE id = ?",
                (exam_context_id,)):
            raise ValidationError(
                f"no exam with id {exam_context_id!r}")
        if subject_id is not None and not self.fetchone(
                "SELECT id FROM subject_nodes WHERE id = ?", (subject_id,)):
            raise ValidationError(f"no subject with id {subject_id!r}")

        # ---------------------------------------------- the exam's mistakes
        # Read once: the median needs every one of them, whatever the scope.
        rows = self.fetchall("""
            SELECT qe.id, qe.perceived_difficulty AS d,
                   qe.time_spent_seconds AS t, qe.is_draft,
                   qe.question_id, rs.session_name
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ? AND rs.exam_context_id = ?
            ORDER BY qe.id
        """, (self.user_id, exam_context_id))

        timed_times = sorted(
            r['t'] for r in rows if _dt_is_timed(r['t']))
        timed_count = len(timed_times)
        available = timed_count >= DT_MIN_TIMED
        median_value = _dt_median(timed_times) if available else None
        all_equal = timed_count > 0 and timed_times[0] == timed_times[-1]

        # ---------------------------------------------------------- scope
        if subject_id is None:
            in_scope = [r for r in rows]
            counting = 'every_mistake'
        else:
            sql, params = self._deep_dive_counted_entries_sql(
                subject_id, primary_parent_id)
            sql += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)
            counted = {r['id'] for r in self.fetchall(sql, tuple(params))}
            in_scope = [r for r in rows if r['id'] in counted]
            counting = 'primary_subject_subtree'
        scope_ids = [r['id'] for r in in_scope]

        # ------------------------------------------- types and subjects
        tags_by_entry: Dict[int, List[int]] = {i: [] for i in scope_ids}
        type_info: Dict[int, Dict[str, Any]] = {}
        subjects_by_entry: Dict[int, List[Dict[str, Any]]] = {
            i: [] for i in scope_ids}
        for chunk in _dt_chunks(scope_ids):
            marks = ','.join('?' * len(chunk))
            for row in self.fetchall(f"""
                SELECT et.question_entry_id AS entry_id, t.id AS tag_id,
                       t.tag_name, t.description, t.parent_id AS group_id,
                       g.tag_name AS group_name,
                       EXISTS (SELECT 1 FROM exam_error_types x
                               WHERE x.exam_context_id = ?
                                 AND x.tag_id = t.id) AS listed
                FROM entry_tags et
                JOIN tags t ON t.id = et.tag_id
                LEFT JOIN tags g ON g.id = t.parent_id
                WHERE et.question_entry_id IN ({marks})
                  AND IFNULL(t.is_group, 0) = 0
            """, (exam_context_id, *chunk)):
                carried = tags_by_entry[row['entry_id']]
                if row['tag_id'] not in carried:
                    carried.append(row['tag_id'])
                type_info.setdefault(row['tag_id'], {
                    'tag_id': row['tag_id'],
                    'name': row['tag_name'],
                    'description': row['description'],
                    'group_id': row['group_id'],
                    'group_name': row['group_name'],
                    'listed_on_exam': bool(row['listed']),
                })
            for row in self.fetchall(f"""
                SELECT esm.question_entry_id AS entry_id, sn.id, sn.name
                FROM entry_subject_mappings esm
                JOIN subject_nodes sn ON sn.id = esm.subject_node_id
                WHERE esm.question_entry_id IN ({marks})
                  AND esm.mapping_type = 'primary'
                ORDER BY sn.name, sn.id
            """, tuple(chunk)):
                subjects_by_entry[row['entry_id']].append(
                    {'id': row['id'], 'name': row['name']})

        # -------------------------------------------------- per entry
        selecting = bool(picked) or untagged
        entries: List[Dict[str, Any]] = []
        for r in in_scope:
            carried = tags_by_entry[r['id']]
            hits = [t for t in picked if t in carried]
            if untagged:
                matches: Optional[bool] = not carried
            elif picked:
                matches = (bool(hits) if match == 'any'
                           else len(hits) == len(picked))
            else:
                matches = None
            entries.append({
                'id': r['id'],
                'd': r['d'],
                't': r['t'],
                'bucket': _dt_bucket(r['d'], r['t'], median_value),
                'is_draft': bool(r['is_draft']),
                'session_name': r['session_name'],
                'question_id': r['question_id'],
                'subjects': subjects_by_entry[r['id']],
                'tag_ids': sorted(carried),
                'matches': matches,
                'picked_hits': hits,
            })

        # -------------------------------------------------- per bucket
        def summarise(name: str) -> Dict[str, Any]:
            members = [e for e in entries if e['bucket'] == name]
            type_counts: Dict[int, int] = {}
            for e in members:
                for t in e['tag_ids']:
                    type_counts[t] = type_counts.get(t, 0) + 1
            ranked = sorted(
                type_counts.items(),
                key=lambda kv: (-kv[1], type_info[kv[0]]['name'], kv[0]))
            summary: Dict[str, Any] = {
                'count': len(members),
                'untagged': sum(1 for e in members if not e['tag_ids']),
                'top_types': [
                    {'tag_id': t, 'name': type_info[t]['name'], 'count': n}
                    for t, n in ranked[:DT_TOP_TYPES]],
                'more_types': max(0, len(ranked) - DT_TOP_TYPES),
                'match': None,
            }
            if selecting:
                summary['match'] = {
                    'count': sum(1 for e in members if e['matches']),
                    'per_type': [
                        {'tag_id': t,
                         'count': sum(1 for e in members
                                      if t in e['picked_hits'])}
                        for t in picked],
                }
            return summary

        buckets: Dict[str, Any] = {}
        for name in _DT_QUADRANTS:
            buckets[name] = summarise(name) if available else None
        buckets['middle'] = summarise('middle')
        buckets['not_placed'] = summarise('not_placed')
        unsplit = None if available else summarise('unsplit')

        not_placed_detail = {'no_rating_no_time': 0, 'no_rating_only': 0,
                             'no_time_only': 0}
        for e in entries:
            if e['bucket'] != 'not_placed':
                continue
            rated, timed = _dt_is_rated(e['d']), _dt_is_timed(e['t'])
            if not rated and not timed:
                not_placed_detail['no_rating_no_time'] += 1
            elif not rated:
                not_placed_detail['no_rating_only'] += 1
            else:
                not_placed_detail['no_time_only'] += 1

        # ---------------------------------------------------------- types
        type_totals: Dict[int, int] = {}
        for e in entries:
            for t in e['tag_ids']:
                type_totals[t] = type_totals.get(t, 0) + 1
        types = sorted(
            ({**type_info[t], 'count': n} for t, n in type_totals.items()),
            key=lambda ty: (-ty['count'], ty['name'], ty['tag_id']))

        # ----------------------------------------------------------- axis
        drawn = sorted(e['t'] for e in entries if e['bucket'] != 'not_placed')
        if drawn:
            p95 = drawn[math.ceil(0.95 * len(drawn)) - 1]
            x_max = max(60, math.ceil(p95 / 60) * 60)
            clipped = sum(1 for t in drawn if t > x_max)
        else:
            x_max, clipped = None, 0

        total = len(entries)
        payload = {
            'scope': {
                'exam_context_id': exam_context_id,
                'subject_id': subject_id,
                'primary_parent_id': primary_parent_id,
                'counting': counting,
            },
            'total': total,
            'placed': (sum(buckets[name]['count'] for name in _DT_QUADRANTS)
                       if available else unsplit['count']),
            'unsplit': unsplit,
            'median': {
                'population': 'exam_timed_mistakes',
                'timed_count': timed_count,
                'value_seconds': median_value,
                'label_seconds': (math.ceil(median_value)
                                  if median_value is not None else None),
                'available': available,
                'min_timed': DT_MIN_TIMED,
                'all_equal': all_equal,
            },
            'buckets': buckets,
            'not_placed_detail': not_placed_detail,
            'selection': {
                'tag_ids': picked,
                'untagged': untagged,
                'match': match,
            },
            'types': types,
            'untagged_count': sum(1 for e in entries if not e['tag_ids']),
            'entries': entries,
            'axis': {'x_max_seconds': x_max, 'clipped_count': clipped},
        }
        _dt_check_accounting(payload)
        return payload

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
                'streak_at_risk': False,
                'total_active_days': 45,
                'week_start': 'sunday'
            }
        """
        from datetime import timedelta

        today = datetime.now().date()

        # Start on the Sunday `weeks - 1` weeks before this week's Sunday, so
        # the window is `weeks` columns ending today. It MUST be a Sunday:
        # heatmap_chart.js puts day i in row i % 7 and labels rows 1/3/5
        # Mon/Wed/Fri. The old `days=6` here made it a Monday, and every
        # label sat one row off (#529).
        days_since_sunday = (today.weekday() + 1) % 7
        this_sunday = today - timedelta(days=days_since_sunday)
        start_date = this_sunday - timedelta(weeks=weeks - 1)

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
            # Forwarded, not recomputed (#478): the dashboard's Current
            # Streak card is the only consumer of this payload that draws
            # the warning, and it used to hardcode the flag to False.
            'streak_at_risk': streak_info['streak_at_risk'],
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

        THE one definition of a study day in WIMI (owner's decision on #531,
        2026-10-07): **a day with at least one entry**. A review session
        started with nothing logged does not count. A streak is consecutive
        such days, as the student's local calendar days (#286). Every streak
        surface reads this -- the analytics streak card (through the heatmap
        payload), ``get_streak_info`` (Quick Analytics' STREAK stat) and
        ``get_study_streak`` (Patterns & Insights, the plugin API, the MCP
        tool). Do not give any of them its own query.
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
                'streak_at_risk': False,
                'days_since_last_active': None
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
                'streak_at_risk': False,
                'days_since_last_active': None
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
            'streak_at_risk': streak_at_risk,
            # Same clock as everything above, so get_study_streak never
            # reads a second `now()` across midnight.
            'days_since_last_active': (today - last_active).days
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
                AND DATE(qe.created_at) >= ?
        """
        # No ``is_draft`` predicate: drafts count here, per the owner's
        # decision on issue #12. A draft exists because a question was
        # answered wrong, and which source it came from is known the
        # moment the entry is started -- the unfinished reflection does
        # not make the source any less responsible for the mistake.
        # Pinned by ``tests/database/test_draft_policy_by_surface.py``.
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

        Drafts count (issue #12) — the same policy as
        :meth:`get_source_comparison`, which this feeds. Leaving the
        filter here would have let a source's headline subject disagree
        with its own entry count on the same card.
        """
        query = """
            SELECT sn.name, COUNT(*) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            JOIN subject_nodes sn ON esm.subject_node_id = sn.id
            WHERE rs.user_id = ?
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
                AND DATE(qe.created_at) >= ?
        """
        # No ``is_draft`` predicate (issue #12). This is an activity
        # trend: a week spent logging drafts is a week the student
        # studied, and showing it as a flat line was the single most
        # discouraging way to be wrong about it.
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
        exam_context_id: int,
        dimension_id: Optional[int] = None,
        level_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compare mistake distribution against exam weight distribution.

        This analysis helps identify if study time is aligned with exam priorities.

        Args:
            exam_context_id: Exam context ID (required)
            dimension_id: List only this dimension's subjects (#820). The
                dimensions overlap -- each covers the whole exam -- so the
                unfiltered list mixes several partitions of one item pool.
            level_type: List only subjects stored at this level (#820), read
                from ``level_type`` and never from depth (#49).

        Neither filter changes the counting: a subject's mistakes still
        include everything beneath it (#468) and are still shared out of
        every entry in the exam. They only choose which rows are listed.

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
                'efficiency_band': {
                    'low': float, 'high': float, 'half_width': float,
                    'unverified_weight_pct': float,
                    'unverified_share': float,
                },
                'total_mistakes': int,
                'weighted_subjects': int,
                'weight_source_distribution': {...}
            }

        ``efficiency_band`` is always present (#133). The student's
        ``efficiency_show_confidence_band`` preference decides whether the
        dashboard *renders* it; the score itself is the same number either
        way, because provenance is not part of its arithmetic.
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
            -- mapping_type belongs in the JOIN, not the WHERE: a
            -- weighted subject with no entries must still produce a row.
            --
            -- Filtering to 'primary' aligns this surface with Top
            -- Subjects and the sunburst, which both do. Without it the
            -- quadrant counted secondary "also tested" tags as full
            -- mistakes, so one question became a mistake in two
            -- subjects -- the same data reading differently depending on
            -- which chart you looked at, with the inflated
            -- total_mistakes feeding mistake_pct and the efficiency
            -- score.
            LEFT JOIN entry_subject_mappings esm
                ON sn.id = esm.subject_node_id
                AND esm.mapping_type = 'primary'
            LEFT JOIN question_entries qe ON esm.question_entry_id = qe.id
            LEFT JOIN review_sessions rs ON qe.review_session_id = rs.id
            -- No ``is_draft`` predicate (issue #12). Note where the old
            -- one sat: in the WHERE, after a LEFT JOIN. A subject whose
            -- only entries were drafts did not come back with a zero --
            -- the row was dropped from the quadrant altogether, so the
            -- student's least-finished topics were the ones the chart
            -- could not see.
            -- A RECORDED weight, including 0% (#468, owner's decision
            -- 2026-10-07). This read `COALESCE(exam_weight_low, 0) > 0`,
            -- which excluded unweighted subjects as intended and ALSO a
            -- subject published at 0%, which #64 says is real data (Step 2
            -- CK publishes tasks at 0%). NULL on both bounds is the only
            -- "no weight".
            WHERE sn.exam_context = ?
                AND sn.status = 'active'
                AND (sn.exam_weight_low IS NOT NULL
                     OR sn.exam_weight_high IS NOT NULL)
                AND (rs.user_id = ? OR qe.id IS NULL)
                {scope}
            GROUP BY sn.id, sn.name, sn.exam_weight_low, sn.exam_weight_high, sn.weight_source
            ORDER BY exam_weight DESC
        """

        scope, params = '', [exam_name, self.user_id]
        if dimension_id is not None:
            scope += ' AND sn.dimension_id = ?'
            params.append(dimension_id)
        if level_type:
            scope += ' AND sn.level_type = ?'
            params.append(level_type)
        results = self.fetchall(query.replace('{scope}', scope), tuple(params))

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
                # #133: keep the band key present in the empty state for
                # the same reason the distribution is — the renderer
                # should not have to null-check a whole branch.
                'efficiency_band': {
                    'low': 0.0,
                    'high': 0.0,
                    'half_width': 0.0,
                    'unverified_weight_pct': 0.0,
                    'unverified_share': 0.0,
                },
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

        # Roll mistakes UP, and share them out of the WHOLE exam (#468,
        # owner's decision 2026-10-07).
        #
        # The query above counts entries tagged on each subject itself. A
        # weighted parent whose entries all sat on its topics therefore read
        # 0% and was filed as well-maintained -- "maintain current study
        # level" about the branch carrying the most mistakes -- while the
        # sunburst and Top Subject on the same page drew it as the largest.
        # #64 makes a weight a share of the whole exam AT ANY DEPTH, so a
        # parent's 20-25% includes its children and its mistakes must too.
        #
        # Same mechanism as Top Subject (get_subject_analytics), not a second
        # rollup: _aggregate_hierarchy_counts over subject_edges with the
        # §5.4 context buckets, so an entry pinned to one parent reaches that
        # parent only. Rows OVERLAP and no longer sum to 100% -- the
        # non-additivity #6 settled for the sunburst arcs, and true here for
        # the same reason. Do not "fix" it by dividing by the sum of rows.
        #
        # The denominator is every entry in the exam (the Total Entries
        # card's figure), not the sum over the weighted rows that survived
        # the WHERE: that made the left-hand percentage a share of SOME
        # mistakes while the right-hand one was a share of the whole exam.
        rolled = self._quadrant_rollup(exam_name, exam_context_id)
        total_mistakes = rolled['total_entries']
        min_mistakes = self.get_exam_analytics_config(exam_context_id).get(
            'min_mistakes_to_flag', self.MIN_MISTAKES_TO_FLAG_DEFAULT)

        # Calculate mistake percentages
        subjects = []
        for row in results:
            direct_count = row['mistake_count']
            row = {**row, 'mistake_count': rolled['totals'].get(
                row['subject_id'], direct_count)}
            mistake_pct = (row['mistake_count'] / total_mistakes * 100) if total_mistakes > 0 else 0
            weight_pct = row['exam_weight']  # This is now the midpoint
            weight_low = row['exam_weight_low']
            weight_high = row['exam_weight_high']
            difference = mistake_pct - weight_pct

            # Determine quadrant using range-aware categorization
            quadrant = self._categorize_subject_quadrant(
                mistake_pct, weight_low, weight_high,
                mistake_count=row['mistake_count'], min_mistakes=min_mistakes)

            # Stage 9: pick the dominant edge's weight_source. Falls
            # back to the legacy node-level value when the node has no
            # incoming edges (System-level nodes always do) or all
            # edges have weight_source=NULL (pre-Stage-2 legacy data).
            #
            # The final ``or 'derived'`` is a *display bucket* for a row
            # with no recorded provenance at all, nothing more. It used
            # to be described as a pessimistic default and was in fact
            # the third of #133's compounding errors: it kept
            # ``_WEIGHT_SOURCE_DEFAULT_CONFIDENCE`` from ever firing on
            # real data while quietly discounting the penalty. Now that
            # the score ignores provenance entirely, this only decides
            # which row of the "Weight Sources" card the subject lands
            # in, and 'derived' keeps the totals reconciling with
            # ``_build_source_distribution``.
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
                'direct_mistake_count': direct_count,
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
        # #133 — always computed, rendered only when the student asks.
        efficiency_band = self._build_efficiency_band(
            subjects, efficiency_score
        )

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
            'efficiency_band': efficiency_band,
            'total_mistakes': total_mistakes,
            'weighted_subjects': len(subjects),
            'weight_source_distribution': weight_source_distribution,
            'min_mistakes_to_flag': min_mistakes,
        }

    def _quadrant_rollup(self, exam_name: str, exam_context_id: int) -> Dict[str, Any]:
        """Each active subject's mistakes including its descendants (#468).

        Returns ``{'totals': {subject_id: count}, 'total_entries': int}``.
        ``totals`` comes from :meth:`_aggregate_hierarchy_counts` with the
        §5.4 buckets, exactly as Top Subject computes its own; every active
        subject of the exam is passed, so a parent with no entries of its own
        still receives its children's. ``total_entries`` is every entry in
        the exam for this user.
        """
        nodes = self.fetchall(
            "SELECT id FROM subject_nodes WHERE exam_context = ? AND status = 'active'",
            (exam_name,))
        bucket_rows = self.fetchall(
            """
            SELECT esm.subject_node_id AS sid,
                   esm.primary_parent_id AS ppid,
                   COUNT(DISTINCT qe.id) AS n
            FROM entry_subject_mappings esm
            JOIN question_entries qe ON qe.id = esm.question_entry_id
            JOIN review_sessions rs ON rs.id = qe.review_session_id
            JOIN subject_nodes sn ON sn.id = esm.subject_node_id
            WHERE sn.exam_context = ? AND sn.status = 'active'
              AND rs.user_id = ?
              AND esm.mapping_type = 'primary'
            GROUP BY esm.subject_node_id, esm.primary_parent_id
            """,
            (exam_name, self.user_id))
        buckets: Dict[int, Dict[Any, int]] = {}
        direct: Dict[int, int] = {}
        for b in bucket_rows:
            buckets.setdefault(b['sid'], {})[b['ppid']] = b['n']
        # A node's own figure is every entry tagged on it, however the
        # student pinned it -- counted distinct, not summed across buckets.
        for r in self.fetchall(
            """
            SELECT esm.subject_node_id AS sid, COUNT(DISTINCT qe.id) AS n
            FROM entry_subject_mappings esm
            JOIN question_entries qe ON qe.id = esm.question_entry_id
            JOIN review_sessions rs ON rs.id = qe.review_session_id
            JOIN subject_nodes sn ON sn.id = esm.subject_node_id
            WHERE sn.exam_context = ? AND sn.status = 'active'
              AND rs.user_id = ?
              AND esm.mapping_type = 'primary'
            GROUP BY esm.subject_node_id
            """,
                (exam_name, self.user_id)):
            direct[r['sid']] = r['n']
        totals = self._aggregate_hierarchy_counts(
            [{'id': n['id'], 'direct_count': direct.get(n['id'], 0)} for n in nodes],
            count_field='direct_count',
            context_buckets=buckets,
        )
        total = self.fetchone(
            """
            SELECT COUNT(DISTINCT qe.id) AS n
            FROM question_entries qe
            JOIN review_sessions rs ON rs.id = qe.review_session_id
            WHERE rs.exam_context_id = ? AND rs.user_id = ?
            """,
            (exam_context_id, self.user_id))['n'] or 0
        return {'totals': totals, 'total_entries': total}

    def _categorize_subject_quadrant(
        self,
        mistake_pct: float,
        weight_low: float,
        weight_high: float,
        mistake_count: Optional[int] = None,
        min_mistakes: int = 1,
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

        # Measured from the MIDDLE of the band (#827, owner's decision
        # 2026-10-14: "instead of the higher end of the range, make it the
        # median"). It was 1.3 x the top, so a 20-30% subject needed over 39%
        # of the mistakes before it was flagged. A share inside the band is
        # still never over-represented (the branch above), which with the
        # middle as reference matters only for wide bands: for 5-15% the cut
        # is 13%, and 13-15% stays unflagged because it is in the band.
        is_over_represented = mistake_pct > (midpoint * OVER_REPRESENTED_THRESHOLD)
        # And only on enough mistakes to be a pattern (#828, owner's decision
        # 2026-10-14, set per exam in Settings). Without it a 0% subject was
        # over-represented on its first mistake, since any share beats
        # 1.3 x 0. The count is the rolled-up one the row shows.
        if mistake_count is not None and mistake_count < min_mistakes:
            is_over_represented = False

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
        Calculate study efficiency score (0-100).

        Formula: ``100 - Σ(deviation × weight_factor)``

        **No confidence term, in either direction (settled in #133).**
        Two of them used to sit in this product — ``source_confidence``,
        keyed on ``weight_source``, and ``range_confidence``, keyed on how
        wide the published range is — and both multiplied a *penalty*, so
        a weight WIMI was less sure about produced a **smaller** penalty
        and a **higher** score. The ``min()`` of the two, written to make
        "the less certain signal dominate", systematically picked whichever
        factor inflated the score most.

        Both describe the measuring stick; the score is a statement about
        the student. Folding data quality into it yields a number meaning
        "your alignment, adjusted by how good our data is", which nobody
        can act on. Inverting the multiplier was considered and rejected:
        that lowers a student's score because their blueprint lacked
        provenance metadata, which blames a data problem on the person.

        Uncertainty is *shown* instead of priced in — the "Weight Sources"
        breakdown card, and the optional band from
        ``_build_efficiency_band`` when the student turns
        ``efficiency_show_confidence_band`` on. See the ``CLAUDE.md``
        section "Weight confidence is not part of the efficiency score
        (settled in #133)".

        Args:
            subjects: Rows carrying ``mistake_percentage`` and either
                ``exam_weight`` alone or the ``exam_weight_low`` /
                ``exam_weight_high`` pair. ``weight_source``, if present,
                is ignored here by design.

        Returns:
            A score in ``[0, 100]``; ``0`` for an empty list.
        """
        if not subjects:
            return 0

        total_penalty = 0
        for subject in subjects:
            total_penalty += self._subject_penalty(subject)

        score = max(0, 100 - total_penalty)
        return score

    @staticmethod
    def _subject_deviation(subject: Dict[str, Any]) -> float:
        """Distance between a subject's mistake share and its exam weight.

        Inside the published range, the deviation is measured from the
        midpoint; outside it, from the nearest bound. A range is a claim
        about where the truth lies, so landing anywhere inside it is not
        a miss.
        """
        mistake_pct = subject['mistake_percentage']
        weight_low = subject.get('exam_weight_low', subject['exam_weight'])
        weight_high = subject.get('exam_weight_high', subject['exam_weight'])
        midpoint = (weight_low + weight_high) / 2.0

        if weight_low <= mistake_pct <= weight_high:
            return abs(mistake_pct - midpoint)
        if mistake_pct < weight_low:
            return weight_low - mistake_pct
        return mistake_pct - weight_high

    @staticmethod
    def _subject_weight_factor(subject: Dict[str, Any]) -> float:
        """A subject's share of the exam, as a 0-1 multiplier."""
        weight_low = subject.get('exam_weight_low', subject['exam_weight'])
        weight_high = subject.get('exam_weight_high', subject['exam_weight'])
        return ((weight_low + weight_high) / 2.0) / 100

    def _subject_penalty(self, subject: Dict[str, Any]) -> float:
        """One subject's contribution to the efficiency penalty."""
        return (
            self._subject_deviation(subject)
            * self._subject_weight_factor(subject)
        )

    def _build_efficiency_band(
        self,
        subjects: List[Dict[str, Any]],
        score: float,
    ) -> Dict[str, Any]:
        """Uncertainty band around the efficiency score (#133).

        The score itself never moves — this is a *rendering* the student
        opts into with ``efficiency_show_confidence_band``, and the
        payload always carries it so "off" is a presentation choice
        rather than a degraded mode.

        The width comes from the weights, **not** from the deviations. A
        student perfectly aligned against fifteen weights somebody typed
        by hand has the least trustworthy 100 on offer, so a band that
        collapsed at perfect alignment would be telling the wrong story.
        Taking the honest worst case — an unverified weight could be off
        by as much as its own magnitude — and propagating it through
        ``penalty = deviation × midpoint/100`` gives

            half_width = Σ over unverified subjects of midpoint² / 100

        which is zero when every weight came from a blueprint, grows with
        the unverified share of the exam, and *narrows* as the blueprint
        gets more granular (fifteen 7% buckets say far more per bucket
        than three 33% ones). "Unverified" means any ``weight_source``
        outside ``_VERIFIED_WEIGHT_SOURCES`` — typed, anchored, derived
        or simply unrecorded.

        Returns:
            ``{'low', 'high', 'half_width', 'unverified_weight_pct',
            'unverified_share'}``. ``low``/``high`` are clamped to
            ``[0, 100]``; a subject list with no unverified weight yields
            a zero-width band sitting on the score.
        """
        total_mass = 0.0
        unverified_mass = 0.0
        half_width = 0.0
        for subject in subjects:
            midpoint = self._subject_weight_factor(subject) * 100
            total_mass += midpoint
            if subject.get('weight_source') in _VERIFIED_WEIGHT_SOURCES:
                continue
            unverified_mass += midpoint
            half_width += midpoint * midpoint / 100

        half_width = min(half_width, 100.0)
        return {
            'low': round(max(0.0, score - half_width), 1),
            'high': round(min(100.0, score + half_width), 1),
            'half_width': round(half_width, 1),
            'unverified_weight_pct': round(unverified_mass, 1),
            'unverified_share': (
                round(unverified_mass / total_mass, 3) if total_mass else 0.0
            ),
        }

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
