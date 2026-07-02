"""WIMI Subject hierarchy, weights, and question analysis operations."""

import json
import math
from typing import Optional, List, Dict, Any, Callable, Tuple
from datetime import date
from decimal import Decimal
from ..base_db import DatabaseIntegrityError
from ..exceptions import (
    ValidationError,
    SubjectNodeError,
    QuestionAnalysisError,
    AllocationFeasibilityError,
)
from ..models import UserPreferences, SubjectNode, QuestionAnalysis, QuestionTopicAssignment, Tag, QuestionTag
from app_logging import ErrorCategory


# Default half-life (days) for the recency decay applied to mistake
# weights in ``HierarchyMixin.compute_weakness_scores``. Surfaced as a
# module-level constant so it can be tuned without touching call sites
# (per Stage 1 §"Open questions" of
# ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``).
_HALF_LIFE_DAYS = 90


class HierarchyMixin:
    """Mixin for subject hierarchy, weight management, and question analysis operations."""

    def create_subject_node(
        self,
        exam_context: str,
        name: str,
        level_type: str,
        parent_id: Optional[int] = None,
        exam_weight_low: Optional[float] = None,
        exam_weight_high: Optional[float] = None,
        exam_source: Optional[str] = None,
        sort_order: int = 1,
        outline_type: str = 'content',
        dimension_id: Optional[int] = None
    ) -> SubjectNode:
        """
        Create a subject node in the hierarchy.

        Args:
            exam_context: Exam code (e.g., 'SAT', 'GRE')
            name: Node name
            level_type: Hierarchy level (e.g., 'Domain', 'Topic')
            parent_id: Parent node ID for hierarchy
            exam_weight_low: Lower bound of exam weight percentage
            exam_weight_high: Upper bound of exam weight percentage
            exam_source: Source document for weights
            sort_order: Display order
            outline_type: Type of outline ('content', 'competency', etc.)
            dimension_id: Dimension ID for multi-dimensional exams (NULL for simple exams)

        Returns:
            Created SubjectNode object
        """
        # Check for duplicates manually (since UNIQUE constraint doesn't work with NULL parent_id)
        if parent_id is None:
            existing = self.fetchone(
                "SELECT id FROM subject_nodes WHERE exam_context = ? AND name = ? AND parent_id IS NULL AND status = 'active'",
                (exam_context, name)
            )
        else:
            existing = self.fetchone(
                "SELECT id FROM subject_nodes WHERE exam_context = ? AND name = ? AND parent_id = ? AND status = 'active'",
                (exam_context, name, parent_id)
            )

        if existing:
            raise SubjectNodeError(
                f"Subject node already exists: {exam_context}/{name}"
            )

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO subject_nodes (
                        exam_context, name, parent_id, level_type, sort_order,
                        exam_weight_low, exam_weight_high, exam_source,
                        outline_type, dimension_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """, (
                    exam_context, name, parent_id, level_type, sort_order,
                    exam_weight_low, exam_weight_high, exam_source,
                    outline_type, dimension_id
                ))

                node_id = cursor.lastrowid

                # Polyhierarchy migration: also write a primary subject_edges
                # row so the new edge-based traversal helpers see this
                # parent-child relationship. Backward-compatible because
                # subject_nodes.parent_id is also still populated above; the
                # backfill in m004 created edges for all pre-migration rows.
                # Guard with a table-existence check so this is safe when
                # legacy DBs predate the migration.
                if parent_id is not None:
                    try:
                        self.execute(
                            """
                            INSERT OR IGNORE INTO subject_edges
                                (parent_id, child_id, is_primary, display_order)
                            VALUES (?, ?, TRUE, ?)
                            """,
                            (parent_id, node_id, sort_order or 0),
                        )
                    except Exception:
                        # subject_edges table may not exist on very old DBs;
                        # legacy parent_id traversal still works in that case.
                        pass

                if self.error_logger:
                    self.error_logger.debug(
                        f"Created subject node: {name} (ID: {node_id})",
                        category=ErrorCategory.DATABASE
                    )

                result_node = self.get_subject_node(node_id)

                # Graph dual-write
                full_path = self._build_subject_path(node_id)
                _exam_context = exam_context
                _parent_id = parent_id
                _dimension_id = dimension_id
                _node_id = node_id

                def _graph_write():
                    self._graph_execute(
                        "MERGE (s:Subject {sqlite_id: $id}) "
                        "SET s.name = $name, s.level_type = $level_type, s.full_path = $path",
                        {"id": _node_id, "name": name, "level_type": level_type, "path": full_path}
                    )
                    if _parent_id:
                        self._graph_execute(
                            "MATCH (p:Subject {sqlite_id: $pid}), (s:Subject {sqlite_id: $sid}) "
                            "MERGE (p)-[:HAS_CHILD]->(s)",
                            {"pid": _parent_id, "sid": _node_id}
                        )
                    else:
                        ec_row = self.fetchone(
                            "SELECT id FROM exam_contexts WHERE exam_name = ?",
                            (_exam_context,)
                        )
                        if ec_row:
                            self._graph_execute(
                                "MATCH (ec:ExamContext {sqlite_id: $ecid}), (s:Subject {sqlite_id: $sid}) "
                                "MERGE (ec)-[:ROOT_OF]->(s)",
                                {"ecid": ec_row['id'], "sid": _node_id}
                            )
                    if _dimension_id:
                        self._graph_execute(
                            "MATCH (s:Subject {sqlite_id: $sid}), (d:Dimension {sqlite_id: $did}) "
                            "MERGE (s)-[:BELONGS_TO]->(d)",
                            {"sid": _node_id, "did": _dimension_id}
                        )
                self._dual_write_graph("create_subject_node", _graph_write)

                return result_node

        except DatabaseIntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise SubjectNodeError(
                    f"Subject node already exists: {exam_context}/{name}"
                ) from e
            raise

    def get_subject_node(self, node_id: int) -> Optional[SubjectNode]:
        """Get subject node by ID.

        SQLite-primary (P2.5): graph lacks full SubjectNode fields (weights, etc.).
        """
        row = self.fetchone(
            "SELECT * FROM subject_nodes WHERE id = ? AND status = 'active'",
            (node_id,)
        )
        return SubjectNode.from_db_row(row) if row else None

    def get_subject_hierarchy(
        self,
        exam_context: str,
        parent_id: Optional[int] = None,
        include_weights: bool = True
    ) -> List[SubjectNode]:
        """
        Get subject hierarchy for an exam, walking ``subject_edges``.

        Polyhierarchy-aware: a node with multiple parent edges appears
        once under each parent. Non-primary appearances are flagged via
        ``SubjectNode.is_alias_appearance=True`` and do NOT recurse into
        their subtree (the canonical/primary appearance carries the
        children — duplicating subtrees under every alias parent would
        produce huge trees and isn't what the SNOMED-style renderer
        wants per ``docs/planning/POLYHIERARCHY_MIGRATION.md`` §7.1).

        A "root" is a node with no incoming ``subject_edges`` row. The
        legacy ``subject_nodes.parent_id`` column is intentionally
        ignored — the m004 migration backfilled an ``is_primary=TRUE``
        edge for every existing parent_id, so the edges table is the
        single source of truth post-migration.

        Args:
            exam_context: Exam code
            parent_id: Parent node id, or None for root nodes
            include_weights: Include weight information (currently
                always loaded; kept for API compatibility)

        Returns:
            List of SubjectNode objects
        """
        if parent_id is None:
            # Roots: nodes with no incoming edge.
            query = """
                SELECT sn.*, 0 AS _is_alias_appearance
                FROM subject_nodes sn
                WHERE sn.exam_context = ?
                  AND sn.status = 'active'
                  AND NOT EXISTS (
                      SELECT 1 FROM subject_edges se
                      WHERE se.child_id = sn.id
                  )
                ORDER BY sn.sort_order, sn.name
            """
            params: tuple = (exam_context,)
        else:
            # Children of `parent_id`: every edge from that parent,
            # including non-primary ones. Order by edge display_order
            # first so the renderer can lay out parents consistently.
            query = """
                SELECT
                    sn.*,
                    CASE WHEN se.is_primary THEN 0 ELSE 1 END AS _is_alias_appearance
                FROM subject_edges se
                JOIN subject_nodes sn ON sn.id = se.child_id
                WHERE se.parent_id = ?
                  AND sn.exam_context = ?
                  AND sn.status = 'active'
                ORDER BY se.display_order, sn.sort_order, sn.name
            """
            params = (parent_id, exam_context)

        rows = self.fetchall(query, params)
        nodes: List[SubjectNode] = []
        for row in rows:
            node = SubjectNode.from_db_row(row)
            node.is_alias_appearance = bool(row.get('_is_alias_appearance', 0))
            nodes.append(node)

        # Don't recurse under alias appearances — the primary appearance
        # carries the subtree, and showing the same descendants under
        # every non-primary parent would multiply the tree size.
        for node in nodes:
            if node.is_alias_appearance:
                node.children = []
            else:
                node.children = self.get_subject_hierarchy(
                    exam_context, node.id, include_weights
                )

        return nodes

    def update_subject_weights(
        self,
        node_id: int,
        exam_weight_low: float,
        exam_weight_high: float,
        exam_source: Optional[str] = None
    ) -> SubjectNode:
        """Update exam weights for a subject node"""
        with self.transaction():
            self.execute("""
                UPDATE subject_nodes
                SET exam_weight_low = ?,
                    exam_weight_high = ?,
                    exam_source = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (exam_weight_low, exam_weight_high, exam_source, node_id))

        return self.get_subject_node(node_id)

    # ==================== Question Analysis ====================

    def create_question_analysis(
        self,
        exam_context: str,
        question_source: str,
        question_source_id: str,
        answered_incorrectly_date: date,
        user_selected_answer: Optional[str] = None,
        correct_answer: Optional[str] = None,
        perceived_difficulty: Optional[int] = None,
        metacognitive_reflection: Optional[str] = None,
        mistake_category: Optional[str] = None,
        confidence_before_answer: Optional[int] = None,
        time_spent_on_question: Optional[int] = None,
        question_explanation: Optional[str] = None,
        user_notes: Optional[str] = None
    ) -> QuestionAnalysis:
        """
        Create a question analysis entry.

        Args:
            exam_context: Exam code
            question_source: Source of question (e.g., "Official SAT Practice Test 1")
            question_source_id: Unique ID within source (e.g., "Section3_Q15")
            answered_incorrectly_date: Date question was answered incorrectly
            user_selected_answer: Answer user selected
            correct_answer: Correct answer
            perceived_difficulty: User's difficulty rating (1-5)
            metacognitive_reflection: User's reflection on why they got it wrong
            mistake_category: Category of mistake
            confidence_before_answer: Confidence level before answering (1-5)
            time_spent_on_question: Time in seconds
            question_explanation: Explanation of correct answer
            user_notes: Additional user notes

        Returns:
            Created QuestionAnalysis object
        """
        # Validate inputs
        if mistake_category and mistake_category not in self.VALID_MISTAKE_CATEGORIES:
            raise ValidationError(f"Invalid mistake category: {mistake_category}")

        if perceived_difficulty and not (1 <= perceived_difficulty <= 5):
            raise ValidationError("Perceived difficulty must be between 1 and 5")

        if confidence_before_answer and not (1 <= confidence_before_answer <= 5):
            raise ValidationError("Confidence must be between 1 and 5")

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO question_analyses (
                        exam_context, question_source, question_source_id,
                        answered_incorrectly_date, user_selected_answer,
                        correct_answer, perceived_difficulty,
                        metacognitive_reflection, question_explanation,
                        user_notes, time_spent_on_question,
                        confidence_before_answer, mistake_category,
                        review_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_review')
                """, (
                    exam_context, question_source, question_source_id,
                    answered_incorrectly_date.isoformat(),
                    user_selected_answer, correct_answer,
                    perceived_difficulty, metacognitive_reflection,
                    question_explanation, user_notes,
                    time_spent_on_question, confidence_before_answer,
                    mistake_category
                ))

                question_id = cursor.lastrowid

                if self.error_logger:
                    self.error_logger.info(
                        f"Created question analysis ID {question_id} for {exam_context}",
                        category=ErrorCategory.DATABASE
                    )

                return self.get_question_analysis(question_id)

        except DatabaseIntegrityError as e:
            raise QuestionAnalysisError(
                f"Failed to create question analysis: {str(e)}"
            ) from e

    def get_question_analysis(self, question_id: int) -> Optional[QuestionAnalysis]:
        """Get question analysis by ID"""
        row = self.fetchone(
            "SELECT * FROM question_analyses WHERE id = ?",
            (question_id,)
        )
        return QuestionAnalysis.from_db_row(row) if row else None

    def assign_question_to_topics(
        self,
        question_id: int,
        subject_node_ids: List[int],
        assignment_type: str = 'primary'
    ) -> None:
        """
        Assign a question to subject nodes.

        Args:
            question_id: Question analysis ID
            subject_node_ids: List of subject node IDs to assign
            assignment_type: 'primary' or 'secondary'
        """
        if assignment_type not in self.VALID_ASSIGNMENT_TYPES:
            raise ValidationError(f"Invalid assignment type: {assignment_type}")

        # Get question to verify it exists and get exam context
        question = self.get_question_analysis(question_id)
        if not question:
            raise QuestionAnalysisError(f"Question {question_id} not found")

        with self.transaction():
            for node_id in subject_node_ids:
                # Verify node exists
                node = self.get_subject_node(node_id)
                if not node:
                    raise SubjectNodeError(f"Subject node {node_id} not found")

                # Check if assignment already exists
                existing = self.fetchone("""
                    SELECT id FROM question_topic_assignments
                    WHERE question_analysis_id = ? AND subject_node_id = ?
                """, (question_id, node_id))

                if not existing:
                    self.execute("""
                        INSERT INTO question_topic_assignments (
                            question_analysis_id, subject_node_id,
                            exam_context, assignment_type, assigned_by
                        ) VALUES (?, ?, ?, ?, 'user')
                    """, (question_id, node_id, question.exam_context, assignment_type))

    def get_questions_by_topic(
        self,
        subject_node_id: int,
        include_children: bool = False,
        limit: Optional[int] = None
    ) -> List[QuestionAnalysis]:
        """
        Get questions assigned to a topic.

        Args:
            subject_node_id: Subject node ID
            include_children: Include questions from child nodes
            limit: Maximum number of questions to return

        Returns:
            List of QuestionAnalysis objects
        """
        node_ids = [subject_node_id]

        if include_children:
            # Get all descendant node IDs
            node_ids.extend(self._get_descendant_node_ids(subject_node_id))

        placeholders = ','.join(['?'] * len(node_ids))
        query = f"""
            SELECT DISTINCT qa.*
            FROM question_analyses qa
            JOIN question_topic_assignments qta ON qa.id = qta.question_analysis_id
            WHERE qta.subject_node_id IN ({placeholders})
            ORDER BY qa.answered_incorrectly_date DESC
        """

        if limit:
            query += f" LIMIT {limit}"

        rows = self.fetchall(query, tuple(node_ids))
        return [QuestionAnalysis.from_db_row(row) for row in rows]

    def get_recent_questions(
        self,
        exam_context: Optional[str] = None,
        days_back: int = 30,
        limit: Optional[int] = 50
    ) -> List[QuestionAnalysis]:
        """
        Get recently analyzed questions.

        Args:
            exam_context: Optional exam filter
            days_back: Number of days to look back
            limit: Maximum number of questions

        Returns:
            List of QuestionAnalysis objects
        """
        query = """
            SELECT * FROM question_analyses
            WHERE answered_incorrectly_date >= date('now', ? || ' days')
        """
        params = [-days_back]

        if exam_context:
            query += " AND exam_context = ?"
            params.append(exam_context)

        query += " ORDER BY answered_incorrectly_date DESC, created_at DESC"

        if limit:
            query += f" LIMIT {limit}"

        rows = self.fetchall(query, tuple(params))
        return [QuestionAnalysis.from_db_row(row) for row in rows]

    def get_questions_by_mistake_category(
        self,
        mistake_category: str,
        exam_context: Optional[str] = None
    ) -> List[QuestionAnalysis]:
        """
        Get questions by mistake category.

        Args:
            mistake_category: Category of mistake
            exam_context: Optional exam filter

        Returns:
            List of QuestionAnalysis objects
        """
        if mistake_category not in self.VALID_MISTAKE_CATEGORIES:
            raise ValidationError(f"Invalid mistake category: {mistake_category}")

        query = "SELECT * FROM question_analyses WHERE mistake_category = ?"
        params = [mistake_category]

        if exam_context:
            query += " AND exam_context = ?"
            params.append(exam_context)

        query += " ORDER BY answered_incorrectly_date DESC"

        rows = self.fetchall(query, tuple(params))
        return [QuestionAnalysis.from_db_row(row) for row in rows]

    def get_mistake_statistics(
        self,
        exam_context: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Get statistics on mistake categories.

        Args:
            exam_context: Optional exam filter

        Returns:
            Dictionary of category -> count
        """
        query = """
            SELECT mistake_category, COUNT(*) as count
            FROM question_analyses
            WHERE mistake_category IS NOT NULL
        """

        if exam_context:
            query += " AND exam_context = ?"
            params = (exam_context,)
        else:
            params = None

        query += " GROUP BY mistake_category ORDER BY count DESC"

        rows = self.fetchall(query, params)
        return {row['mistake_category']: row['count'] for row in rows}

    def search_questions(
        self,
        search_term: str,
        exam_context: Optional[str] = None,
        include_notes: bool = True,
        include_reflection: bool = True
    ) -> List[QuestionAnalysis]:
        """
        Search questions by text content.

        Args:
            search_term: Text to search for
            exam_context: Optional exam filter
            include_notes: Search in user notes
            include_reflection: Search in metacognitive reflection

        Returns:
            List of matching QuestionAnalysis objects
        """
        conditions = []
        params = []

        # Build search conditions
        search_fields = ["question_source", "question_source_id"]
        if include_notes:
            search_fields.append("user_notes")
        if include_reflection:
            search_fields.append("metacognitive_reflection")

        search_conditions = " OR ".join([f"{field} LIKE ?" for field in search_fields])
        conditions.append(f"({search_conditions})")
        params.extend([f"%{search_term}%"] * len(search_fields))

        if exam_context:
            conditions.append("exam_context = ?")
            params.append(exam_context)

        query = f"""
            SELECT * FROM question_analyses
            WHERE {' AND '.join(conditions)}
            ORDER BY answered_incorrectly_date DESC
        """

        rows = self.fetchall(query, tuple(params))
        return [QuestionAnalysis.from_db_row(row) for row in rows]

    def get_hierarchy_levels(
        self,
        exam_context_id: int
    ) -> List['HierarchyLevelDefinition']:
        """
        Get all hierarchy levels for an exam context, ordered by level_order.

        Args:
            exam_context_id: ID of the exam context

        Returns:
            List of HierarchyLevelDefinition objects
        """
        from ..models import HierarchyLevelDefinition

        rows = self.fetchall("""
            SELECT * FROM hierarchy_level_definitions
            WHERE exam_context_id = ?
            ORDER BY level_order
        """, (exam_context_id,))

        return [HierarchyLevelDefinition.from_db_row(row) for row in rows]

    def get_hierarchy_level_definition(
        self,
        level_id: int
    ) -> Optional['HierarchyLevelDefinition']:
        """
        Get a specific hierarchy level definition.

        Args:
            level_id: ID of the hierarchy level

        Returns:
            HierarchyLevelDefinition object or None
        """
        from ..models import HierarchyLevelDefinition

        row = self.fetchone(
            "SELECT * FROM hierarchy_level_definitions WHERE id = ?",
            (level_id,)
        )
        return HierarchyLevelDefinition.from_db_row(row) if row else None

    def add_custom_hierarchy_level(
        self,
        exam_context_id: int,
        level_name: Optional[str] = None,
        display_name_template: Optional[str] = None
    ) -> 'HierarchyLevelDefinition':
        """
        Add a custom hierarchy level beyond the default 5.

        Args:
            exam_context_id: ID of the exam context
            level_name: Optional custom name (defaults to "Level N")
            display_name_template: Optional template for display (e.g., "Daughter of {parent_name}")

        Returns:
            HierarchyLevelDefinition object
        """
        from ..models import HierarchyLevelDefinition
        from ..exceptions import HierarchyLevelError

        # Get current max level order
        row = self.fetchone("""
            SELECT MAX(level_order) as max_order
            FROM hierarchy_level_definitions
            WHERE exam_context_id = ?
        """, (exam_context_id,))

        max_order = row['max_order'] if row and row['max_order'] else 0
        new_order = max_order + 1

        # Default name for custom levels
        if level_name is None:
            level_name = f"Level {new_order}"

        # Default template for custom levels
        if display_name_template is None:
            display_name_template = "Daughter of {parent_name}"

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO hierarchy_level_definitions (
                        exam_context_id, level_name, level_order,
                        is_required, display_name_template, is_custom_level
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    exam_context_id,
                    level_name,
                    new_order,
                    False,
                    display_name_template,
                    True
                ))

                level_id = cursor.lastrowid

                if self.error_logger:
                    self.error_logger.debug(
                        f"Added custom hierarchy level: {level_name} (order {new_order})",
                        category=ErrorCategory.DATABASE
                    )

            return self.get_hierarchy_level_definition(level_id)

        except DatabaseIntegrityError as e:
            raise HierarchyLevelError(
                f"Failed to add custom hierarchy level: {e}"
            ) from e

    def update_hierarchy_level(
        self,
        level_id: int,
        level_name: Optional[str] = None,
        display_name_template: Optional[str] = None
    ) -> 'HierarchyLevelDefinition':
        """
        Update a hierarchy level definition.

        Args:
            level_id: ID of the hierarchy level
            level_name: New level name
            display_name_template: New display template

        Returns:
            Updated HierarchyLevelDefinition object
        """
        updates = []
        params = []

        if level_name is not None:
            updates.append("level_name = ?")
            params.append(level_name)

        if display_name_template is not None:
            updates.append("display_name_template = ?")
            params.append(display_name_template)

        if not updates:
            return self.get_hierarchy_level_definition(level_id)

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(level_id)

        with self.transaction():
            self.execute(f"""
                UPDATE hierarchy_level_definitions
                SET {', '.join(updates)}
                WHERE id = ?
            """, tuple(params))

        return self.get_hierarchy_level_definition(level_id)

    # ==================== Stage 1: Hamilton Allocator ====================
    #
    # Implements §3.1 of
    # ``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`` — the
    # Largest Remainder (Hamilton) integer apportionment with a
    # weakness-biased tie-break. Pure read-side functions: no writes to
    # ``subject_node_weights`` from here. Higher-level callers (Stage 5
    # bridge surface, Stage 6 UI) are responsible for any audit-trail
    # bookkeeping.

    def allocate_questions_hamilton(
        self,
        parent_id: int,
        total_questions: int,
        *,
        weakness_lookup: Optional[Callable[[int], float]] = None,
        is_adaptive: bool = False,
    ) -> Dict[int, Any]:
        """Distribute ``total_questions`` across ``parent_id``'s child edges.

        Implements §3.1 of
        ``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``:

        1. Enumerate sibling edges via :meth:`EdgesMixin.get_sibling_edges`
           (cross-mixin call goes through ``self.*`` per the project's
           mixin-composition rule).
        2. **Anchored edges keep their explicit allocation.** For each
           edge with ``is_anchor=TRUE`` and a non-NULL ``relative_weight``,
           the allocation is ``round(relative_weight * total_questions /
           100)`` (banker's rounding via Python's built-in ``round``,
           clamped to ``[0, total_questions]``). The anchored share is
           then removed from the budget that the non-anchored siblings
           compete over. Anchored edges with NULL ``relative_weight``
           are treated as carrying weight 0 (they receive 0 questions).
        3. For non-anchored edges, compute exact share
           ``q_i = remaining_N · w_i / Σw``, ``floor`` each, and
           distribute leftover units one-by-one to the edges with the
           largest fractional remainder. Tie-break order:

           1. Larger fractional remainder
           2. Higher weakness score (lower historical accuracy →
              preferred for the marginal question)
           3. Lower ``edge_id`` (stable last-resort)

        Stage 8 — adaptive (CAT) branch
        --------------------------------
        When ``is_adaptive=True`` the allocator skips steps 2 (integer
        rounding) and 3 (remainder distribution / weakness tie-break)
        and returns the **raw exact share** ``q_i = N · w_i / Σw`` as
        a float for each non-anchored edge. Anchored edges still keep
        their explicit allocation ``relative_weight × total_questions
        / 100`` but as a float instead of an integer round. Rationale:
        CAT exams (NCLEX-RN, etc.) have no fixed length — forcing an
        integer Hamilton rounding lies about precision the underlying
        test doesn't have, and downstream UI rendering needs the float
        to display ``~26.4 q (planning estimate)`` instead of
        ``~26 q``.

        Edge cases:

        - Zero siblings → ``{}``.
        - All non-anchored weights sum to 0 → every non-anchored edge
          gets 0 questions; the function never divides by zero.
        - ``total_questions == 0`` → every edge gets 0.
        - Single non-anchored sibling with a positive weight → it
          receives the entire remaining budget.

        Args:
            parent_id: ``subject_nodes.id`` of the parent whose outgoing
                edges receive the allocation.
            total_questions: Effective question budget for the parent
                (typically ``length_typical * parent_effective_weight``,
                computed by the caller).
            weakness_lookup: Optional callable mapping ``edge_id ->
                float`` weakness score. Higher = weaker = preferred for
                the leftover question on a fractional-remainder tie.
                When omitted, every edge gets the neutral score 1.0,
                so tie-break rule 2 collapses and rule 3 (``edge_id``)
                decides. Ignored when ``is_adaptive=True`` (no
                tie-break path is exercised).
            is_adaptive: Stage 8 — when ``True`` (the exam's
                ``length_kind='range'`` i.e. CAT), return raw float
                shares instead of integer-rounded allocations.

        Returns:
            ``{edge_id: allocated_q}`` for every outgoing edge of
            ``parent_id``. Values are ``int`` when ``is_adaptive=False``
            (the canonical Hamilton output, summing to
            ``total_questions``) and ``float`` when ``is_adaptive=True``
            (raw exact shares; sum equals ``total_questions`` within
            float epsilon). For the adaptive case, anchored edges
            carry float ``relative_weight × total_questions / 100``
            (no rounding) so their precision is preserved end-to-end.

        Raises:
            AllocationFeasibilityError: When ``total_questions < 0`` or
                when any sibling edge carries a negative
                ``relative_weight``. Rounding-class infeasibility is
                **not** an exception — it lands in the Stage 7
                feasibility report instead.
        """
        if total_questions < 0:
            raise AllocationFeasibilityError(
                f"total_questions must be non-negative; got {total_questions}"
            )

        sibling_edges = self.get_sibling_edges(parent_id)
        if not sibling_edges:
            return {}

        # Validate weights up front so a single bad row is reported
        # before we start partitioning the budget.
        for edge in sibling_edges:
            rw = edge['relative_weight']
            if rw is not None and rw < 0:
                raise AllocationFeasibilityError(
                    f"Edge {edge['edge_id']} has negative relative_weight "
                    f"({rw}); Hamilton allocator requires non-negative weights."
                )

        if weakness_lookup is None:
            def weakness_lookup(_edge_id: int) -> float:  # type: ignore[misc]
                return 1.0

        allocations: Dict[int, Any] = {}

        # ---- Step 1/2: handle anchored edges, deduct from budget ----
        # Track the int and float anchored shares separately so the
        # adaptive branch can preserve float precision through the
        # remaining-budget computation.
        anchored_total_int = 0
        anchored_total_float = 0.0
        non_anchored: List[Dict[str, Any]] = []

        for edge in sibling_edges:
            if edge['is_anchor']:
                rw = edge['relative_weight']
                if rw is None:
                    # Anchored without a value: treat as 0 questions.
                    # Distinct from "anchored at 0" only in audit copy;
                    # both produce the same numeric outcome.
                    allocations[edge['edge_id']] = 0.0 if is_adaptive else 0
                    continue
                if is_adaptive:
                    # Float-precise anchored share. Clamp to [0, N] to
                    # match the int-mode clamping invariant.
                    anchored_q_float = max(
                        0.0,
                        min(float(total_questions), rw * total_questions / 100.0),
                    )
                    allocations[edge['edge_id']] = anchored_q_float
                    anchored_total_float += anchored_q_float
                else:
                    # Round to nearest whole question; clamp to the budget.
                    anchored_q = max(
                        0,
                        min(total_questions, int(round(rw * total_questions / 100.0))),
                    )
                    allocations[edge['edge_id']] = anchored_q
                    anchored_total_int += anchored_q
            else:
                non_anchored.append(edge)

        if is_adaptive:
            remaining_float = max(
                0.0, float(total_questions) - anchored_total_float
            )
        else:
            remaining_float = float(
                max(0, total_questions - anchored_total_int)
            )

        # If anchors consumed the entire budget, every non-anchored
        # edge gets 0. Same when there are no non-anchored edges.
        if (
            not non_anchored
            or remaining_float <= 0
            or total_questions == 0
        ):
            zero: Any = 0.0 if is_adaptive else 0
            for edge in non_anchored:
                allocations[edge['edge_id']] = zero
            return allocations

        # ---- Step 3: largest-remainder distribution over non-anchored ----
        weights = [
            (edge['edge_id'], (edge['relative_weight'] or 0.0))
            for edge in non_anchored
        ]
        total_weight = sum(w for _eid, w in weights)

        if total_weight <= 0:
            # No information to distribute by — every non-anchored edge
            # gets 0. Defensive against division-by-zero per the design
            # doc's "Sum of weights = 0" edge case.
            zero = 0.0 if is_adaptive else 0
            for edge_id, _w in weights:
                allocations[edge_id] = zero
            return allocations

        exact_shares = [
            (edge_id, remaining_float * w / total_weight)
            for edge_id, w in weights
        ]

        if is_adaptive:
            # Stage 8 — return raw float shares; no flooring, no
            # remainder distribution. The UI renders these as
            # ``~26.4 q (planning estimate)`` so the user can see the
            # CAT exam has no fixed precision.
            for edge_id, share in exact_shares:
                allocations[edge_id] = share
            return allocations

        # Integer Hamilton: floor then distribute leftover via the
        # tie-break in :meth:`_largest_remainder`.
        non_anchored_alloc = self._largest_remainder(
            exact_shares, int(remaining_float), weakness_lookup
        )
        allocations.update(non_anchored_alloc)
        return allocations

    @staticmethod
    def _largest_remainder(
        shares: List[Tuple[int, float]],
        total: int,
        weakness_lookup: Callable[[int], float],
    ) -> Dict[int, int]:
        """Floor each exact share, then distribute leftover units.

        Pure function — no DB access, no instance state. Easy to unit
        test in isolation per
        ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md`` Stage 1.

        Args:
            shares: ``[(edge_id, exact_share_float), ...]``. Order is
                preserved as a stable secondary key only insofar as
                tie-break rule 3 (lower ``edge_id``) reproduces it.
            total: Integer budget being apportioned. Equals the sum of
                the exact shares (within float epsilon).
            weakness_lookup: ``edge_id -> float``. Higher value wins
                tie-break rule 2.

        Returns:
            ``{edge_id: integer_allocation}``. Values sum to ``total``
            when ``shares`` contains at least one entry with a positive
            exact share (otherwise the budget is unreachable and the
            return collapses to all zeros, which is safe — the public
            allocator handles the zero-weight case before calling here).
        """
        if not shares:
            return {}

        floors: Dict[int, int] = {}
        remainders: List[Tuple[int, float]] = []
        for edge_id, exact in shares:
            floor_val = int(math.floor(exact))
            floors[edge_id] = floor_val
            remainders.append((edge_id, exact - floor_val))

        leftover = total - sum(floors.values())
        if leftover <= 0:
            # Defensive: floor sum can briefly exceed total when
            # callers pass slightly-too-generous shares (e.g., from
            # round-trip floating point math). Trim deterministically
            # by reducing the edges with the smallest fractional
            # remainder — but in practice this branch should not fire
            # for the budgets the allocator constructs above.
            return floors

        # Sort by tie-break:
        # 1. Larger fractional remainder (descending → negate)
        # 2. Higher weakness score (descending → negate)
        # 3. Lower edge_id (ascending → no negate)
        ranked = sorted(
            remainders,
            key=lambda er: (
                -er[1],
                -float(weakness_lookup(er[0])),
                er[0],
            ),
        )

        for edge_id, _rem in ranked[:leftover]:
            floors[edge_id] += 1
        return floors

    def compute_weakness_scores(
        self,
        edge_ids: List[int],
        *,
        half_life_days: int = _HALF_LIFE_DAYS,
    ) -> Dict[int, float]:
        """Recency-decayed mistake-rate per edge.

        Used by :meth:`allocate_questions_hamilton` as tie-break rule 2.
        Higher score = weaker topic (lower historical accuracy) =
        preferred to receive the leftover question per pedagogy goal in
        §3.1 of ``HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``.

        Algorithm (per the implementation plan's Stage 1 spec):

        1. For each ``edge_id``, look up the edge's parent_id and child_id.
        2. Find ``entry_subject_mappings`` rows where the entry is mapped
           to the child (or the child's primary mapping is overridden via
           ``primary_parent_id``) and where the *parent context* is the
           edge's parent_id. This scopes mistakes correctly: a leaf
           reachable through multiple parents does not pollute its
           other-parent weakness scores.
        3. Apply exponential recency decay to each entry's session date:
           ``weight = exp(-ln(2) · age_days / half_life_days)``.
        4. Score = ``weighted_mistake_count / weighted_attempt_count``.

        WIMI logs only mistakes (every ``question_entries`` row is a
        wrong answer the user reflected on — see the schema in
        ``user_db_schema_v1_phase4.sql``), so weighted_mistake_count and
        weighted_attempt_count coincide. The ratio is therefore 1.0 for
        any edge with at least one mapping. We still compute the
        weighted sum so the score reflects *recency*: an edge with one
        very old mistake gets a smaller weighted count than an edge
        with one recent mistake, and on a fractional-remainder tie the
        more-recent edge wins. Edges with no mappings return 1.0
        (neutral — does not bias tie-break beyond rule 3).

        Args:
            edge_ids: List of ``subject_edges.id`` to score. Empty
                list returns ``{}``.
            half_life_days: Number of days after which a mistake's
                contribution is halved. Defaults to the module
                constant ``_HALF_LIFE_DAYS`` (90 days). Must be > 0.

        Returns:
            ``{edge_id: weakness_score}`` for every edge_id in the
            input list (including edges with no mistake history, which
            map to ``1.0``).
        """
        if not edge_ids:
            return {}
        if half_life_days <= 0:
            raise ValidationError(
                f"half_life_days must be positive; got {half_life_days}"
            )

        # SQLite cannot bind a list directly — build a placeholder set.
        placeholders = ",".join(["?"] * len(edge_ids))
        edge_rows = self.fetchall(
            f"SELECT id AS edge_id, parent_id, child_id "
            f"FROM subject_edges WHERE id IN ({placeholders})",
            tuple(edge_ids),
        )
        edge_lookup = {
            row['edge_id']: (row['parent_id'], row['child_id'])
            for row in edge_rows
        }

        decay = math.log(2) / half_life_days
        today = date.today()
        scores: Dict[int, float] = {}

        for edge_id in edge_ids:
            ctx = edge_lookup.get(edge_id)
            if ctx is None:
                # Edge id doesn't exist (defensive — caller passed a
                # stale id). Neutral score so it doesn't crash the
                # allocator.
                scores[edge_id] = 1.0
                continue
            parent_id, child_id = ctx

            # Pull every dated mistake on this child whose parent
            # context matches this edge's parent. ``primary_parent_id``
            # NULL means "count under all parents" per §5.4 of the
            # polyhierarchy plan, so the OR clause includes those rows
            # even when they didn't pin a context — they still belong
            # to *this* edge's parent unless explicitly overridden.
            rows = self.fetchall(
                """
                SELECT rs.date_encountered AS d
                FROM entry_subject_mappings esm
                JOIN question_entries qe ON qe.id = esm.question_entry_id
                JOIN review_sessions rs ON rs.id = qe.review_session_id
                WHERE esm.subject_node_id = ?
                  AND (
                        esm.primary_parent_id = ?
                        OR (esm.primary_parent_id IS NULL)
                      )
                """,
                (child_id, parent_id),
            )

            if not rows:
                scores[edge_id] = 1.0
                continue

            weighted = 0.0
            for row in rows:
                d_raw = row['d']
                if d_raw is None:
                    continue
                # ``date_encountered`` arrives as a string (SQLite stores
                # DATE as text); be tolerant of both that and a real
                # ``date`` instance.
                if isinstance(d_raw, date):
                    enc_date = d_raw
                else:
                    try:
                        enc_date = date.fromisoformat(str(d_raw)[:10])
                    except (ValueError, TypeError):
                        continue
                age_days = max(0, (today - enc_date).days)
                weighted += math.exp(-decay * age_days)

            if weighted <= 0:
                # All rows had unparseable dates — neutral score.
                scores[edge_id] = 1.0
            else:
                # Weighted mistake count divided by weighted attempt
                # count. Since WIMI logs only mistakes, both sums are
                # the same, so the ratio is 1.0 by construction. The
                # *value* still encodes recency via the weighted sum
                # — but for the public API contract we return the
                # ratio so callers don't need to know the model.
                # However, returning 1.0 for everything would defeat
                # tie-break rule 2; we therefore expose ``weighted``
                # itself as the score, since "more recent activity =
                # weaker topic, prefer for leftover" is the desired
                # semantic and weighted sums are monotonic in recency.
                scores[edge_id] = weighted

        return scores

    # ==================== Phase 2: Weight Management ====================

    def update_subject_node_weight(
        self,
        node_id: int,
        new_weight: float,
        reason: Optional[str] = None,
        user_notes: Optional[str] = None
    ) -> 'WeightUpdateResult':
        """
        Update a subject node's weight with automatic sibling balancing.

        Args:
            node_id: ID of the node to update
            new_weight: New weight value (relative % of parent)
            reason: Optional reason for the change
            user_notes: Optional user notes

        Returns:
            WeightUpdateResult with updated node and affected siblings

        Raises:
            WeightValidationError: If weight is invalid
            SubjectNodeError: If node not found
        """
        from ..models import WeightUpdateResult, SubjectNodeWeight
        from ..exceptions import WeightValidationError, WeightBalancingError

        # Ensure Phase 2 tables exist
        self._ensure_phase2_schema()

        # Get the node
        node = self.get_subject_node(node_id)
        if not node:
            raise SubjectNodeError(f"Subject node {node_id} not found")

        # Get exam context settings
        exam_context = self.get_exam_context_by_name(node.exam_context)
        if not exam_context:
            # Default settings if no exam context configured
            settings = {
                'autonomous_weight_balancing': True,
                'precision_decimal_places': 1,
                'require_exact_100': True,
                'balancing_algorithm': 'proportional'
            }
        else:
            settings = exam_context.weight_validation_rules

        # Validate new weight
        self._validate_weight(new_weight, settings)

        # Get siblings (nodes with same parent)
        siblings = self._get_sibling_nodes(node_id)

        # Calculate weight change
        old_weight = node.exam_weight_low or 0.0
        weight_change = new_weight - old_weight

        # Determine affected siblings and new weights
        updated_siblings = []
        weight_history_ids = []

        if settings.get('autonomous_weight_balancing', True) and siblings and abs(weight_change) > 0.001:
            if settings.get('balancing_algorithm', 'proportional') == 'proportional':
                updated_siblings = self._proportional_distribution(siblings, weight_change)
            else:
                updated_siblings = self._even_distribution(siblings, weight_change)

            # Validate total (if required)
            if settings.get('require_exact_100', True):
                total = new_weight + sum(s['new_weight'] for s in updated_siblings)
                tolerance = 10 ** (-settings.get('precision_decimal_places', 1))
                if abs(total - 100.0) > tolerance:
                    raise WeightBalancingError(
                        f"Total weight {total:.2f}% must equal 100% (tolerance: {tolerance}%)"
                    )

        # Update database within transaction
        with self.transaction():
            # Update main node
            self.execute("""
                UPDATE subject_nodes
                SET exam_weight_low = ?, exam_weight_high = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_weight, new_weight, node_id))

            # Record weight history for main node.
            # ``edge_id`` is NULL here: this is a node-level write
            # against ``subject_nodes`` with no specific parent-edge
            # context. Stage 0 of WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md
            # threads the new column through so legacy call sites line
            # up; edge-keyed call sites land in later stages.
            cursor = self.execute("""
                INSERT INTO subject_node_weights (
                    subject_node_id, weight_value, edited_by, edited_reason,
                    previous_weight, change_type, affected_siblings, user_notes,
                    edge_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                node_id,
                new_weight,
                'user',
                reason or 'User manual edit',
                old_weight,
                'manual_edit',
                json.dumps([s['id'] for s in updated_siblings]),
                user_notes,
                None,
            ))
            weight_history_ids.append(cursor.lastrowid)

            # Update siblings and record history
            for sibling in updated_siblings:
                self.execute("""
                    UPDATE subject_nodes
                    SET exam_weight_low = ?, exam_weight_high = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (sibling['new_weight'], sibling['new_weight'], sibling['id']))

                # Record sibling weight history. ``edge_id`` is NULL
                # for the same reason as the parent record above —
                # this is a node-level auto-adjust that pre-dates the
                # per-edge weight model.
                cursor = self.execute("""
                    INSERT INTO subject_node_weights (
                        subject_node_id, weight_value, edited_by, edited_reason,
                        previous_weight, change_type, affected_siblings,
                        edge_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sibling['id'],
                    sibling['new_weight'],
                    'system',
                    f"Auto-adjusted due to node {node_id} weight change",
                    sibling['old_weight'],
                    'auto_recalculate',
                    json.dumps([node_id] + [s['id'] for s in updated_siblings if s['id'] != sibling['id']]),
                    None,
                ))
                weight_history_ids.append(cursor.lastrowid)

            if self.error_logger:
                self.error_logger.info(
                    f"Updated weight for node {node_id}: {old_weight}% -> {new_weight}%, "
                    f"affected {len(updated_siblings)} siblings",
                    category=ErrorCategory.DATABASE
                )

        # Return result
        return WeightUpdateResult(
            updated_node=self.get_subject_node(node_id),
            affected_siblings=[self.get_subject_node(s['id']) for s in updated_siblings],
            total_updates=1 + len(updated_siblings),
            weight_history_ids=weight_history_ids
        )

    def _validate_weight(
        self,
        weight: float,
        settings: Dict[str, Any]
    ) -> None:
        """
        Validate weight against settings.

        Args:
            weight: Weight value to validate
            settings: Weight validation rules from exam context

        Raises:
            WeightValidationError: If validation fails
        """
        from ..exceptions import WeightValidationError

        # Range check
        if weight < 0 or weight > 100:
            raise WeightValidationError(
                f"Weight {weight}% must be between 0% and 100%"
            )

        # Precision check
        precision = settings.get('precision_decimal_places', 1)
        rounded = round(weight, precision)
        tolerance = 10 ** (-(precision + 2))  # Allow for float precision issues
        if abs(weight - rounded) > tolerance:
            raise WeightValidationError(
                f"Weight {weight}% exceeds precision of {precision} decimal place(s)"
            )

    def _get_sibling_nodes(self, node_id: int) -> List[Dict[str, Any]]:
        """
        Get sibling nodes (same parent) for weight balancing.

        Args:
            node_id: ID of the reference node

        Returns:
            List of dicts with id and weight for each sibling
        """
        # Get parent_id
        row = self.fetchone(
            "SELECT parent_id FROM subject_nodes WHERE id = ?",
            (node_id,)
        )

        if not row or row['parent_id'] is None:
            return []

        parent_id = row['parent_id']

        # Get siblings (excluding self)
        rows = self.fetchall("""
            SELECT id, exam_weight_low as weight
            FROM subject_nodes
            WHERE parent_id = ? AND id != ? AND status = 'active'
        """, (parent_id, node_id))

        return [{'id': row['id'], 'weight': row['weight'] or 0.0} for row in rows]

    def _proportional_distribution(
        self,
        siblings: List[Dict[str, Any]],
        change_amount: float
    ) -> List[Dict[str, Any]]:
        """
        Distribute weight change proportionally among siblings.

        This algorithm distributes the weight change to siblings based on
        their current relative weights, preserving proportional relationships.

        Args:
            siblings: List of sibling nodes with 'id' and 'weight'
            change_amount: Amount to distribute (positive = reduce siblings, negative = increase)

        Returns:
            List of dicts with id, old_weight, and new_weight for each sibling
        """
        if not siblings:
            return []

        # Calculate total weight of siblings
        total_weight = sum(s['weight'] for s in siblings)

        if total_weight == 0:
            # If all siblings are 0, fall back to even distribution
            return self._even_distribution(siblings, change_amount)

        # Calculate proportional changes
        result = []
        for sibling in siblings:
            proportion = sibling['weight'] / total_weight
            adjustment = change_amount * proportion
            new_weight = max(0.0, sibling['weight'] - adjustment)  # Prevent negative

            result.append({
                'id': sibling['id'],
                'old_weight': sibling['weight'],
                'new_weight': round(new_weight, 3)  # Round to avoid float issues
            })

        return result

    def _even_distribution(
        self,
        siblings: List[Dict[str, Any]],
        change_amount: float
    ) -> List[Dict[str, Any]]:
        """
        Distribute weight change evenly among siblings.

        Args:
            siblings: List of sibling nodes with 'id' and 'weight'
            change_amount: Amount to distribute

        Returns:
            List of dicts with id, old_weight, and new_weight for each sibling
        """
        if not siblings:
            return []

        per_sibling = change_amount / len(siblings)

        result = []
        for sibling in siblings:
            new_weight = max(0.0, sibling['weight'] - per_sibling)  # Prevent negative
            result.append({
                'id': sibling['id'],
                'old_weight': sibling['weight'],
                'new_weight': round(new_weight, 3)
            })

        return result

    def get_weight_history(
        self,
        node_id: int,
        limit: Optional[int] = 50
    ) -> List['SubjectNodeWeight']:
        """
        Get weight change history for a subject node.

        Args:
            node_id: ID of the subject node
            limit: Maximum number of records to return

        Returns:
            List of SubjectNodeWeight objects, most recent first
        """
        from ..models import SubjectNodeWeight

        query = """
            SELECT * FROM subject_node_weights
            WHERE subject_node_id = ?
            ORDER BY id DESC
        """

        if limit:
            query += f" LIMIT {limit}"

        rows = self.fetchall(query, (node_id,))
        return [SubjectNodeWeight.from_db_row(row) for row in rows]

    def get_recent_weight_changes(
        self,
        exam_context: Optional[str] = None,
        days_back: int = 30,
        limit: Optional[int] = 100
    ) -> List['SubjectNodeWeight']:
        """
        Get recent weight changes across all nodes.

        Args:
            exam_context: Optional filter by exam context
            days_back: Number of days to look back
            limit: Maximum number of records to return

        Returns:
            List of SubjectNodeWeight objects, most recent first
        """
        from ..models import SubjectNodeWeight

        query = """
            SELECT snw.*
            FROM subject_node_weights snw
            JOIN subject_nodes sn ON snw.subject_node_id = sn.id
            WHERE snw.edited_date >= date('now', ? || ' days')
        """
        params = [-days_back]

        if exam_context:
            query += " AND sn.exam_context = ?"
            params.append(exam_context)

        query += " ORDER BY snw.edited_date DESC, snw.created_at DESC"

        if limit:
            query += f" LIMIT {limit}"

        rows = self.fetchall(query, tuple(params))
        return [SubjectNodeWeight.from_db_row(row) for row in rows]

    def get_weight_statistics(
        self,
        exam_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get weight change statistics.

        Args:
            exam_context: Optional filter by exam context

        Returns:
            Dictionary with statistics about weight changes
        """
        base_query = """
            SELECT
                COUNT(*) as total_changes,
                SUM(CASE WHEN snw.change_type = 'manual_edit' THEN 1 ELSE 0 END) as manual_edits,
                SUM(CASE WHEN snw.change_type = 'auto_recalculate' THEN 1 ELSE 0 END) as auto_adjustments,
                COUNT(DISTINCT snw.subject_node_id) as nodes_changed
            FROM subject_node_weights snw
        """

        if exam_context:
            base_query += """
                JOIN subject_nodes sn ON snw.subject_node_id = sn.id
                WHERE sn.exam_context = ?
            """
            row = self.fetchone(base_query, (exam_context,))
        else:
            row = self.fetchone(base_query)

        if not row:
            return {
                'total_changes': 0,
                'manual_edits': 0,
                'auto_adjustments': 0,
                'nodes_changed': 0
            }

        return {
            'total_changes': row['total_changes'] or 0,
            'manual_edits': row['manual_edits'] or 0,
            'auto_adjustments': row['auto_adjustments'] or 0,
            'nodes_changed': row['nodes_changed'] or 0
        }

    def update_subject_relative_weight(
        self,
        node_id: int,
        relative_weight: float,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update a subject's relative weight on its primary parent edge.

        .. deprecated:: Stage 2 (WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md)
            Prefer :meth:`update_edge_relative_weight` for edge-aware
            writes; this shim remains for one release for backward
            compatibility.

        **Behavior change in Stage 2:** sibling weights are **no longer
        auto-mutated** when this method is called. Callers wanting
        redistribution must invoke
        :meth:`rebalance_sibling_edge_weights` separately. The returned
        payload always reports ``rebalanced=False`` and
        ``affected_siblings=[]`` so the contract is explicit.

        Internally, this delegates to
        :meth:`update_edge_relative_weight` keyed on the node's primary
        parent edge (``subject_edges.is_primary=TRUE``). When the node
        has no primary edge (top-level/root node), the legacy
        ``subject_nodes.relative_weight`` column is updated directly so
        existing call sites still see a write.

        Args:
            node_id: Subject node ID to update
            relative_weight: New relative weight (0-100)
            reason: Optional reason for the change

        Returns:
            Dictionary with update results::

                {
                    'updated_node': SubjectNode,
                    'affected_siblings': [],   # always empty (Stage 2)
                    'old_weight': float,
                    'new_weight': float,
                    'rebalanced': False        # always False (Stage 2)
                }

        Raises:
            SubjectNodeError: If node not found or is locked
            WeightValidationError: If weight is invalid
        """
        from ..exceptions import WeightValidationError

        # Validate weight
        if relative_weight < 0 or relative_weight > 100:
            raise WeightValidationError("Relative weight must be between 0 and 100")

        # Get the node
        node = self.get_subject_node(node_id)
        if not node:
            raise SubjectNodeError(f"Subject node {node_id} not found")

        # Check if locked (legacy flag)
        if node.weight_locked:
            raise SubjectNodeError(f"Subject node {node_id} has locked weights and cannot be modified")

        old_weight = node.relative_weight or 0.0

        # Look up the node's primary parent edge so we can delegate to
        # the edge-aware writer. This is the canonical write path going
        # forward (Stage 3 will replace this shim entirely).
        primary_edge_row = self.fetchone(
            "SELECT id FROM subject_edges "
            "WHERE child_id = ? AND is_primary = TRUE LIMIT 1",
            (node_id,)
        )

        if primary_edge_row is not None:
            # Delegate to the edge-aware writer. It handles the
            # subject_edges UPDATE plus a properly-tagged history row.
            edge_result = self.update_edge_relative_weight(
                edge_id=primary_edge_row['id'],
                relative_weight=relative_weight,
                set_anchor=False,
                source='user_estimate',
                reason=reason,
            )
            # Also mirror the value onto the legacy
            # ``subject_nodes.relative_weight`` column for any read
            # paths that have not yet been cut over to ``subject_edges``
            # (Stage 10 will drop those columns, but until then they
            # must stay in sync to avoid silent regressions).
            with self.transaction():
                self.execute(
                    """
                    UPDATE subject_nodes
                    SET relative_weight = ?,
                        weight_source = CASE
                            WHEN weight_source = 'official' THEN 'official'
                            ELSE 'user_estimate'
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (relative_weight, node_id),
                )
        else:
            # No primary edge — node is root (or orphaned). Fall back to
            # the legacy node-level write so the column still updates.
            # No edge means no edge_id for the history row.
            with self.transaction():
                self.execute(
                    """
                    UPDATE subject_nodes
                    SET relative_weight = ?,
                        weight_source = CASE
                            WHEN weight_source = 'official' THEN 'official'
                            ELSE 'user_estimate'
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (relative_weight, node_id),
                )
                try:
                    self.execute(
                        """
                        INSERT INTO subject_node_weights (
                            subject_node_id, weight_value, relative_weight_value,
                            weight_type, edited_by, edited_reason,
                            previous_weight, change_type, affected_siblings,
                            edge_id
                        ) VALUES (?, ?, ?, 'relative', 'user', ?, ?, 'manual_edit', ?, ?)
                        """,
                        (
                            node_id,
                            node.exam_weight_low,
                            relative_weight,
                            reason or 'User manual edit',
                            old_weight,
                            json.dumps([]),
                            None,
                        ),
                    )
                except Exception:
                    pass  # Phase 2 tables may not exist

        if self.error_logger:
            self.error_logger.info(
                f"Updated relative weight for node {node_id}: {old_weight}% -> {relative_weight}% "
                f"(no sibling rebalance — Stage 2 opt-in)",
                category=ErrorCategory.DATABASE
            )

        return {
            'updated_node': self.get_subject_node(node_id),
            'affected_siblings': [],
            'old_weight': old_weight,
            'new_weight': relative_weight,
            'rebalanced': False,
        }

    def update_edge_relative_weight(
        self,
        edge_id: int,
        relative_weight: float,
        *,
        set_anchor: bool = False,
        source: str = 'user_explicit',
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update the ``relative_weight`` for a single ``subject_edges`` row.

        Stage 2 of the Hierarchical Weight Allocation Implementation
        Plan. This is the canonical per-edge writer — it touches
        exactly one edge and **never** rebalances siblings. Callers
        that want sibling redistribution must call
        :meth:`rebalance_sibling_edge_weights` separately.

        Args:
            edge_id: ``subject_edges.id`` to update.
            relative_weight: New weight value (0-100).
            set_anchor: When True, also sets ``subject_edges.is_anchor``
                to True on the same edge. Stage 3 will add a dedicated
                ``set_edge_anchor`` method that is the canonical anchor
                toggle; this parameter is a convenience for callers
                that need to write-and-anchor in one operation (e.g.
                the explicit-typed-value flow).
            source: ``weight_source`` value to record on the edge.
                Defaults to ``'user_explicit'`` since this method is
                the user-typed write path; pass other enum values for
                non-user writes.
            reason: Optional reason for the change (recorded in the
                history row).

        Returns:
            ``{'ok': True, 'edge_id': int, 'old_weight': float,
            'new_weight': float, 'anchor_set': bool}``

        Raises:
            WeightValidationError: When ``relative_weight`` is outside
                ``[0, 100]``.
            SubjectNodeError: When ``edge_id`` does not exist.
        """
        from ..exceptions import WeightValidationError

        if relative_weight < 0 or relative_weight > 100:
            raise WeightValidationError("Relative weight must be between 0 and 100")

        edge_row = self.fetchone(
            "SELECT id, parent_id, child_id, relative_weight, is_anchor, weight_source "
            "FROM subject_edges WHERE id = ?",
            (edge_id,),
        )
        if edge_row is None:
            raise SubjectNodeError(f"Subject edge {edge_id} not found")

        old_weight = float(edge_row['relative_weight']) if edge_row['relative_weight'] is not None else 0.0
        child_id = edge_row['child_id']

        with self.transaction():
            # Write the new edge weight + (optionally) anchor flag.
            # Anchor flips run in the same statement so the edge row
            # is internally consistent at every commit boundary.
            if set_anchor:
                self.execute(
                    "UPDATE subject_edges "
                    "SET relative_weight = ?, weight_source = ?, "
                    "    is_anchor = TRUE, "
                    "    updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (relative_weight, source, edge_id),
                )
            else:
                self.execute(
                    "UPDATE subject_edges "
                    "SET relative_weight = ?, weight_source = ?, "
                    "    updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (relative_weight, source, edge_id),
                )

            # Record the history row tagged with the new
            # ``edge_weight_edit`` change_type (added by m006). The
            # subject_node_weights table still requires a child node id,
            # so we use the edge's child_id for the FK; ``edge_id``
            # carries the per-parent context that node_id alone cannot.
            #
            # Note: we only reference columns that are actually present
            # in the live phase 2 schema (``user_db_schema_v1_phase2.sql``).
            # Earlier code in this file historically referenced
            # ``relative_weight_value`` / ``weight_type`` which exist
            # only in legacy planning docs — the broad ``except`` below
            # was silently swallowing those bind errors. We keep the
            # ``try/except`` for environments that may not yet have the
            # phase 2 table at all (some early-phase test setups).
            try:
                self.execute(
                    """
                    INSERT INTO subject_node_weights (
                        subject_node_id, weight_value,
                        edited_by, edited_reason,
                        previous_weight, change_type, affected_siblings,
                        edge_id
                    ) VALUES (?, ?, 'user', ?, ?, 'edge_weight_edit', '[]', ?)
                    """,
                    (
                        child_id,
                        relative_weight,
                        reason or 'Edge weight edit',
                        old_weight,
                        edge_id,
                    ),
                )
            except Exception:
                # Phase 2 tables may not exist in older test setups.
                pass

        if self.error_logger:
            self.error_logger.info(
                f"Updated edge {edge_id} relative_weight: {old_weight}% -> {relative_weight}% "
                f"(anchor_set={set_anchor}, source={source})",
                category=ErrorCategory.DATABASE,
            )

        return {
            'ok': True,
            'edge_id': edge_id,
            'old_weight': old_weight,
            'new_weight': relative_weight,
            'anchor_set': bool(set_anchor),
        }

    def _get_relative_weight_siblings(
        self,
        node_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get sibling nodes with their relative weights for rebalancing.

        Args:
            node_id: Reference node ID

        Returns:
            List of sibling dicts with id, name, relative_weight, weight_locked
        """
        # Get parent_id of the node
        node_row = self.fetchone(
            "SELECT parent_id FROM subject_nodes WHERE id = ?",
            (node_id,)
        )

        if not node_row or node_row['parent_id'] is None:
            return []  # Root nodes have no siblings to rebalance with

        parent_id = node_row['parent_id']

        # Get all siblings (excluding self)
        siblings = self.fetchall("""
            SELECT id, name, relative_weight, weight_locked
            FROM subject_nodes
            WHERE parent_id = ? AND id != ? AND status = 'active'
        """, (parent_id, node_id))

        return [
            {
                'id': s['id'],
                'name': s['name'],
                'relative_weight': s['relative_weight'] or 0.0,
                'weight_locked': bool(s['weight_locked'])
            }
            for s in siblings
        ]

    def rebalance_sibling_edge_weights(
        self,
        parent_id: int,
        *,
        exclude_anchored: bool = True,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rebalance sibling edge weights so they sum to 100% under ``parent_id``.

        Stage 2 of the Hierarchical Weight Allocation Implementation
        Plan. This is the **explicit** rebalance entry point — the
        writer methods (:meth:`update_edge_relative_weight`,
        :meth:`update_subject_relative_weight`) no longer call this
        implicitly. Callers must opt in.

        Edge-aware: walks ``subject_edges`` via
        :meth:`EdgesMixin.get_sibling_edges`, not
        ``subject_nodes.parent_id``. Excludes from the adjustable set:

        - Edges with ``is_anchor=TRUE`` (when ``exclude_anchored=True``)
        - Edges whose child node has the legacy
          ``subject_nodes.weight_locked=TRUE`` flag set (both flags
          exclude — they coexist per plan §3.3 / Stage 2 open-question
          decision).

        The unallocated remainder is distributed proportionally across
        the adjustable set. Anchored / locked edges keep their existing
        weight byte-identical.

        Args:
            parent_id: Parent node whose outgoing edges to rebalance.
            exclude_anchored: When True (default), edges with
                ``is_anchor=TRUE`` are skipped. Set False to force
                rebalance across every non-locked edge regardless of
                anchor state (used rarely — typically by a "reset all"
                flow that the user has explicitly confirmed).
            reason: Optional reason recorded on each history row.

        Returns:
            ``{
                'ok': True,
                'parent_id': int,
                'affected_edges': [
                    {'edge_id': int, 'child_id': int,
                     'old_weight': float, 'new_weight': float}, ...
                ],
                'skipped': [
                    {'edge_id': int, 'child_id': int, 'reason': str}, ...
                ]
            }``
        """
        # Enumerate all outgoing edges via the canonical edge query.
        # EdgesMixin.get_sibling_edges is the source of truth for
        # "what are the siblings under this parent" — see plan
        # Stage 1 §"Files to create / modify".
        sibling_edges = self.get_sibling_edges(parent_id)

        if not sibling_edges:
            return {
                'ok': True,
                'parent_id': parent_id,
                'affected_edges': [],
                'skipped': [],
            }

        # Fetch the legacy weight_locked flags in one query so we can
        # filter without a per-edge round-trip. The flag lives on
        # subject_nodes (it predates the polyhierarchy migration); we
        # JOIN on child_id to learn whether each edge's child is
        # locked.
        child_ids = tuple(e['child_id'] for e in sibling_edges)
        placeholders = ','.join('?' * len(child_ids))
        locked_rows = self.fetchall(
            f"SELECT id, weight_locked FROM subject_nodes WHERE id IN ({placeholders})",
            child_ids,
        )
        locked_lookup = {
            row['id']: bool(row['weight_locked']) for row in locked_rows
        }

        adjustable: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        for edge in sibling_edges:
            edge_id = edge['edge_id']
            child_id = edge['child_id']
            is_anchor = edge['is_anchor']
            is_locked = locked_lookup.get(child_id, False)

            if exclude_anchored and is_anchor:
                skipped.append({
                    'edge_id': edge_id,
                    'child_id': child_id,
                    'reason': 'anchored',
                })
                continue
            if is_locked:
                skipped.append({
                    'edge_id': edge_id,
                    'child_id': child_id,
                    'reason': 'weight_locked',
                })
                continue
            adjustable.append(edge)

        if not adjustable:
            # Everything is anchored or locked — nothing to rebalance.
            return {
                'ok': True,
                'parent_id': parent_id,
                'affected_edges': [],
                'skipped': skipped,
            }

        # Compute the locked/anchored weight footprint and the budget
        # left over for the adjustable edges. NULL weights count as
        # zero so an uncategorized edge participates as 0.
        anchored_total = sum(
            float(e['relative_weight']) if e['relative_weight'] is not None else 0.0
            for e in sibling_edges
            if e not in adjustable
        )
        remainder = max(0.0, 100.0 - anchored_total)

        adjustable_current_total = sum(
            float(e['relative_weight']) if e['relative_weight'] is not None else 0.0
            for e in adjustable
        )

        affected_edges: List[Dict[str, Any]] = []

        with self.transaction():
            if adjustable_current_total <= 0.001:
                # All adjustable edges are zero or null — split the
                # remainder evenly. This is the "first-time rebalance"
                # path where no priors exist to anchor against.
                per_edge = remainder / len(adjustable)
                for edge in adjustable:
                    old_w = (
                        float(edge['relative_weight'])
                        if edge['relative_weight'] is not None
                        else 0.0
                    )
                    new_w = round(per_edge, 3)
                    self._write_rebalanced_edge_weight(
                        edge_id=edge['edge_id'],
                        child_id=edge['child_id'],
                        old_weight=old_w,
                        new_weight=new_w,
                        reason=reason,
                    )
                    affected_edges.append({
                        'edge_id': edge['edge_id'],
                        'child_id': edge['child_id'],
                        'old_weight': old_w,
                        'new_weight': new_w,
                    })
            else:
                # Proportional distribution — keep each edge's relative
                # share of the adjustable pool, scaled to fill the
                # remainder budget.
                for edge in adjustable:
                    old_w = (
                        float(edge['relative_weight'])
                        if edge['relative_weight'] is not None
                        else 0.0
                    )
                    proportion = old_w / adjustable_current_total
                    new_w = round(proportion * remainder, 3)
                    self._write_rebalanced_edge_weight(
                        edge_id=edge['edge_id'],
                        child_id=edge['child_id'],
                        old_weight=old_w,
                        new_weight=new_w,
                        reason=reason,
                    )
                    affected_edges.append({
                        'edge_id': edge['edge_id'],
                        'child_id': edge['child_id'],
                        'old_weight': old_w,
                        'new_weight': new_w,
                    })

        if self.error_logger:
            self.error_logger.info(
                f"Rebalanced {len(affected_edges)} edges under parent {parent_id} "
                f"(skipped {len(skipped)}; anchored_total={anchored_total}%)",
                category=ErrorCategory.DATABASE,
            )

        return {
            'ok': True,
            'parent_id': parent_id,
            'affected_edges': affected_edges,
            'skipped': skipped,
        }

    def _write_rebalanced_edge_weight(
        self,
        *,
        edge_id: int,
        child_id: int,
        old_weight: float,
        new_weight: float,
        reason: Optional[str],
    ) -> None:
        """Internal helper: update one edge weight + log auto_recalculate history.

        Used exclusively by :meth:`rebalance_sibling_edge_weights`.
        Caller is expected to already hold a ``self.transaction()``.
        """
        self.execute(
            "UPDATE subject_edges "
            "SET relative_weight = ?, "
            "    weight_source = CASE "
            "        WHEN weight_source = 'official' THEN 'official' "
            "        WHEN weight_source = 'user_explicit' THEN 'user_explicit' "
            "        ELSE 'derived' "
            "    END, "
            "    updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (new_weight, edge_id),
        )
        # Mirror the value onto the legacy ``subject_nodes.relative_weight``
        # column so chip-render and other read paths that have not yet
        # been cut over to ``subject_edges`` see the rebalanced value.
        # Without this the audit log records the change but the UI keeps
        # displaying the pre-rebalance number until Stage 10 drops the
        # legacy column. Mirrors the pattern in
        # ``update_subject_relative_weight``.
        self.execute(
            "UPDATE subject_nodes "
            "SET relative_weight = ?, "
            "    weight_source = CASE "
            "        WHEN weight_source = 'official' THEN 'official' "
            "        ELSE 'derived' "
            "    END, "
            "    updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (new_weight, child_id),
        )
        try:
            self.execute(
                """
                INSERT INTO subject_node_weights (
                    subject_node_id, weight_value,
                    edited_by, edited_reason,
                    previous_weight, change_type, affected_siblings,
                    edge_id
                ) VALUES (?, ?, 'system', ?, ?, 'auto_recalculate', '[]', ?)
                """,
                (
                    child_id,
                    new_weight,
                    reason or 'Auto-rebalance',
                    old_weight,
                    edge_id,
                ),
            )
        except Exception:
            # Phase 2 history table may not exist in older test setups.
            pass

    def get_subjects_with_effective_weights(
        self,
        exam_context_id: int,
        include_children: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get all subjects with calculated effective weights.

        Effective weight = parent's midpoint x (relative_weight / 100)
        For top-level subjects, effective weight = midpoint of range

        Stage 5 extension (``WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``):
        each subject's ``weight`` dict now also carries ``q_typical`` —
        the integer question count for the subject under its parent path
        when the exam declares a ``length_typical``. When the exam is
        ``length_kind='unknown'``, ``q_typical`` is ``None``. Legacy
        callers that ignore the field continue to work unchanged.

        Args:
            exam_context_id: Exam context ID
            include_children: Include children in the hierarchy

        Returns:
            List of subject dicts with weight information:
            [
                {
                    'id': int,
                    'name': str,
                    'parent_id': int | None,
                    'level_type': str,
                    'weight': {
                        'absolute_low': float | None,
                        'absolute_high': float | None,
                        'relative': float | None,
                        'effective': float,
                        'effective_low': float,  # calculated from parent range
                        'effective_high': float,
                        'source': str,
                        'locked': bool,
                        'confidence': str,  # 'high', 'medium', 'low'
                        'q_typical': int | None  # Stage 5 — int when
                            # the exam has a length_typical, NULL when
                            # length_kind='unknown'.
                    },
                    'children': [...] if include_children
                },
                ...
            ]
        """
        # Get exam context
        exam_config = self.get_exam_context_config(exam_context_id)
        if not exam_config:
            raise ValueError(f"Exam context {exam_context_id} not found")

        exam_name = exam_config.exam_name

        # Stage 5 — read the exam length triple once so the recursive
        # walk can attach ``q_typical`` to every subject's weight dict.
        # When the exam is ``length_kind='unknown'`` (no planning
        # baseline), ``length_typical`` is ``None`` and ``q_typical``
        # degrades to ``None`` on every node.
        try:
            length_info = self.get_exam_length(exam_context_id)
            length_typical = length_info.get('typical')
        except Exception:
            # Exam-length triple is a newer column; older test fixtures
            # may not have it. Degrade gracefully — same behavior as
            # length_kind='unknown'.
            length_typical = None

        def calculate_effective_weights(
            parent_id: Optional[int],
            parent_effective_low: float = 100.0,
            parent_effective_high: float = 100.0,
            parent_q_typical: Optional[float] = None,
        ) -> List[Dict[str, Any]]:
            """Recursively calculate effective weights."""

            if parent_id is None:
                query = """
                    SELECT * FROM subject_nodes
                    WHERE exam_context = ? AND parent_id IS NULL AND status = 'active'
                    ORDER BY sort_order, name
                """
                params = (exam_name,)
            else:
                query = """
                    SELECT * FROM subject_nodes
                    WHERE exam_context = ? AND parent_id = ? AND status = 'active'
                    ORDER BY sort_order, name
                """
                params = (exam_name, parent_id)

            rows = self.fetchall(query, params)
            subjects = []

            for row in rows:
                abs_low = row['exam_weight_low']
                abs_high = row['exam_weight_high']
                relative = row['relative_weight']
                source = row['weight_source'] or 'user_defined'
                locked = bool(row['weight_locked'])

                # Calculate effective weights
                if abs_low is not None:
                    # Has absolute weight - use it directly
                    effective_low = abs_low
                    effective_high = abs_high if abs_high is not None else abs_low
                    effective = (effective_low + effective_high) / 2
                    confidence = 'high' if source == 'official' else 'medium'
                elif relative is not None:
                    # Has relative weight - calculate from parent
                    parent_midpoint = (parent_effective_low + parent_effective_high) / 2
                    effective = parent_midpoint * (relative / 100)
                    effective_low = parent_effective_low * (relative / 100)
                    effective_high = parent_effective_high * (relative / 100)
                    confidence = 'medium' if source in ('official', 'derived') else 'low'
                else:
                    # No weight information
                    effective = 0
                    effective_low = 0
                    effective_high = 0
                    confidence = 'none'

                # Stage 5 — compute q_typical for this node from the
                # effective midpoint when length_typical is known.
                # Root nodes (parent_id is None): the System-level
                # carries an `exam_weight_low/high` range or no info;
                # `effective` is the percentage of the whole exam.
                # Child nodes: derive from the parent's q_typical via
                # the per-edge relative_weight. We do NOT call the
                # Hamilton allocator here because this read-side path
                # is whole-tree and rounds each node independently
                # (per the float-then-round contract for the
                # node-keyed call site). The per-parent allocator is
                # available via :meth:`get_effective_question_counts`
                # for callers that need integer Hamilton output.
                if length_typical is None:
                    q_typical: Optional[int] = None
                elif parent_id is None:
                    # System level: percentage of the whole exam.
                    q_typical = int(round(effective * length_typical / 100.0))
                elif parent_q_typical is not None and relative is not None:
                    q_typical = int(round(parent_q_typical * (relative / 100.0)))
                elif parent_q_typical is not None and abs_low is not None:
                    # Child with explicit absolute weight (rare for
                    # non-root): use the midpoint as a percent of the
                    # parent's effective range. We treat the absolute
                    # weight as a slice of the whole exam.
                    q_typical = int(round(effective * length_typical / 100.0))
                else:
                    q_typical = None

                subject_dict = {
                    'id': row['id'],
                    'name': row['name'],
                    'parent_id': row['parent_id'],
                    'level_type': row['level_type'],
                    'weight': {
                        'absolute_low': abs_low,
                        'absolute_high': abs_high,
                        'relative': relative,
                        'effective': round(effective, 3),
                        'effective_low': round(effective_low, 3),
                        'effective_high': round(effective_high, 3),
                        'source': source,
                        'locked': locked,
                        'confidence': confidence,
                        'q_typical': q_typical,
                    }
                }

                if include_children:
                    # Recursively get children — thread q_typical down
                    # so child nodes can scale their share of the
                    # parent's question budget.
                    subject_dict['children'] = calculate_effective_weights(
                        row['id'],
                        effective_low if effective_low > 0 else parent_effective_low,
                        effective_high if effective_high > 0 else parent_effective_high,
                        q_typical if q_typical is not None else parent_q_typical,
                    )

                subjects.append(subject_dict)

            return subjects

        return calculate_effective_weights(None)

    # =====================================================================
    # Stage 5 — Question allocation read-side API
    # (WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 5")
    # =====================================================================

    def get_effective_question_counts(
        self,
        exam_context_id: int,
    ) -> List[Dict[str, Any]]:
        """Return per-edge effective question counts for an exam context.

        Walks ``subject_edges`` for every node belonging to the exam
        context (matched via ``subject_nodes.exam_context = exam_name``)
        and emits one row per edge. Each row carries:

        * ``edge_id``        — ``subject_edges.id``
        * ``child_id``       — ``subject_edges.child_id``
        * ``child_name``     — ``subject_nodes.name`` for the child
        * ``parent_id``      — ``subject_edges.parent_id``
        * ``parent_name``    — ``subject_nodes.name`` for the parent
        * ``parent_path``    — ``" / ".join(ancestor_names)`` from root
          down to the parent. Used for stable sort and UI display.
        * ``relative_weight`` — ``subject_edges.relative_weight`` (or
          ``None`` when uncategorized).
        * ``weight_source``  — ``subject_edges.weight_source``
        * ``is_anchor``      — bool
        * ``q_typical``      — question count under this edge when
          ``length_kind != 'unknown'``, else ``None``. Computed by
          walking down from the root System level via the per-parent
          Hamilton allocator so totals match the centralized
          :meth:`allocate_questions_hamilton` contract from Stage 1.
          When the exam is adaptive (``length_kind='range'``) this is
          a ``float`` (raw share, not integer-rounded); otherwise an
          ``int``.
        * ``q_low`` / ``q_high`` — integer question counts derived from
          the System-level ``exam_weight_low/high`` range (still on
          ``subject_nodes``, per design §2 Non-Goals) propagated through
          per-edge ``relative_weight``. ``None`` when length is unknown.
        * ``is_adaptive``    — bool. ``True`` iff the exam context's
          ``length_kind == 'range'`` (Stage 8). Stamped on every row
          (including the synthetic root rows) so downstream UI code
          can format ``q_typical`` as ``~26.4 q (planning estimate)``
          for adaptive exams and ``~26 q`` otherwise.

        Behavior under ``length_kind='unknown'``:
            ``q_typical``, ``q_low``, ``q_high`` are all ``None`` so the
            UI can render percentages without fabricating integer
            counts that the user would mistake for grounded numbers.
            ``is_adaptive`` is ``False`` (CAT semantics only apply
            when the planning baseline is known).

        Caching is intentionally **not** applied. WIMI hierarchies are
        <10K nodes and the recursive walk benchmarks under 10 ms per
        ``POLYHIERARCHY_MIGRATION.md`` §11. A cache would add
        invalidation complexity (every weight write would need to bust
        it) for negligible gain.

        Ordering: stable, by ``parent_path`` ASC, then ``sort_order``
        ASC, then ``edge_id`` ASC. Ties on parent_path are rare (only
        possible if two parents share the same lineage names), but the
        triple key guarantees a deterministic order suitable for
        analytics tables and regression assertions.

        Args:
            exam_context_id: Exam context whose subject tree is walked.

        Returns:
            A flat list of dicts as described above. Empty when the
            exam context has no subject edges yet.

        Raises:
            ValueError: When ``exam_context_id`` does not exist.
        """
        exam_config = self.get_exam_context_config(exam_context_id)
        if not exam_config:
            raise ValueError(f"Exam context {exam_context_id} not found")
        exam_name = exam_config.exam_name

        # Stage 4 — pull the length triple. When kind='unknown' the
        # ``typical`` slot is None and every q_* is None.
        try:
            length_info = self.get_exam_length(exam_context_id)
            length_typical = length_info.get('typical')
            length_kind = length_info.get('kind') or 'unknown'
        except Exception:
            length_typical = None
            length_kind = 'unknown'

        # Stage 8 — adaptive (CAT) exams have a planning baseline but
        # no fixed item count. The allocator should skip integer
        # rounding so downstream UI renders ``~26.4 q (planning
        # estimate)`` instead of fabricating precision the exam
        # doesn't have. The flag also rides on every returned row so
        # the bridge layer doesn't need to re-look-up the exam config.
        is_adaptive = length_kind == 'range'

        # Roots: nodes belonging to this exam_context with no incoming
        # edge. These are the System-level nodes that carry official
        # range semantics on ``subject_nodes.exam_weight_low/high``.
        root_rows = self.fetchall(
            """
            SELECT sn.id, sn.name, sn.sort_order,
                   sn.exam_weight_low, sn.exam_weight_high,
                   sn.relative_weight AS legacy_relative_weight
            FROM subject_nodes sn
            WHERE sn.exam_context = ?
              AND sn.status = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM subject_edges se WHERE se.child_id = sn.id
              )
            ORDER BY sn.sort_order ASC, sn.id ASC
            """,
            (exam_name,),
        )

        results: List[Dict[str, Any]] = []
        # Cycle guard: a defensive recursion-visit set on the path
        # (NOT global) so a node that legitimately appears under
        # multiple parents still gets fully walked under each one.
        # Cycles in subject_edges are blocked at write-time by
        # EdgesMixin.add_edge, but the guard is cheap insurance.
        def _walk(
            parent_id: int,
            parent_name: str,
            parent_path: str,
            parent_q_typical: Optional[int],
            parent_q_low: Optional[int],
            parent_q_high: Optional[int],
            ancestors: set,
        ) -> None:
            # Use the Stage 1 Hamilton allocator for the per-parent
            # integer distribution so q_typical totals match the
            # canonical writer contract.
            sibling_edges = self.get_sibling_edges(parent_id)
            if not sibling_edges:
                return

            if parent_q_typical is not None and parent_q_typical > 0:
                # Stage 1 contract: the allocator returns
                # {edge_id: int} summing to parent_q_typical (modulo
                # anchored-clamp edge cases).
                # Stage 8: pass ``is_adaptive`` so adaptive (CAT)
                # exams skip integer rounding and return float shares.
                # In adaptive mode the parent_q_typical is a float
                # propagated from the root; we forward it as-is so
                # precision is preserved end-to-end. The allocator's
                # adaptive branch coerces to float internally.
                allocations = self.allocate_questions_hamilton(
                    parent_id,
                    parent_q_typical if is_adaptive else int(parent_q_typical),
                    is_adaptive=is_adaptive,
                )
            else:
                allocations = {edge['edge_id']: None for edge in sibling_edges}

            for edge in sibling_edges:
                edge_id = edge['edge_id']
                child_id = edge['child_id']
                child_name = edge['child_name']
                rw = edge['relative_weight']

                # Range propagation: q_low/q_high scale by per-edge
                # relative_weight (falling back to 0 when NULL so we
                # don't propagate a fictional share).
                if (
                    parent_q_low is not None
                    and parent_q_high is not None
                    and rw is not None
                ):
                    edge_q_low = int(math.floor(parent_q_low * rw / 100.0))
                    edge_q_high = int(math.ceil(parent_q_high * rw / 100.0))
                elif (
                    parent_q_low is not None
                    and parent_q_high is not None
                    and rw is None
                ):
                    # Uncategorized edge — no information to scale by.
                    edge_q_low = None
                    edge_q_high = None
                else:
                    edge_q_low = None
                    edge_q_high = None

                edge_q_typical = allocations.get(edge_id)

                path = f"{parent_path} / {child_name}" if parent_path else parent_name

                results.append({
                    'edge_id': edge_id,
                    'child_id': child_id,
                    'child_name': child_name,
                    'parent_id': parent_id,
                    'parent_name': parent_name,
                    'parent_path': parent_path,
                    'relative_weight': rw,
                    'weight_source': edge['weight_source'],
                    'is_anchor': bool(edge['is_anchor']),
                    'q_typical': edge_q_typical,
                    'q_low': edge_q_low,
                    'q_high': edge_q_high,
                    # Stage 8 — adaptive flag rides on every row so
                    # the bridge layer doesn't need a second lookup
                    # and the UI can pick the right q_typical formatter
                    # (``~26.4 q (planning estimate)`` vs ``~26 q``).
                    'is_adaptive': is_adaptive,
                })

                # Descend only if we haven't visited this node on the
                # current path (defensive cycle guard).
                if child_id in ancestors:
                    continue
                _walk(
                    child_id,
                    child_name,
                    path,
                    edge_q_typical,
                    edge_q_low,
                    edge_q_high,
                    ancestors | {child_id},
                )

        for root in root_rows:
            root_id = root['id']
            root_name = root['name']

            # Compute the root's q_typical / q_low / q_high from the
            # System-level range columns (still on subject_nodes per
            # design §2 Non-Goals).
            #
            # Stage 8: in adaptive (CAT) mode the typical is a float
            # so the float precision propagates down to children via
            # the allocator's adaptive branch. q_low/q_high remain
            # integers because they're floor/ceil of the official
            # range — that's the user-visible "best case / worst
            # case" question count and rounding it doesn't introduce
            # fake precision.
            abs_low = root['exam_weight_low']
            abs_high = root['exam_weight_high']
            if length_typical is None:
                root_q_typical: Optional[Any] = None
                root_q_low: Optional[int] = None
                root_q_high: Optional[int] = None
            elif abs_low is not None:
                root_q_low = int(math.floor(abs_low * length_typical / 100.0))
                if abs_high is not None:
                    root_q_high = int(math.ceil(abs_high * length_typical / 100.0))
                else:
                    root_q_high = root_q_low
                # Typical = midpoint, integer-rounded for non-adaptive
                # / float-preserved for adaptive so the chip can show
                # ``~84.0 q (planning estimate)`` for a System under a
                # CAT exam.
                mid = (abs_low + (abs_high if abs_high is not None else abs_low)) / 2.0
                root_q_typical_raw = mid * length_typical / 100.0
                root_q_typical = (
                    root_q_typical_raw if is_adaptive
                    else int(round(root_q_typical_raw))
                )
            else:
                # No range info on root. Some user-defined exams set
                # everything via the relative-weight chain only; in
                # that case the root's effective share is 100% of the
                # exam (a single system) — but with multiple systems
                # and no range info, we have no signal. Fall back to
                # the whole-exam budget so child allocations still
                # work; the UI clearly shows the missing data.
                root_q_typical = (
                    float(length_typical) if is_adaptive else length_typical
                )
                root_q_low = length_typical
                root_q_high = length_typical

            # Emit a synthetic row for the root System node itself so
            # the UI chip-stamping code (which keys on ``child_id``)
            # finds a ``q_typical`` for the System chips visible at
            # the top of the tree. Roots have no incoming edge, so we
            # use ``edge_id=None`` and ``parent_id=None`` as the
            # convention for "this is a root, not an edge row".
            results.append({
                'edge_id': None,
                'child_id': root_id,
                'child_name': root_name,
                'parent_id': None,
                'parent_name': None,
                'parent_path': '',
                'relative_weight': None,
                'weight_source': 'official',
                'is_anchor': False,
                'q_typical': root_q_typical,
                'q_low': root_q_low,
                'q_high': root_q_high,
                # Stage 8 — root rows also carry the adaptive flag so
                # downstream UI doesn't need a side-channel lookup.
                'is_adaptive': is_adaptive,
            })

            _walk(
                root_id,
                root_name,
                '',
                root_q_typical,
                root_q_low,
                root_q_high,
                ancestors={root_id},
            )

        # Stable sort: parent_path → child sort_order is already the
        # walk order, but assert the contract for callers that depend
        # on it. Root rows (edge_id=None) sort first within their
        # empty parent_path bucket via the explicit None-handling key.
        results.sort(key=lambda r: (r['parent_path'], r['edge_id'] is not None, r['edge_id'] or 0))
        return results

    def get_weight_config_for_exam(
        self,
        exam_context_id: int
    ) -> Dict[str, Any]:
        """
        Get weight configuration for an exam context.

        Args:
            exam_context_id: Exam context ID

        Returns:
            Dictionary with weight configuration:
            {
                'weight_mode': str,  # 'official_ranges', 'official_fixed', 'user_defined'
                'has_official_weights': bool,
                'official_weight_count': int,
                'user_weight_count': int,
                'source_name': str | None,
                'source_url': str | None,
                'total_weight_sum': float,
                'weight_complete': bool
            }
        """
        # Get exam context
        exam_config = self.get_exam_context_config(exam_context_id)
        if not exam_config:
            raise ValueError(f"Exam context {exam_context_id} not found")

        exam_name = exam_config.exam_name

        # Count weights by source
        counts = self.fetchone("""
            SELECT
                SUM(CASE WHEN weight_source = 'official' THEN 1 ELSE 0 END) as official_count,
                SUM(CASE WHEN weight_source != 'official' THEN 1 ELSE 0 END) as user_count,
                SUM(CASE WHEN exam_weight_low IS NOT NULL THEN 1 ELSE 0 END) as has_absolute,
                SUM(CASE WHEN exam_weight_low != exam_weight_high THEN 1 ELSE 0 END) as has_range
            FROM subject_nodes
            WHERE exam_context = ? AND parent_id IS NULL AND status = 'active'
        """, (exam_name,))

        official_count = counts['official_count'] or 0
        user_count = counts['user_count'] or 0
        has_ranges = (counts['has_range'] or 0) > 0

        # Determine weight mode
        if official_count > 0:
            weight_mode = 'official_ranges' if has_ranges else 'official_fixed'
        else:
            weight_mode = 'user_defined'

        # Get source info from first official weight
        source_info = self.fetchone("""
            SELECT exam_source
            FROM subject_nodes
            WHERE exam_context = ? AND weight_source = 'official' AND status = 'active'
            LIMIT 1
        """, (exam_name,))

        # Calculate total weight
        weight_sum = self.fetchone("""
            SELECT SUM((COALESCE(exam_weight_low, 0) + COALESCE(exam_weight_high, exam_weight_low, 0)) / 2.0) as total
            FROM subject_nodes
            WHERE exam_context = ? AND parent_id IS NULL AND status = 'active'
        """, (exam_name,))

        total = weight_sum['total'] or 0.0

        return {
            'weight_mode': weight_mode,
            'has_official_weights': official_count > 0,
            'official_weight_count': official_count,
            'user_weight_count': user_count,
            'source_name': source_info['exam_source'] if source_info else None,
            'source_url': None,  # Could be stored in exam_contexts weight_validation_rules
            'total_weight_sum': round(total, 1),
            'weight_complete': abs(total - 100.0) < 1.0  # Within 1% of 100
        }

    def create_subject_node_with_weight(
        self,
        exam_context: str,
        name: str,
        level_type: str,
        parent_id: Optional[int] = None,
        exam_weight_low: Optional[float] = None,
        exam_weight_high: Optional[float] = None,
        relative_weight: Optional[float] = None,
        weight_source: str = 'user_defined',
        weight_locked: bool = False,
        exam_source: Optional[str] = None,
        sort_order: int = 1,
        outline_type: str = 'content',
        dimension_id: Optional[int] = None
    ) -> SubjectNode:
        """
        Create a subject node with full weight configuration.

        This is an enhanced version of create_subject_node that supports
        the hybrid weight system and multi-dimensional hierarchies.

        Args:
            exam_context: Exam code (e.g., 'USMLE Step 1')
            name: Node name
            level_type: Hierarchy level (e.g., 'System', 'Topic')
            parent_id: Parent node ID for hierarchy
            exam_weight_low: Lower bound of absolute weight
            exam_weight_high: Upper bound of absolute weight
            relative_weight: Relative weight within parent (0-100)
            weight_source: Source of weight ('official', 'derived', 'user_estimate', 'user_defined')
            weight_locked: Whether weight can be edited
            exam_source: Source document for weights
            sort_order: Display order
            outline_type: Type of outline
            dimension_id: Dimension ID for multi-dimensional exams (NULL for simple exams)

        Returns:
            Created SubjectNode object
        """
        from ..exceptions import WeightValidationError

        # Validate weight source
        valid_sources = ('official', 'derived', 'user_estimate', 'user_defined')
        if weight_source not in valid_sources:
            raise WeightValidationError(f"Invalid weight_source: {weight_source}. Must be one of {valid_sources}")

        # Validate weights
        if exam_weight_low is not None and exam_weight_low < 0:
            raise WeightValidationError("exam_weight_low cannot be negative")
        if exam_weight_high is not None and exam_weight_high < 0:
            raise WeightValidationError("exam_weight_high cannot be negative")
        if relative_weight is not None and (relative_weight < 0 or relative_weight > 100):
            raise WeightValidationError("relative_weight must be between 0 and 100")

        # If only low is provided, set high to same value
        if exam_weight_low is not None and exam_weight_high is None:
            exam_weight_high = exam_weight_low

        # Check for duplicates
        if parent_id is None:
            existing = self.fetchone(
                "SELECT id FROM subject_nodes WHERE exam_context = ? AND name = ? AND parent_id IS NULL AND status = 'active'",
                (exam_context, name)
            )
        else:
            existing = self.fetchone(
                "SELECT id FROM subject_nodes WHERE exam_context = ? AND name = ? AND parent_id = ? AND status = 'active'",
                (exam_context, name, parent_id)
            )

        if existing:
            raise SubjectNodeError(f"Subject node already exists: {exam_context}/{name}")

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO subject_nodes (
                        exam_context, name, parent_id, level_type, sort_order,
                        exam_weight_low, exam_weight_high, exam_source,
                        relative_weight, weight_source, weight_locked,
                        outline_type, dimension_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """, (
                    exam_context, name, parent_id, level_type, sort_order,
                    exam_weight_low, exam_weight_high, exam_source,
                    relative_weight, weight_source, weight_locked,
                    outline_type, dimension_id
                ))

                node_id = cursor.lastrowid

                # Polyhierarchy: mirror create_subject_node by writing a
                # primary subject_edges row whenever parent_id is set, so
                # the edge-based traversal helpers (and the polyhierarchy-
                # aware get_subject_hierarchy) see this parent-child
                # relationship. Guarded against legacy DBs that pre-date
                # the m004 migration.
                if parent_id is not None:
                    try:
                        self.execute(
                            """
                            INSERT OR IGNORE INTO subject_edges
                                (parent_id, child_id, is_primary, display_order)
                            VALUES (?, ?, TRUE, ?)
                            """,
                            (parent_id, node_id, sort_order or 0),
                        )
                    except Exception:
                        pass

                if self.error_logger:
                    self.error_logger.debug(
                        f"Created subject node with weight: {name} (ID: {node_id})",
                        category=ErrorCategory.DATABASE
                    )

                result_node = self.get_subject_node(node_id)

                # Graph dual-write
                full_path = self._build_subject_path(node_id)
                _exam_context = exam_context
                _parent_id = parent_id
                _dimension_id = dimension_id
                _node_id = node_id

                def _graph_write():
                    self._graph_execute(
                        "MERGE (s:Subject {sqlite_id: $id}) "
                        "SET s.name = $name, s.level_type = $level_type, s.full_path = $path",
                        {"id": _node_id, "name": name, "level_type": level_type, "path": full_path}
                    )
                    if _parent_id:
                        self._graph_execute(
                            "MATCH (p:Subject {sqlite_id: $pid}), (s:Subject {sqlite_id: $sid}) "
                            "MERGE (p)-[:HAS_CHILD]->(s)",
                            {"pid": _parent_id, "sid": _node_id}
                        )
                    else:
                        ec_row = self.fetchone(
                            "SELECT id FROM exam_contexts WHERE exam_name = ?",
                            (_exam_context,)
                        )
                        if ec_row:
                            self._graph_execute(
                                "MATCH (ec:ExamContext {sqlite_id: $ecid}), (s:Subject {sqlite_id: $sid}) "
                                "MERGE (ec)-[:ROOT_OF]->(s)",
                                {"ecid": ec_row['id'], "sid": _node_id}
                            )
                    if _dimension_id:
                        self._graph_execute(
                            "MATCH (s:Subject {sqlite_id: $sid}), (d:Dimension {sqlite_id: $did}) "
                            "MERGE (s)-[:BELONGS_TO]->(d)",
                            {"sid": _node_id, "did": _dimension_id}
                        )
                self._dual_write_graph("create_subject_node_with_weight", _graph_write)

                return result_node

        except DatabaseIntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise SubjectNodeError(
                    f"Subject node already exists: {exam_context}/{name}"
                ) from e
            raise

    # =====================================================================
    # Stage 7 — Interval-Rounding Feasibility Checker
    # (docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md §"Stage 7";
    #  docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md §3.5)
    #
    # Save-then-warn: backend never refuses a write. These methods are
    # pure read-side validators that produce a per-parent report
    # describing whether the children's [low, high] ranges fit inside
    # the parent's range — including the rounding-class infeasibility
    # case (Σ⌈child_lo·N/100⌉ > ⌊parent_hi·N/100⌋) where integer
    # rounding makes the configuration mathematically unsatisfiable.
    #
    # Status taxonomy:
    #   * 'ok'          — children [low, high] fit cleanly in parent's range
    #   * 'under'       — Σ child highs < parent low (room for more)
    #   * 'over'        — Σ child lows > parent high (over-claimed)
    #   * 'infeasible'  — Σ⌈child_lo·N/100⌉ > ⌊parent_hi·N/100⌋
    #                     (rounding-class violation)
    #
    # Appended at the end of the mixin to dodge merge conflicts with the
    # parallel Stage 8 (CAT) work that modifies allocate_questions_hamilton
    # and get_effective_question_counts above.
    # =====================================================================

    def _resolve_parent_q_range(
        self,
        parent_id: int,
        length_typical: int,
    ) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        """Return ``(parent_low_q, parent_high_q, parent_typical_q)`` for a parent.

        Helper for :meth:`validate_hierarchy_feasibility`. The parent's
        question range is derived in one of two ways:

        * **System (root) parents**: use ``subject_nodes.exam_weight_low``
          and ``exam_weight_high`` scaled by ``length_typical`` — these
          are the official-outline percentage ranges that stay on the
          node per design §2 Non-Goals.
        * **Non-root parents**: walk the effective-question-counts table
          produced by :meth:`get_effective_question_counts` (which is
          already polyhierarchy-aware and Hamilton-consistent) and pick
          the row matching ``parent_id``. ``q_low``/``q_high``/
          ``q_typical`` come straight from that row.

        When the parent's range information is unavailable (no exam
        weight set, no edge weights propagated yet), returns
        ``(None, None, None)``. The caller treats that as ``'ok'``
        because there's no constraint to violate.
        """
        # System-level: read the absolute range straight off subject_nodes.
        node_row = self.fetchone(
            """
            SELECT exam_weight_low, exam_weight_high
            FROM subject_nodes
            WHERE id = ?
            """,
            (parent_id,),
        )
        if node_row is None:
            return (None, None, None)

        is_root = self.fetchone(
            "SELECT 1 FROM subject_edges WHERE child_id = ? LIMIT 1",
            (parent_id,),
        ) is None

        if (
            is_root
            and node_row['exam_weight_low'] is not None
            and node_row['exam_weight_high'] is not None
        ):
            plow_pct = float(node_row['exam_weight_low'])
            phigh_pct = float(node_row['exam_weight_high'])
            parent_low_q = int(math.floor(plow_pct * length_typical / 100.0))
            parent_high_q = int(math.floor(phigh_pct * length_typical / 100.0))
            # Typical = midpoint, rounded to nearest whole question
            # (same convention used by get_effective_question_counts).
            mid_pct = (plow_pct + phigh_pct) / 2.0
            parent_typical_q = int(round(mid_pct * length_typical / 100.0))
            return (parent_low_q, parent_high_q, parent_typical_q)

        # Non-root: defer to the canonical walker. Picks the row for the
        # parent under any incoming-edge context (polyhierarchy nodes
        # have multiple rows; pick the largest for the most generous
        # bound — matches _compute_parent_q_budget's chip-stamping
        # convention).
        exam_row = self.fetchone(
            """
            SELECT ec.id AS exam_context_id
            FROM subject_nodes sn
            JOIN exam_contexts ec ON ec.exam_name = sn.exam_context
            WHERE sn.id = ?
            """,
            (parent_id,),
        )
        if exam_row is None:
            return (None, None, None)

        try:
            counts = self.get_effective_question_counts(
                exam_row['exam_context_id']
            )
        except Exception:
            return (None, None, None)

        best_low: Optional[int] = None
        best_high: Optional[int] = None
        best_typical: Optional[int] = None
        for row in counts:
            if row['child_id'] != parent_id:
                continue
            q_low = row.get('q_low')
            q_high = row.get('q_high')
            q_typical = row.get('q_typical')
            if q_typical is not None and (best_typical is None or q_typical > best_typical):
                best_typical = q_typical
            if q_low is not None and (best_low is None or q_low > best_low):
                best_low = q_low
            if q_high is not None and (best_high is None or q_high > best_high):
                best_high = q_high

        return (best_low, best_high, best_typical)

    def validate_hierarchy_feasibility(
        self,
        parent_id: int,
        length_typical: int,
    ) -> Dict[str, Any]:
        """Validate that a parent's child weights are feasible.

        Stage 7 of the Hierarchical Weight Allocation Implementation
        Plan. Pure read-side validator — never writes, never refuses.
        Produces a structured report the UI consumes to render the
        soft-warning badge in the weight modal (and the warning dots
        on tree rows whose parent is non-``'ok'``).

        Math:

        * ``parent_low_q  = ⌊parent_low_pct  · N / 100⌋``
        * ``parent_high_q = ⌊parent_high_pct · N / 100⌋``
        * ``child_low_q[i]  = ⌈child_low_pct[i]  · N / 100⌉``
        * ``child_high_q[i] = ⌈child_high_pct[i] · N / 100⌉``
        * Outward rounding (floor on parent caps, ceil on child caps)
          *widens* intervals rather than over-constraining them, per
          design §3.5.

        Status decision tree (most-actionable first):

        1. ``Σ child_low_pct > parent_high_pct`` ⇒ ``'over'`` — the
           percentages alone over-claim. Reported first because the
           user's fix is "reduce a weight", which is simpler than the
           rounding-class advice. (Note: when percentages over-sum, the
           integer rounding class is also violated, but the percentage
           message is the more actionable one.)
        2. ``Σ child_low_q > parent_high_q`` ⇒ ``'infeasible'`` —
           percentages COULD fit but ceiling-rounded q minimums sum
           past the floor-rounded q ceiling. The genuine
           "round more aggressively" case.
        3. ``Σ child_high_pct < parent_low_pct`` ⇒ ``'under'`` —
           children sum to less than the parent's floor.
        4. Otherwise ⇒ ``'ok'``.

        Args:
            parent_id: ``subject_nodes.id`` whose outgoing edges to
                validate.
            length_typical: Exam length integer used for q conversion.
                When ``length_typical <= 0`` the rounding-class check
                is skipped and the status is decided on percentages
                alone.

        Returns:
            ``{
                'status': 'ok' | 'under' | 'over' | 'infeasible',
                'parent_low_q':  int | None,
                'parent_high_q': int | None,
                'children_low_sum_q':  int,
                'children_high_sum_q': int,
                'children_low_sum_pct':  float,
                'children_high_sum_pct': float,
                'violators': [
                    {'edge_id', 'child_id', 'child_name', 'reason'}, ...
                ]
            }``
        """
        sibling_edges = self.get_sibling_edges(parent_id)
        if not sibling_edges:
            return {
                'status': 'ok',
                'parent_low_q': None,
                'parent_high_q': None,
                'children_low_sum_q': 0,
                'children_high_sum_q': 0,
                'children_low_sum_pct': 0.0,
                'children_high_sum_pct': 0.0,
                'violators': [],
            }

        # Resolve parent's q range. When unavailable (root with no
        # exam_weight_*, or orphaned non-root with no propagation),
        # collapse to 'ok' — there's no constraint to violate.
        parent_low_q, parent_high_q, _parent_typical_q = self._resolve_parent_q_range(
            parent_id, length_typical
        )

        # Each child's percent low/high. We read absolute % ranges from
        # subject_nodes.exam_weight_low/high when set; otherwise we
        # treat the edge's relative_weight as a point estimate (low =
        # high = rw). NULL relative_weight + NULL ranges ⇒ 0 (no signal).
        child_data: List[Dict[str, Any]] = []
        for edge in sibling_edges:
            child_row = self.fetchone(
                "SELECT exam_weight_low, exam_weight_high FROM subject_nodes WHERE id = ?",
                (edge['child_id'],),
            )
            cn_low_pct = child_row['exam_weight_low'] if child_row else None
            cn_high_pct = child_row['exam_weight_high'] if child_row else None
            rw = edge['relative_weight']

            if cn_low_pct is not None and cn_high_pct is not None:
                low_pct = float(cn_low_pct)
                high_pct = float(cn_high_pct)
            elif rw is not None:
                low_pct = float(rw)
                high_pct = float(rw)
            else:
                low_pct = 0.0
                high_pct = 0.0

            child_data.append({
                'edge_id': edge['edge_id'],
                'child_id': edge['child_id'],
                'child_name': edge['child_name'],
                'low_pct': low_pct,
                'high_pct': high_pct,
            })

        children_low_sum_pct = sum(c['low_pct'] for c in child_data)
        children_high_sum_pct = sum(c['high_pct'] for c in child_data)

        # Convert children's bounds to integer q (ceil outward).
        N = length_typical if length_typical and length_typical > 0 else 0
        children_low_sum_q = 0
        children_high_sum_q = 0
        if N > 0:
            for c in child_data:
                c['low_q'] = int(math.ceil(c['low_pct'] * N / 100.0))
                c['high_q'] = int(math.ceil(c['high_pct'] * N / 100.0))
                children_low_sum_q += c['low_q']
                children_high_sum_q += c['high_q']
        else:
            for c in child_data:
                c['low_q'] = 0
                c['high_q'] = 0

        # Resolve parent's percent range too — needed for the over/under
        # checks that don't depend on integer rounding.
        parent_row = self.fetchone(
            """
            SELECT exam_weight_low, exam_weight_high
            FROM subject_nodes
            WHERE id = ?
            """,
            (parent_id,),
        )
        if parent_row:
            parent_low_pct = (
                float(parent_row['exam_weight_low'])
                if parent_row['exam_weight_low'] is not None
                else None
            )
            parent_high_pct = (
                float(parent_row['exam_weight_high'])
                if parent_row['exam_weight_high'] is not None
                else None
            )
        else:
            parent_low_pct = None
            parent_high_pct = None

        violators: List[Dict[str, Any]] = []
        status = 'ok'

        # Decision precedence:
        #
        #   1. 'over'       — percentage sum exceeds parent's high. The
        #                     simple "you've over-claimed" case; reported
        #                     BEFORE 'infeasible' so the user gets
        #                     actionable copy ("reduce a weight") instead
        #                     of the rounding-class message ("round more
        #                     aggressively"). When percentages sum over,
        #                     the integer rounding class is *also*
        #                     violated, but the percentage-level fix is
        #                     what the user needs first.
        #   2. 'infeasible' — rounding-class: percentages COULD fit
        #                     (each child's low pct ≤ parent high), but
        #                     ceiling-rounded q minimums sum past the
        #                     floor-rounded q ceiling. The genuine
        #                     "fix needs rounding aggression, not
        #                     weight reduction" case from design §3.5.
        #   3. 'under'      — Σ children's high pct < parent's low pct.
        #                     Room for more children / heavier weights.
        #   4. 'ok'         — children fit.

        # --- over (percentage sum exceeds parent high) -------------------
        if (
            parent_high_pct is not None
            and children_low_sum_pct > parent_high_pct
        ):
            status = 'over'
            # Violators: children whose low_pct alone contributes to the
            # overrun. List those whose individual low > 0 (all
            # contributors).
            for c in child_data:
                if c['low_pct'] > 0:
                    violators.append({
                        'edge_id': c['edge_id'],
                        'child_id': c['child_id'],
                        'child_name': c['child_name'],
                        'reason': (
                            f"low={c['low_pct']:.1f}% contributes to the "
                            f"over-allocated sum of "
                            f"{children_low_sum_pct:.1f}% > "
                            f"parent high {parent_high_pct:.1f}%"
                        ),
                    })

        # --- infeasibility (rounding-class) -----------------------------
        # Only checkable when we have N and a parent q ceiling.
        elif (
            N > 0
            and parent_high_q is not None
            and children_low_sum_q > parent_high_q
        ):
            status = 'infeasible'
            # Violators: children whose ceiling-rounded mins materially
            # contribute. Use the simple "child_low_q > 0" filter so the
            # UI can highlight every contributing edge; this keeps the
            # report actionable without an arbitrary threshold.
            for c in child_data:
                if c['low_q'] > 0:
                    violators.append({
                        'edge_id': c['edge_id'],
                        'child_id': c['child_id'],
                        'child_name': c['child_name'],
                        'reason': (
                            f"low={c['low_pct']:.1f}% → ceil({c['low_pct']}·"
                            f"{N}/100) = {c['low_q']} q contributes to the "
                            f"infeasible sum of {children_low_sum_q} q > "
                            f"parent high {parent_high_q} q"
                        ),
                    })

        # --- under (children sum less than parent low) -------------------
        elif (
            parent_low_pct is not None
            and children_high_sum_pct < parent_low_pct
        ):
            status = 'under'
            # No specific violators per spec — under-allocation is a
            # parent-level "add more children" message, not a
            # per-child action.
            violators = []

        return {
            'status': status,
            'parent_low_q': parent_low_q,
            'parent_high_q': parent_high_q,
            'children_low_sum_q': children_low_sum_q,
            'children_high_sum_q': children_high_sum_q,
            'children_low_sum_pct': children_low_sum_pct,
            'children_high_sum_pct': children_high_sum_pct,
            'violators': violators,
        }

    def validate_hierarchy_feasibility_recursive(
        self,
        exam_context_id: int,
    ) -> Dict[int, Dict[str, Any]]:
        """Walk every parent in the exam's subject tree and produce a feasibility report.

        Stage 7 companion to :meth:`validate_hierarchy_feasibility`.
        Used by the tree editor to show warning dots on every parent
        row whose status is non-``'ok'``.

        Args:
            exam_context_id: Target exam context. The walk enumerates
                every ``subject_node`` belonging to this exam (matched
                via ``subject_nodes.exam_context = exam_name``) that has
                at least one outgoing edge — i.e. every node that is
                someone's parent.

        Returns:
            ``{parent_id: <feasibility-report-dict>, ...}`` — one entry
            per parent. Empty when the exam context has no subject
            edges. When ``length_kind='unknown'`` every parent's status
            is ``'ok'`` (no integer feasibility check possible without a
            length budget) but the percentage-only over/under checks
            still apply.
        """
        exam_config = self.get_exam_context_config(exam_context_id)
        if not exam_config:
            raise ValueError(f"Exam context {exam_context_id} not found")
        exam_name = exam_config.exam_name

        try:
            length_info = self.get_exam_length(exam_context_id)
            length_typical = length_info.get('typical')
        except Exception:
            length_typical = None

        # If length is unknown, we still walk and report the percentage
        # over/under cases — the integer feasibility class is just
        # skipped (length_typical=0 in the helper coerces N=0).
        effective_length = int(length_typical) if length_typical else 0

        # Every distinct parent_id in subject_edges whose parent_node
        # belongs to this exam. Includes both root Systems (whose
        # parent_id appears in edges as a parent) and intermediate
        # parents.
        parent_rows = self.fetchall(
            """
            SELECT DISTINCT se.parent_id AS parent_id
            FROM subject_edges se
            JOIN subject_nodes sn ON sn.id = se.parent_id
            WHERE sn.exam_context = ?
              AND sn.status = 'active'
            """,
            (exam_name,),
        )

        reports: Dict[int, Dict[str, Any]] = {}
        for row in parent_rows:
            pid = row['parent_id']
            try:
                reports[pid] = self.validate_hierarchy_feasibility(
                    pid, effective_length
                )
            except Exception as e:
                # Defensive — a malformed parent shouldn't poison the
                # whole tree's report. Log via the error logger when
                # available; surface a stub 'ok' so the UI doesn't show
                # a phantom warning dot on a parent we couldn't
                # validate.
                if getattr(self, 'error_logger', None):
                    self.error_logger.warning(
                        f"validate_hierarchy_feasibility failed for parent "
                        f"{pid}: {e}",
                        category=ErrorCategory.DATABASE,
                    )
                reports[pid] = {
                    'status': 'ok',
                    'parent_low_q': None,
                    'parent_high_q': None,
                    'children_low_sum_q': 0,
                    'children_high_sum_q': 0,
                    'children_low_sum_pct': 0.0,
                    'children_high_sum_pct': 0.0,
                    'violators': [],
                }
        return reports

    def ensure_hybrid_weight_columns(self) -> bool:
        """
        Ensure the hybrid weight columns exist in subject_nodes table.

        This method checks for and adds the new columns if they don't exist,
        supporting migration of existing databases.

        Returns:
            True if columns were added, False if they already existed
        """
        columns = self.fetchall("PRAGMA table_info(subject_nodes)")
        column_names = {col['name'] for col in columns}

        added_columns = False

        if 'relative_weight' not in column_names:
            self.execute("""
                ALTER TABLE subject_nodes ADD COLUMN relative_weight REAL
                CHECK (relative_weight IS NULL OR (relative_weight >= 0 AND relative_weight <= 100))
            """)
            added_columns = True

        if 'weight_source' not in column_names:
            self.execute("""
                ALTER TABLE subject_nodes ADD COLUMN weight_source VARCHAR(50)
                DEFAULT 'user_defined'
            """)
            # SQLite doesn't support adding CHECK constraint via ALTER TABLE
            # The constraint is enforced at the application level
            added_columns = True

        if 'weight_locked' not in column_names:
            self.execute("""
                ALTER TABLE subject_nodes ADD COLUMN weight_locked BOOLEAN
                DEFAULT FALSE
            """)
            added_columns = True

        if added_columns:
            self.conn.commit()

            # Set existing weights as user_defined
            self.execute("""
                UPDATE subject_nodes
                SET weight_source = 'user_defined', weight_locked = FALSE
                WHERE weight_source IS NULL
            """)
            self.conn.commit()

            if self.error_logger:
                self.error_logger.info(
                    f"Added hybrid weight columns to subject_nodes for user {self.username}",
                    category=ErrorCategory.DATABASE
                )

        return added_columns
