"""WIMI Question entry database operations."""

import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, date
from ..base_db import DatabaseIntegrityError
from ..exceptions import ValidationError
from ..models import SubjectNode, Tag
from app_logging import ErrorCategory

logger = logging.getLogger('wimi.graph')


class EntriesMixin:
    """Mixin for question entry CRUD and query operations."""

    VALID_MISTAKE_CATEGORIES = {
        'knowledge_gap', 'misread_question', 'silly_mistake', 'time_pressure',
        'misunderstanding', 'memory_failure', 'calculation_error', 'wrong_approach',
        'incomplete_solution', 'anxiety_related', 'second_guessing',
        'elimination_error', 'careless_mistake', 'focus_problem',
        'fatigue_related', 'poor_prioritization', 'wrong_guess_strategy',
        'test_strategy_error'
    }

    VALID_ASSIGNMENT_TYPES = {'primary', 'secondary'}

    def create_question_entry(
        self,
        review_session_id: int,
        user_answer: str,
        correct_answer: str,
        question_id: Optional[str] = None,
        perceived_difficulty: Optional[int] = None,
        time_spent_seconds: Optional[int] = None,
        reflection: Optional[str] = None,
        explanation: Optional[str] = None,
        notes: Optional[str] = None,
        reflection_json: Optional[str] = None,
        explanation_json: Optional[str] = None,
        notes_json: Optional[str] = None,
        primary_subject_ids: Optional[List[int]] = None,
        secondary_subject_ids: Optional[List[int]] = None,
        tag_ids: Optional[List[int]] = None
    ) -> 'QuestionEntry':
        """
        Create a new question entry.

        Args:
            review_session_id: ID of the review session
            user_answer: The user's answer
            correct_answer: The correct answer
            question_id: Optional question reference ID
            perceived_difficulty: Optional difficulty rating (1-5)
            time_spent_seconds: Optional time spent in seconds
            reflection: Optional metacognitive reflection (HTML/plain text)
            explanation: Optional explanation of correct answer (HTML/plain text)
            notes: Optional additional notes (HTML/plain text)
            reflection_json: Optional Quill Delta JSON for reflection
            explanation_json: Optional Quill Delta JSON for explanation
            notes_json: Optional Quill Delta JSON for notes
            primary_subject_ids: List of primary subject node IDs
            secondary_subject_ids: List of secondary subject node IDs
            tag_ids: List of tag IDs

        Returns:
            QuestionEntry object
        """
        from ..models import QuestionEntry
        from ..exceptions import QuestionEntryError, ReviewSessionNotFoundError

        self._ensure_phase4_schema()

        # Validate session exists
        session = self.get_review_session(review_session_id)
        if not session:
            raise ReviewSessionNotFoundError(f"Review session {review_session_id} not found")

        # Validate difficulty
        if perceived_difficulty is not None and not (1 <= perceived_difficulty <= 5):
            raise ValidationError("Perceived difficulty must be between 1 and 5")

        # Determine entry order
        row = self.fetchone("""
            SELECT COALESCE(MAX(entry_order), 0) + 1 as next_order
            FROM question_entries WHERE review_session_id = ?
        """, (review_session_id,))
        entry_order = row['next_order']

        # Determine if this is a draft
        is_draft = not (reflection and explanation and (primary_subject_ids and len(primary_subject_ids) > 0))
        missing_fields = []
        if not reflection:
            missing_fields.append('reflection')
        if not explanation:
            missing_fields.append('explanation')
        if not primary_subject_ids:
            missing_fields.append('primary_subjects')

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO question_entries (
                        review_session_id, entry_order, question_id,
                        user_answer, correct_answer, perceived_difficulty,
                        time_spent_seconds, reflection, explanation, notes,
                        reflection_json, explanation_json, notes_json,
                        is_draft, draft_missing_fields, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    review_session_id, entry_order, question_id,
                    user_answer, correct_answer, perceived_difficulty,
                    time_spent_seconds, reflection, explanation, notes,
                    reflection_json, explanation_json, notes_json,
                    is_draft, json.dumps(missing_fields) if missing_fields else None,
                    None if is_draft else datetime.now().isoformat()
                ))

                entry_id = cursor.lastrowid

                # The DB unique index on (question_entry_id, subject_node_id)
                # is mapping_type-agnostic — the same subject cannot be both
                # primary and secondary on the same entry. Dedup defensively:
                # if a subject appears in both lists, keep it in primary and
                # drop the secondary copy so the save doesn't fail with an
                # IntegrityError. Also dedup within each list.
                primary_unique = list(dict.fromkeys(primary_subject_ids or []))
                secondary_unique = [
                    sid for sid in dict.fromkeys(secondary_subject_ids or [])
                    if sid not in primary_unique
                ]

                # Add subject mappings
                for subject_id in primary_unique:
                    self.execute("""
                        INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                        VALUES (?, ?, 'primary')
                    """, (entry_id, subject_id))

                for subject_id in secondary_unique:
                    self.execute("""
                        INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                        VALUES (?, ?, 'secondary')
                    """, (entry_id, subject_id))

                # Add tags
                if tag_ids:
                    for tag_id in tag_ids:
                        self.execute("""
                            INSERT INTO entry_tags (question_entry_id, tag_id)
                            VALUES (?, ?)
                        """, (entry_id, tag_id))

                # Update session entries_completed if not draft
                if not is_draft:
                    self.increment_session_entries_completed(review_session_id)

                if self.error_logger:
                    self.error_logger.debug(
                        f"Created question entry (ID: {entry_id}, draft: {is_draft})",
                        category=ErrorCategory.DATABASE
                    )

            # Graph dual-write (after SQLite commit)
            def _graph_write():
                self._graph_execute(
                    "MERGE (e:Entry {sqlite_id: $id})",
                    {"id": entry_id}
                )
                if primary_subject_ids:
                    for sid in primary_subject_ids:
                        self._graph_execute(
                            "MATCH (e:Entry {sqlite_id: $eid}), (s:Subject {sqlite_id: $sid}) "
                            "CREATE (e)-[:TAGGED_TO {mapping_type: 'primary'}]->(s)",
                            {"eid": entry_id, "sid": sid}
                        )
                if secondary_subject_ids:
                    for sid in secondary_subject_ids:
                        self._graph_execute(
                            "MATCH (e:Entry {sqlite_id: $eid}), (s:Subject {sqlite_id: $sid}) "
                            "CREATE (e)-[:TAGGED_TO {mapping_type: 'secondary'}]->(s)",
                            {"eid": entry_id, "sid": sid}
                        )
            self._dual_write_graph("create_question_entry", _graph_write)

            return self.get_question_entry(entry_id)

        except DatabaseIntegrityError as e:
            raise QuestionEntryError(f"Failed to create question entry: {e}") from e

    def get_question_entry(self, entry_id: int) -> Optional['QuestionEntry']:
        """Get question entry by ID"""
        from ..models import QuestionEntry

        row = self.fetchone(
            "SELECT * FROM question_entries WHERE id = ?",
            (entry_id,)
        )

        if not row:
            return None

        entry = QuestionEntry.from_db_row(row)

        # Load related data
        entry.primary_subjects = self._get_entry_subjects(entry_id, 'primary')
        entry.secondary_subjects = self._get_entry_subjects(entry_id, 'secondary')
        entry.tags = self._get_entry_tags(entry_id)
        entry.media = self._get_entry_media(entry_id)
        entry.notes_list = self._get_entry_notes(entry_id)

        return entry

    def get_session_entries(
        self,
        session_id: int,
        include_drafts: bool = True
    ) -> List['QuestionEntry']:
        """
        Get all entries for a review session.

        Args:
            session_id: ID of the review session
            include_drafts: Include draft entries

        Returns:
            List of QuestionEntry objects, ordered by entry_order
        """
        from ..models import QuestionEntry

        query = """
            SELECT * FROM question_entries
            WHERE review_session_id = ?
        """
        params = [session_id]

        if not include_drafts:
            query += " AND is_draft = FALSE"

        query += " ORDER BY entry_order"

        rows = self.fetchall(query, tuple(params))
        entries = []

        for row in rows:
            entry = QuestionEntry.from_db_row(row)
            entry.primary_subjects = self._get_entry_subjects(entry.id, 'primary')
            entry.secondary_subjects = self._get_entry_subjects(entry.id, 'secondary')
            entry.tags = self._get_entry_tags(entry.id)
            entry.media = self._get_entry_media(entry.id)
            entry.notes_list = self._get_entry_notes(entry.id)
            entries.append(entry)

        return entries

    def update_question_entry(
        self,
        entry_id: int,
        primary_subject_ids: Optional[List[int]] = None,
        secondary_subject_ids: Optional[List[int]] = None,
        tag_ids: Optional[List[int]] = None,
        **kwargs
    ) -> 'QuestionEntry':
        """
        Update a question entry.

        Args:
            entry_id: ID of the entry to update
            primary_subject_ids: New list of primary subject IDs (replaces existing)
            secondary_subject_ids: New list of secondary subject IDs (replaces existing)
            tag_ids: New list of tag IDs (replaces existing)
            **kwargs: Other fields to update

        Returns:
            Updated QuestionEntry object
        """
        from ..exceptions import QuestionEntryNotFoundError

        # Get existing entry
        entry = self.get_question_entry(entry_id)
        if not entry:
            raise QuestionEntryNotFoundError(f"Question entry {entry_id} not found")

        # Validate difficulty if provided
        if 'perceived_difficulty' in kwargs and kwargs['perceived_difficulty'] is not None:
            if not (1 <= kwargs['perceived_difficulty'] <= 5):
                raise ValidationError("Perceived difficulty must be between 1 and 5")

        updates = []
        params = []

        allowed_fields = {
            'question_id', 'user_answer', 'correct_answer', 'perceived_difficulty',
            'time_spent_seconds', 'reflection', 'explanation', 'notes',
            'reflection_json', 'explanation_json', 'notes_json'
        }

        for field, value in kwargs.items():
            if field in allowed_fields:
                updates.append(f"{field} = ?")
                params.append(value)

        with self.transaction():
            # Update main entry fields
            if updates:
                params.append(entry_id)
                self.execute(f"""
                    UPDATE question_entries
                    SET {', '.join(updates)}
                    WHERE id = ?
                """, tuple(params))

            # Defensive cross-list dedup — see create_question_entry above
            # for the rationale (UNIQUE on (entry, subject) is
            # mapping_type-agnostic). Compute the canonical id sets up
            # front, then DELETE/INSERT each side as before.
            if primary_subject_ids is not None or secondary_subject_ids is not None:
                primary_unique = (
                    list(dict.fromkeys(primary_subject_ids))
                    if primary_subject_ids is not None
                    else None
                )
                secondary_unique = (
                    [
                        sid for sid in dict.fromkeys(secondary_subject_ids)
                        if primary_unique is None or sid not in primary_unique
                    ]
                    if secondary_subject_ids is not None
                    else None
                )

                # Subject mappings are replaced wholesale, but
                # primary_parent_id must survive that replacement.
                #
                # It is written by a SEPARATE call
                # (setPrimaryParentForEntry) and records which parent a
                # multi-parent subject was tagged under -- the thing the
                # entry form's Tag context pill exists to capture. A
                # delete-and-reinsert that omits the column silently
                # discards it on every save after the first, and the
                # caller has no way to notice: the mapping row is still
                # there, just with its context reset to NULL.
                #
                # So carry the existing value forward per subject. A
                # newly-added subject has no prior row and correctly
                # starts NULL.
                def _replace_mappings(mapping_type, subject_ids):
                    existing = {
                        row['subject_node_id']: row['primary_parent_id']
                        for row in self.fetchall(
                            "SELECT subject_node_id, primary_parent_id "
                            "FROM entry_subject_mappings "
                            "WHERE question_entry_id = ? AND mapping_type = ?",
                            (entry_id, mapping_type)
                        )
                    }
                    self.execute(
                        "DELETE FROM entry_subject_mappings "
                        "WHERE question_entry_id = ? AND mapping_type = ?",
                        (entry_id, mapping_type)
                    )
                    for subject_id in subject_ids:
                        self.execute("""
                            INSERT INTO entry_subject_mappings
                                (question_entry_id, subject_node_id,
                                 mapping_type, primary_parent_id)
                            VALUES (?, ?, ?, ?)
                        """, (entry_id, subject_id, mapping_type,
                              existing.get(subject_id)))

                if primary_unique is not None:
                    _replace_mappings('primary', primary_unique)

                if secondary_unique is not None:
                    _replace_mappings('secondary', secondary_unique)

            # Update tags if provided
            if tag_ids is not None:
                self.execute(
                    "DELETE FROM entry_tags WHERE question_entry_id = ?",
                    (entry_id,)
                )
                for tag_id in tag_ids:
                    self.execute("""
                        INSERT INTO entry_tags (question_entry_id, tag_id)
                        VALUES (?, ?)
                    """, (entry_id, tag_id))

            # Re-evaluate draft status
            updated_entry = self.get_question_entry(entry_id)
            was_draft = entry.is_draft
            is_now_draft = not updated_entry.can_complete or len(updated_entry.primary_subjects) == 0

            missing_fields = updated_entry.get_missing_required_fields()
            if len(updated_entry.primary_subjects) == 0:
                missing_fields.append('primary_subjects')

            self.execute("""
                UPDATE question_entries
                SET is_draft = ?, draft_missing_fields = ?, completed_at = ?
                WHERE id = ?
            """, (
                is_now_draft,
                json.dumps(missing_fields) if missing_fields else None,
                None if is_now_draft else (entry.completed_at or datetime.now()).isoformat(),
                entry_id
            ))

            # Update session entries_completed if draft status changed
            if was_draft and not is_now_draft:
                self.increment_session_entries_completed(entry.review_session_id)

        # Graph dual-write for subject mapping changes (after SQLite commit)
        if primary_subject_ids is not None or secondary_subject_ids is not None:
            def _graph_write():
                # Delete all existing TAGGED_TO edges for this entry
                self._graph_execute(
                    "MATCH (e:Entry {sqlite_id: $eid})-[r:TAGGED_TO]->() DELETE r",
                    {"eid": entry_id}
                )
                # Re-create based on new mappings
                if primary_subject_ids is not None:
                    for sid in primary_subject_ids:
                        self._graph_execute(
                            "MATCH (e:Entry {sqlite_id: $eid}), (s:Subject {sqlite_id: $sid}) "
                            "CREATE (e)-[:TAGGED_TO {mapping_type: 'primary'}]->(s)",
                            {"eid": entry_id, "sid": sid}
                        )
                if secondary_subject_ids is not None:
                    for sid in secondary_subject_ids:
                        self._graph_execute(
                            "MATCH (e:Entry {sqlite_id: $eid}), (s:Subject {sqlite_id: $sid}) "
                            "CREATE (e)-[:TAGGED_TO {mapping_type: 'secondary'}]->(s)",
                            {"eid": entry_id, "sid": sid}
                        )
            self._dual_write_graph("update_question_entry", _graph_write)

        return self.get_question_entry(entry_id)

    def delete_question_entry(self, entry_id: int) -> bool:
        """
        Delete a question entry and all related data.

        Args:
            entry_id: ID of the entry to delete

        Returns:
            True if deleted successfully
        """
        from ..exceptions import QuestionEntryNotFoundError

        entry = self.get_question_entry(entry_id)
        if not entry:
            raise QuestionEntryNotFoundError(f"Question entry {entry_id} not found")

        with self.transaction():
            # Delete will cascade to mappings, tags, media via FK constraints
            self.execute("DELETE FROM question_entries WHERE id = ?", (entry_id,))

            # Decrement session entries_completed if entry was complete
            if not entry.is_draft:
                self.execute("""
                    UPDATE review_sessions
                    SET entries_completed = MAX(0, entries_completed - 1)
                    WHERE id = ?
                """, (entry.review_session_id,))

        # Graph dual-write (after SQLite commit)
        def _graph_write():
            self._graph_execute(
                "MATCH (e:Entry {sqlite_id: $eid}) DETACH DELETE e",
                {"eid": entry_id}
            )
        self._dual_write_graph("delete_question_entry", _graph_write)

        return True

    def search_subjects(
        self,
        exam_context_id: int,
        query: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search subjects for autocomplete.

        Args:
            exam_context_id: ID of the exam context
            query: Search query
            limit: Maximum results

        Returns:
            List of matching subjects with full path
        """
        # Get exam context name
        exam_config = self.get_exam_context_config(exam_context_id)
        if not exam_config:
            return []

        exam_context = exam_config.exam_name

        # Search subjects (case-insensitive)
        rows = self.fetchall("""
            SELECT id, name, parent_id, level_type, exam_weight_low
            FROM subject_nodes
            WHERE exam_context = ? AND status = 'active' AND name LIKE ?
            ORDER BY level_type DESC, name
            LIMIT ?
        """, (exam_context, f"%{query}%", limit * 2))  # Get extra for path building

        results = []
        for row in rows:
            # Build full path
            path = self._build_subject_path(row['id'])
            results.append({
                'id': row['id'],
                'name': row['name'],
                'path': path,
                'level_type': row['level_type'],
                'weight': row['exam_weight_low']
            })
            if len(results) >= limit:
                break

        return results

    def get_entries_paginated(
        self,
        exam_context_id: Optional[int] = None,
        session_id: Optional[int] = None,
        subject_ids: Optional[List[int]] = None,
        include_child_subjects: bool = False,
        tag_ids: Optional[List[int]] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        is_draft: Optional[bool] = None,
        search_query: Optional[str] = None,
        sort_by: str = 'date_desc',
        page: int = 1,
        per_page: int = 20,
        field_filters: Optional[Dict[str, str]] = None,
        subject_mode: str = 'or'
    ) -> Tuple[List['QuestionEntry'], int]:
        """
        Get paginated entries with comprehensive filtering.

        Args:
            exam_context_id: Filter by exam context
            session_id: Filter by review session
            subject_ids: Filter by subject IDs (entries must have at least one)
            include_child_subjects: Include entries from child subjects
            tag_ids: Filter by tag IDs (entries must have at least one)
            date_from: Filter entries from this date
            date_to: Filter entries up to this date
            is_draft: Filter by draft status (None = all)
            search_query: Full-text search in reflection, explanation, notes
            sort_by: Sort order ('date_desc', 'date_asc', 'difficulty_desc', 'difficulty_asc', 'subject_asc')
            page: Page number (1-indexed)
            per_page: Items per page
            field_filters: Dict of field-specific filters, e.g. {'user_answer': 'ACE', 'subject': 'cardiology'}
            subject_mode: 'or' (entry matches any subject) or 'and' (entry matches all subjects)

        Returns:
            Tuple of (entries list, total count)
        """
        from ..models import QuestionEntry

        self._ensure_phase4_schema()

        # Build WHERE conditions
        conditions = ["rs.user_id = ?"]
        params = [self.user_id]

        # Exam context filter
        if exam_context_id is not None:
            conditions.append("rs.exam_context_id = ?")
            params.append(exam_context_id)

        # Session filter
        if session_id is not None:
            conditions.append("qe.review_session_id = ?")
            params.append(session_id)

        # Subject filter.
        #
        # This is a *finding* surface, so the scope rule is
        # _subject_filter_scope_sql, not the strict §5.4 predicate the
        # counting surfaces use: entries tagged the named subject directly
        # match whatever parent context they carry, and entries on its
        # descendants match only when their context routes through it.
        # See that helper's docstring, and the decision on Forgejo #13.
        #
        # The two id sets it takes are not interchangeable: the named
        # subjects drive the direct-tag clause, the descendant set drives
        # the rollup clause. The descendant set already includes the seed
        # node itself, so the equality case (primary_parent_id == the
        # filtered subject) is covered.
        #
        # No mapping_type filter, deliberately: an entry tagged
        # "also tested: DVT" is one the student looking for DVT wants.
        # Contrast get_subject_analytics, which totals mistakes and
        # filters to 'primary'.
        if subject_ids:
            if subject_mode == 'and' and len(subject_ids) > 1:
                # AND mode: entry must be tagged with at least one node from EACH subject's tree
                subject_conditions = []
                for sid in subject_ids:
                    sid_set = {sid}
                    if include_child_subjects:
                        sid_set.update(self._get_descendant_node_ids(sid))
                    scope_sql, scope_params = self._subject_filter_scope_sql(
                        {sid}, sid_set, alias='esm'
                    )
                    subject_conditions.append(f"""
                        qe.id IN (
                            SELECT DISTINCT esm.question_entry_id
                            FROM entry_subject_mappings esm
                            WHERE {scope_sql}
                        )
                    """)
                    params.extend(scope_params)
                conditions.append('(' + ' AND '.join(subject_conditions) + ')')
            else:
                # OR mode (default): entry matches any of the subjects
                all_subject_ids = set(subject_ids)
                if include_child_subjects:
                    for sid in subject_ids:
                        all_subject_ids.update(self._get_descendant_node_ids(sid))

                scope_sql, scope_params = self._subject_filter_scope_sql(
                    set(subject_ids), all_subject_ids, alias='esm'
                )
                conditions.append(f"""
                    qe.id IN (
                        SELECT DISTINCT esm.question_entry_id
                        FROM entry_subject_mappings esm
                        WHERE {scope_sql}
                    )
                """)
                params.extend(scope_params)

        # Tag filter
        if tag_ids:
            placeholders = ','.join(['?'] * len(tag_ids))
            conditions.append(f"""
                qe.id IN (
                    SELECT DISTINCT question_entry_id
                    FROM entry_tags
                    WHERE tag_id IN ({placeholders})
                )
            """)
            params.extend(tag_ids)

        # Date filter
        if date_from:
            conditions.append("rs.date_encountered >= ?")
            params.append(date_from.isoformat())

        if date_to:
            conditions.append("rs.date_encountered <= ?")
            params.append(date_to.isoformat())

        # Draft filter
        if is_draft is not None:
            conditions.append("qe.is_draft = ?")
            params.append(is_draft)

        # Search filter - searches in entry text fields AND associated subject names
        #
        # Deliberately no mapping_type filter (decided, not overlooked). This
        # is a free-text *search* over a browse surface: someone typing a
        # subject name is asking "which entries mention this", and an entry
        # where the subject was an "also tested" secondary tag is a legitimate
        # hit. Filtering to 'primary' here would silently hide entries whose
        # text the user can see matches. Contrast get_related_subjects, which
        # is a mistake count and does filter. Also no §5.4 predicate: this
        # branch names an exact subject by name with no descendant set, so it
        # does not aggregate and §5.4 is inapplicable.
        if search_query:
            search_term = f"%{search_query}%"
            conditions.append("""
                (qe.reflection LIKE ? OR qe.explanation LIKE ? OR qe.notes LIKE ?
                 OR qe.user_answer LIKE ? OR qe.correct_answer LIKE ?
                 OR qe.id IN (
                     SELECT esm.question_entry_id
                     FROM entry_subject_mappings esm
                     JOIN subject_nodes sn ON esm.subject_node_id = sn.id
                     WHERE sn.name LIKE ?
                 ))
            """)
            params.extend([search_term] * 6)

        # Field-specific filters
        if field_filters:
            ALLOWED_DIRECT_FIELDS = {
                'user_answer': 'qe.user_answer',
                'correct_answer': 'qe.correct_answer',
                'reflection': 'qe.reflection',
                'explanation': 'qe.explanation',
            }
            for field_name, field_value in field_filters.items():
                if field_name in ALLOWED_DIRECT_FIELDS:
                    col = ALLOWED_DIRECT_FIELDS[field_name]
                    conditions.append(f"{col} LIKE ?")
                    params.append(f"%{field_value}%")
                elif field_name == 'subject':
                    # Same call as the free-text branch above: a name search
                    # on a browse surface, so no mapping_type filter and no
                    # §5.4 predicate (exact name match, no ancestor walk).
                    # The structured, hierarchy-aware subject filter is
                    # `subject_ids` + `include_child_subjects`, which does
                    # apply §5.4.
                    conditions.append("""
                        qe.id IN (
                            SELECT esm.question_entry_id
                            FROM entry_subject_mappings esm
                            JOIN subject_nodes sn ON esm.subject_node_id = sn.id
                            WHERE sn.name LIKE ?
                        )
                    """)
                    params.append(f"%{field_value}%")
                elif field_name == 'notes':
                    conditions.append("""
                        (qe.notes LIKE ? OR qe.id IN (
                            SELECT en.question_entry_id
                            FROM entry_notes en
                            WHERE en.content_html LIKE ?
                        ))
                    """)
                    params.append(f"%{field_value}%")
                    params.append(f"%{field_value}%")
                elif field_name == 'question_id':
                    conditions.append("qe.question_id LIKE ?")
                    params.append(f"{field_value}%")
                # Unknown field names are silently ignored

        where_clause = " AND ".join(conditions)

        # Sort order mapping
        sort_mapping = {
            'date_desc': 'rs.date_encountered DESC, qe.created_at DESC',
            'date_asc': 'rs.date_encountered ASC, qe.created_at ASC',
            'difficulty_desc': 'qe.perceived_difficulty DESC NULLS LAST, qe.created_at DESC',
            'difficulty_asc': 'qe.perceived_difficulty ASC NULLS LAST, qe.created_at DESC',
            'subject_asc': 'qe.created_at DESC'  # Will be improved with subject join
        }
        order_clause = sort_mapping.get(sort_by, sort_mapping['date_desc'])

        # Count total
        count_query = f"""
            SELECT COUNT(DISTINCT qe.id) as total
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause}
        """
        count_row = self.fetchone(count_query, tuple(params))
        total = count_row['total'] if count_row else 0

        # Get paginated results
        offset = (page - 1) * per_page
        query = f"""
            SELECT DISTINCT qe.*
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE {where_clause}
            ORDER BY {order_clause}
            LIMIT ? OFFSET ?
        """
        params.extend([per_page, offset])

        rows = self.fetchall(query, tuple(params))
        entries = []

        for row in rows:
            entry = QuestionEntry.from_db_row(row)
            # Load related data
            entry.primary_subjects = self._get_entry_subjects(entry.id, 'primary')
            entry.secondary_subjects = self._get_entry_subjects(entry.id, 'secondary')
            entry.tags = self._get_entry_tags(entry.id)
            entry.media = self._get_entry_media(entry.id)
            entries.append(entry)

        return entries, total

    def get_entry_with_context(self, entry_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a full entry with all context (session, exam, source info).

        Args:
            entry_id: Question entry ID

        Returns:
            Dictionary with entry and all context, or None if not found
        """
        from ..models import QuestionEntry

        row = self.fetchone("""
            SELECT qe.*,
                   rs.session_name, rs.date_encountered, rs.total_questions, rs.total_incorrect,
                   ec.id AS exam_context_id, ec.exam_name, ec.exam_description,
                   qs.source_name, qs.source_type
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            LEFT JOIN exam_contexts ec ON rs.exam_context_id = ec.id
            LEFT JOIN question_sources qs ON rs.question_source_id = qs.id
            WHERE qe.id = ?
        """, (entry_id,))

        if not row:
            return None

        entry = QuestionEntry.from_db_row(row)
        entry.primary_subjects = self._get_entry_subjects(entry_id, 'primary')
        entry.secondary_subjects = self._get_entry_subjects(entry_id, 'secondary')
        entry.tags = self._get_entry_tags(entry_id)
        entry.media = self._get_entry_media(entry_id)
        entry.notes_list = self._get_entry_notes(entry_id)

        # Build subject path from primary subject
        subject_path = ""
        if entry.primary_subjects:
            subject_path = self._build_subject_path(entry.primary_subjects[0].id)

        return {
            'entry': self._entry_to_dict(entry),
            'session': {
                'id': entry.review_session_id,
                'name': row['session_name'],
                'date': row['date_encountered'],
                'total_questions': row['total_questions'],
                'total_incorrect': row['total_incorrect']
            },
            'exam': {
                # The id the detail page scopes Related Topics, subject-name
                # resolution and its Back/per-subject links to. NULL only when
                # the session's exam context row is gone (the join is LEFT).
                'id': row['exam_context_id'],
                'name': row['exam_name'],
                'description': row['exam_description']
            },
            'source': {
                'name': row['source_name'],
                'type': row['source_type']
            } if row['source_name'] else None,
            'subject_path': subject_path
        }

    def get_related_subjects(
        self,
        subject_id: int,
        exam_context_id: int,
        limit: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Get related subjects for the 'Related Topics to Review' panel.

        Strategy:
        1. Get siblings (every parent's other children) - prioritized
        2. Get parents' siblings (aunts/uncles)
        3. Get children of the current node
        4. Prioritize subjects with more entries (mistakes)

        **This function does NOT aggregate up a hierarchy.** The count is a
        direct per-node count: each candidate is matched on
        ``esm.subject_node_id = sn.id`` with no descendant set and no
        ancestor walk, so ``POLYHIERARCHY_MIGRATION.md`` §5.4 (and
        :meth:`SharedHelpersMixin._primary_parent_scope_sql`) is
        definitionally inapplicable here — a disambiguated entry is still
        this subject's own mistake whichever branch it rolls into. Changing
        the tag context cannot change this function's output. Do not add
        the §5.4 predicate here; it would *remove* entries the student
        explicitly tagged on the node.

        What it did carry (all fixed):

        * **Legacy ``subject_nodes.parent_id``** in all three discovery
          steps, so a relative attached only through ``subject_edges`` was
          invisible. Discovery now walks ``subject_edges`` (the canonical
          source per CLAUDE.md), which also means a multi-parent subject
          contributes siblings from *every* parent rather than only the
          legacy one. Falls back to ``parent_id`` only when the node has no
          edges at all (legacy DBs predating m004, and tests that seed
          ``subject_nodes`` by raw INSERT).
        * **No ``mapping_type`` filter**, so "also tested" secondary tags
          were counted as mistakes. This is a *mistake count* used to rank
          what to review next, so it now filters to ``'primary'`` — the
          same choice Top Subjects, the subject sunburst and the dimension
          sunburst make. (Contrast the free-text search branches in this
          file, which deliberately stay unfiltered; see
          :meth:`get_entries_paginated`.)
        * **No session scoping at all** — ``exam_context_id`` was accepted,
          used once for an early-return config lookup, and never reached
          the query. Every other user's and every other exam's entries
          were counted. Now joined through ``review_sessions`` and scoped
          to both.
        * ``COUNT(esm.id)`` rather than
          ``COUNT(DISTINCT esm.question_entry_id)``. Kept as the distinct
          form for intent, though note the two are equivalent in practice:
          ``idx_unique_entry_subject`` is UNIQUE on
          ``(question_entry_id, subject_node_id)`` and is mapping_type
          agnostic, so one entry can never hold two mappings on the same
          node (``create_question_entry`` dedups defensively for exactly
          this reason).

        ``is_draft`` is deliberately NOT filtered — see the ledger in
        ``docs/planning/ENTRY_COUNT_AUDIT.md``; picking a side belongs to
        that decision, not to this fix.

        Args:
            subject_id: Current subject ID
            exam_context_id: Exam context — scopes the entry counts, and
                gates the early return
            limit: Maximum results

        Returns:
            List of related subjects with entry counts
        """
        # Get exam context name
        exam_config = self.get_exam_context_config(exam_context_id)
        if not exam_config:
            return []

        current = self.get_subject_node(subject_id)
        if not current:
            return []

        edges_available = self.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='subject_edges'"
        ) is not None

        def _parents_of(node_id: int, legacy_parent_id: Optional[int] = None) -> List[int]:
            """Parent ids from ``subject_edges``, legacy column as fallback.

            A node may have several parents; all of them contribute
            relatives. The legacy fallback fires only when the node has no
            edge rows at all, matching the dual-mode shape of
            ``_get_descendant_node_ids``.
            """
            if edges_available:
                rows = self.fetchall(
                    "SELECT parent_id FROM subject_edges WHERE child_id = ?",
                    (node_id,),
                )
                if rows:
                    return [row['parent_id'] for row in rows]
            if legacy_parent_id is None:
                row = self.fetchone(
                    "SELECT parent_id FROM subject_nodes WHERE id = ?",
                    (node_id,),
                )
                legacy_parent_id = row['parent_id'] if row else None
            return [legacy_parent_id] if legacy_parent_id else []

        def _children_of(node_ids: List[int]) -> List[int]:
            """Active child ids of any of ``node_ids``, edges first."""
            if not node_ids:
                return []
            placeholders = ','.join(['?'] * len(node_ids))
            if edges_available:
                rows = self.fetchall(
                    f"""
                    SELECT DISTINCT se.child_id AS id
                    FROM subject_edges se
                    JOIN subject_nodes sn ON sn.id = se.child_id
                    WHERE se.parent_id IN ({placeholders})
                      AND sn.status = 'active'
                    """,
                    tuple(node_ids),
                )
                if rows:
                    return [row['id'] for row in rows]
            rows = self.fetchall(
                f"""
                SELECT id FROM subject_nodes
                WHERE parent_id IN ({placeholders}) AND status = 'active'
                """,
                tuple(node_ids),
            )
            return [row['id'] for row in rows]

        related_ids = set()

        # 1. Siblings — other children of every parent this node has.
        parent_ids = _parents_of(subject_id, current.parent_id)
        related_ids.update(_children_of(parent_ids))
        related_ids.discard(subject_id)

        # 2. Aunts/uncles — other children of every grandparent.
        if len(related_ids) < limit and parent_ids:
            grandparent_ids = []
            for pid in parent_ids:
                grandparent_ids.extend(_parents_of(pid))
            related_ids.update(_children_of(grandparent_ids))
            related_ids.difference_update(parent_ids)
            related_ids.discard(subject_id)

        # 3. Children of the current node.
        if len(related_ids) < limit:
            related_ids.update(_children_of([subject_id]))
            related_ids.discard(subject_id)

        if not related_ids:
            return []

        # Rank by mistake count. The count is a correlated scalar subquery
        # rather than a LEFT JOIN + GROUP BY so that a candidate whose only
        # entries fall outside this user/exam still appears with a count of
        # 0 instead of being dropped from the result set entirely.
        ids = list(related_ids)
        placeholders = ','.join(['?'] * len(ids))
        results = self.fetchall(f"""
            SELECT sn.id, sn.name, (
                SELECT COUNT(DISTINCT esm.question_entry_id)
                FROM entry_subject_mappings esm
                JOIN question_entries qe ON qe.id = esm.question_entry_id
                JOIN review_sessions rs ON rs.id = qe.review_session_id
                WHERE esm.subject_node_id = sn.id
                  AND esm.mapping_type = 'primary'
                  AND rs.user_id = ?
                  AND rs.exam_context_id = ?
            ) AS entry_count
            FROM subject_nodes sn
            WHERE sn.id IN ({placeholders})
              AND sn.status = 'active'
            ORDER BY entry_count DESC, sn.name ASC
            LIMIT ?
        """, tuple([self.user_id, exam_context_id] + ids + [limit]))

        return [
            {
                'id': row['id'],
                'name': row['name'],
                'path': self._build_subject_path(row['id']),
                'entry_count': row['entry_count']
            }
            for row in results
        ]

    def search_entries_fulltext(
        self,
        query: str,
        exam_context_id: Optional[int] = None,
        limit: int = 50
    ) -> List['QuestionEntry']:
        """
        Full-text search across entry fields.

        Does not aggregate — the subject sub-query matches a node by name
        with no descendant set, so §5.4 is inapplicable. The missing
        ``mapping_type`` filter is deliberate for the same reason as the
        search branch of :meth:`get_entries_paginated`: a name search on a
        browse surface should return entries where the subject was a
        secondary ("also tested") tag.

        Args:
            query: Search query
            exam_context_id: Optional filter by exam context
            limit: Maximum results

        Returns:
            List of matching entries
        """
        from ..models import QuestionEntry

        self._ensure_phase4_schema()

        search_term = f"%{query}%"

        sql = """
            SELECT DISTINCT qe.*
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ?
            AND (
                qe.reflection LIKE ? OR
                qe.explanation LIKE ? OR
                qe.notes LIKE ? OR
                qe.user_answer LIKE ? OR
                qe.correct_answer LIKE ? OR
                qe.question_id LIKE ? OR
                qe.id IN (
                    SELECT esm.question_entry_id
                    FROM entry_subject_mappings esm
                    JOIN subject_nodes sn ON esm.subject_node_id = sn.id
                    WHERE sn.name LIKE ?
                )
            )
        """
        params = [self.user_id] + [search_term] * 7

        if exam_context_id:
            sql += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)

        sql += " ORDER BY rs.date_encountered DESC LIMIT ?"
        params.append(limit)

        rows = self.fetchall(sql, tuple(params))
        entries = []

        for row in rows:
            entry = QuestionEntry.from_db_row(row)
            entry.primary_subjects = self._get_entry_subjects(entry.id, 'primary')
            entry.secondary_subjects = self._get_entry_subjects(entry.id, 'secondary')
            entry.tags = self._get_entry_tags(entry.id)
            entry.media = self._get_entry_media(entry.id)
            entries.append(entry)

        return entries

    def get_entries_by_question_id(
        self,
        question_id: str,
        exam_context_id: int,
        exclude_entry_id: Optional[int] = None
    ) -> List['QuestionEntry']:
        """
        Look up entries with the same question_id in an exam context.
        Used for auto-fill functionality in the question entry form.

        Args:
            question_id: The user's question reference (e.g., "Q15", "Page 42")
            exam_context_id: Exam context to search within
            exclude_entry_id: Optional entry ID to exclude (to avoid self-matching)

        Returns:
            List of matching entries with subjects and tags populated
        """
        from ..models import QuestionEntry

        self._ensure_phase4_schema()

        if not question_id or not question_id.strip():
            return []

        sql = """
            SELECT qe.*
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ?
            AND rs.exam_context_id = ?
            AND qe.question_id = ?
        """
        params = [self.user_id, exam_context_id, question_id.strip()]

        if exclude_entry_id:
            sql += " AND qe.id != ?"
            params.append(exclude_entry_id)

        sql += " ORDER BY qe.created_at DESC"

        rows = self.fetchall(sql, tuple(params))
        entries = []

        for row in rows:
            entry = QuestionEntry.from_db_row(row)
            entry.primary_subjects = self._get_entry_subjects(entry.id, 'primary')
            entry.secondary_subjects = self._get_entry_subjects(entry.id, 'secondary')
            entry.tags = self._get_entry_tags(entry.id)
            entries.append(entry)

        return entries

    def get_entry_statistics(
        self,
        exam_context_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get statistics about entries for display.

        Args:
            exam_context_id: Optional filter by exam context

        Returns:
            Dictionary with entry statistics
        """
        self._ensure_phase4_schema()

        base_query = """
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ?
        """
        params = [self.user_id]

        if exam_context_id:
            base_query += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)

        # Total entries
        total_row = self.fetchone(
            f"SELECT COUNT(*) as count {base_query}",
            tuple(params)
        )
        total = total_row['count'] if total_row else 0

        # Draft count
        draft_row = self.fetchone(
            f"SELECT COUNT(*) as count {base_query} AND qe.is_draft = TRUE",
            tuple(params)
        )
        drafts = draft_row['count'] if draft_row else 0

        # Entries this week
        week_row = self.fetchone(
            f"SELECT COUNT(*) as count {base_query} AND qe.created_at >= date('now', '-7 days')",
            tuple(params)
        )
        this_week = week_row['count'] if week_row else 0

        # Entries this month
        month_row = self.fetchone(
            f"SELECT COUNT(*) as count {base_query} AND qe.created_at >= date('now', '-30 days')",
            tuple(params)
        )
        this_month = month_row['count'] if month_row else 0

        # By difficulty breakdown
        difficulty_rows = self.fetchall(f"""
            SELECT qe.perceived_difficulty, COUNT(*) as count
            {base_query}
            GROUP BY qe.perceived_difficulty
            ORDER BY qe.perceived_difficulty
        """, tuple(params))

        by_difficulty = {row['perceived_difficulty']: row['count'] for row in difficulty_rows if row['perceived_difficulty']}

        # Top tags
        top_tags = self.fetchall(f"""
            SELECT t.tag_name, t.color_hex, COUNT(*) as count
            FROM entry_tags et
            JOIN tags t ON et.tag_id = t.id
            JOIN question_entries qe ON et.question_entry_id = qe.id
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ?
            {' AND rs.exam_context_id = ?' if exam_context_id else ''}
            GROUP BY t.id, t.tag_name, t.color_hex
            ORDER BY count DESC
            LIMIT 5
        """, tuple(params))

        return {
            'total': total,
            'drafts': drafts,
            'completed': total - drafts,
            'this_week': this_week,
            'this_month': this_month,
            'by_difficulty': by_difficulty,
            'top_tags': [
                {'name': row['tag_name'], 'color': row['color_hex'], 'count': row['count']}
                for row in top_tags
            ]
        }

    def get_entries_by_subject(
        self,
        subject_id: int,
        include_children: bool = True,
        limit: Optional[int] = None,
        exam_context_id: Optional[int] = None
    ) -> List['QuestionEntry']:
        """
        Get entries for a specific subject (for related topics navigation).

        **This function AGGREGATES up a hierarchy** when
        ``include_children`` is set: the scope is ``subject_id`` plus
        ``_get_descendant_node_ids(subject_id)``, and entries are matched
        against that whole set. That makes ``POLYHIERARCHY_MIGRATION.md``
        §5.4 apply, and it was absent — an entry whose student pinned it to
        one parent was still returned under every other parent of a shared
        subject. Scoping now goes through
        :meth:`SharedHelpersMixin._subject_filter_scope_sql`, the same
        helper :meth:`get_entries_paginated` uses; see its docstring for
        why the predicate is a conditional with an unconditional
        direct-tag clause in front of it. Do not re-derive it inline.

        Two further changes:

        * **The graph-first shortcut is gone.** It asked LadybugDB for the
          entry ids and returned that answer whenever it was non-empty,
          which bypassed the SQL above entirely — including the §5.4
          predicate. ``GraphMixin._etl_subjects`` builds ``HAS_CHILD``
          exclusively from the legacy ``subject_nodes.parent_id`` column and
          ``EdgesMixin`` performs no graph dual-write, so the graph cannot
          see a second parent and answers every polyhierarchy question with
          the legacy single-parent one. ``_graph_read_ready`` defaults to
          True, so the shortcut fired in production. Same defect, same
          cause and same resolution as the one recorded on
          :meth:`SharedHelpersMixin._get_descendant_node_ids` and
          :meth:`SharedHelpersMixin._build_subject_path`: **do not re-add
          it** without first rebuilding the ETL on ``subject_edges`` and
          adding dual-writes to ``EdgesMixin``.
        * **``exam_context_id`` is now accepted** so a caller can scope to
          one exam. It defaults to None (no scoping) to keep the existing
          signature working.

        Deliberately NOT filtered:

        * ``mapping_type`` — this is a *browse/navigation* surface that
          answers "show me the entries on this subject", not a mistake
          count. A student who navigates to a topic plausibly wants the
          questions where it was a secondary ("also tested") tag too. The
          mistake-count surfaces (Top Subjects, both sunbursts,
          :meth:`get_related_subjects`) filter to ``'primary'``; this one
          matches :meth:`get_entries_paginated`'s subject filter instead.
        * ``is_draft`` — see the ledger in
          ``docs/planning/ENTRY_COUNT_AUDIT.md``.

        Former quirk, fixed in the shared helper (Forgejo #13, decided
        2026-09-14): an entry tagged on a shared leaf *and* pinned to a
        parent used not to be returned when the scope was the leaf alone,
        because the predicate asked whether the chosen parent was in
        scope. It is now returned — the leaf is the subject the entry
        actually carries. Pinned by
        ``test_entry_filter_on_the_leaf_finds_entries_scoped_to_another_parent``
        and ``test_entries_by_subject_finds_the_leaf_whatever_the_context``
        in ``tests/database/``.

        Args:
            subject_id: Subject node ID
            include_children: Include entries from child subjects
            limit: Maximum results
            exam_context_id: Optional exam context to scope entries to

        Returns:
            List of entries
        """
        from ..models import QuestionEntry

        subject_ids = {subject_id}
        if include_children:
            subject_ids.update(self._get_descendant_node_ids(subject_id))

        scope_sql, scope_params = self._subject_filter_scope_sql(
            {subject_id}, subject_ids, alias='esm'
        )

        query = f"""
            SELECT DISTINCT qe.*
            FROM question_entries qe
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.user_id = ? AND {scope_sql}
        """
        params = [self.user_id] + scope_params
        if exam_context_id is not None:
            query += " AND rs.exam_context_id = ?"
            params.append(exam_context_id)
        query += " ORDER BY rs.date_encountered DESC, qe.created_at DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = self.fetchall(query, tuple(params))

        entries = []
        for row in rows:
            entry = QuestionEntry.from_db_row(row)
            entry.primary_subjects = self._get_entry_subjects(entry.id, 'primary')
            entry.secondary_subjects = self._get_entry_subjects(entry.id, 'secondary')
            entry.tags = self._get_entry_tags(entry.id)
            entries.append(entry)

        return entries
