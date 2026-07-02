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

                if primary_unique is not None:
                    self.execute(
                        "DELETE FROM entry_subject_mappings WHERE question_entry_id = ? AND mapping_type = 'primary'",
                        (entry_id,)
                    )
                    for subject_id in primary_unique:
                        self.execute("""
                            INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                            VALUES (?, ?, 'primary')
                        """, (entry_id, subject_id))

                if secondary_unique is not None:
                    self.execute(
                        "DELETE FROM entry_subject_mappings WHERE question_entry_id = ? AND mapping_type = 'secondary'",
                        (entry_id,)
                    )
                    for subject_id in secondary_unique:
                        self.execute("""
                            INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, mapping_type)
                            VALUES (?, ?, 'secondary')
                        """, (entry_id, subject_id))

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
        # Polyhierarchy migration §5.4: when esm.primary_parent_id is
        # set, the entry is contextually anchored to that parent's
        # subtree, NOT the leaf's full ancestor closure. So a "filter
        # by subject S" matches an entry iff:
        #   - primary_parent_id IS NULL AND subject_node_id is in S's subtree, OR
        #   - primary_parent_id IS NOT NULL AND primary_parent_id is in S's subtree.
        # The descendant set (`sid_set`) already includes ``sid`` itself
        # so the equality case (primary_parent_id == sid) is covered.
        if subject_ids:
            if subject_mode == 'and' and len(subject_ids) > 1:
                # AND mode: entry must be tagged with at least one node from EACH subject's tree
                subject_conditions = []
                for sid in subject_ids:
                    sid_set = {sid}
                    if include_child_subjects:
                        sid_set.update(self._get_descendant_node_ids(sid))
                    placeholders = ','.join(['?'] * len(sid_set))
                    sid_set_list = list(sid_set)
                    subject_conditions.append(f"""
                        qe.id IN (
                            SELECT DISTINCT question_entry_id
                            FROM entry_subject_mappings
                            WHERE
                                (primary_parent_id IS NULL AND subject_node_id IN ({placeholders}))
                                OR (primary_parent_id IS NOT NULL AND primary_parent_id IN ({placeholders}))
                        )
                    """)
                    params.extend(sid_set_list)
                    params.extend(sid_set_list)
                conditions.append('(' + ' AND '.join(subject_conditions) + ')')
            else:
                # OR mode (default): entry matches any of the subjects
                all_subject_ids = set(subject_ids)
                if include_child_subjects:
                    for sid in subject_ids:
                        all_subject_ids.update(self._get_descendant_node_ids(sid))

                placeholders = ','.join(['?'] * len(all_subject_ids))
                all_list = list(all_subject_ids)
                conditions.append(f"""
                    qe.id IN (
                        SELECT DISTINCT question_entry_id
                        FROM entry_subject_mappings
                        WHERE
                            (primary_parent_id IS NULL AND subject_node_id IN ({placeholders}))
                            OR (primary_parent_id IS NOT NULL AND primary_parent_id IN ({placeholders}))
                    )
                """)
                params.extend(all_list)
                params.extend(all_list)

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
                   ec.exam_name, ec.exam_description,
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
        1. Get siblings (same parent) - prioritized
        2. Get parent's siblings (aunts/uncles)
        3. Prioritize subjects with more entries (mistakes)

        Args:
            subject_id: Current subject ID
            exam_context_id: Exam context for entry counting
            limit: Maximum results

        Returns:
            List of related subjects with entry counts
        """
        # Get exam context name
        exam_config = self.get_exam_context_config(exam_context_id)
        if not exam_config:
            return []

        # Get current node's parent
        current = self.get_subject_node(subject_id)
        if not current:
            return []

        related_ids = set()

        # 1. Get siblings (same parent)
        if current.parent_id:
            siblings = self.fetchall("""
                SELECT id FROM subject_nodes
                WHERE parent_id = ? AND id != ? AND status = 'active'
            """, (current.parent_id, subject_id))
            related_ids.update(row['id'] for row in siblings)

        # 2. Get parent's siblings (aunts/uncles) if we need more
        if len(related_ids) < limit and current.parent_id:
            parent = self.get_subject_node(current.parent_id)
            if parent and parent.parent_id:
                aunts_uncles = self.fetchall("""
                    SELECT id FROM subject_nodes
                    WHERE parent_id = ? AND id != ? AND status = 'active'
                """, (parent.parent_id, parent.id))
                related_ids.update(row['id'] for row in aunts_uncles)

        # 3. Get children of current node if we need more
        if len(related_ids) < limit:
            children = self.fetchall("""
                SELECT id FROM subject_nodes
                WHERE parent_id = ? AND status = 'active'
            """, (subject_id,))
            related_ids.update(row['id'] for row in children)

        if not related_ids:
            return []

        # Get entry counts for these subjects and rank by count
        placeholders = ','.join(['?'] * len(related_ids))
        results = self.fetchall(f"""
            SELECT sn.id, sn.name, COUNT(esm.id) as entry_count
            FROM subject_nodes sn
            LEFT JOIN entry_subject_mappings esm ON sn.id = esm.subject_node_id
            WHERE sn.id IN ({placeholders})
            GROUP BY sn.id, sn.name
            ORDER BY entry_count DESC, sn.name ASC
            LIMIT ?
        """, tuple(list(related_ids) + [limit]))

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
        limit: Optional[int] = None
    ) -> List['QuestionEntry']:
        """
        Get entries for a specific subject (for related topics navigation).

        Graph-primary (P2.5): uses graph for entry ID retrieval, SQLite for
        full entry content.

        Args:
            subject_id: Subject node ID
            include_children: Include entries from child subjects
            limit: Maximum results

        Returns:
            List of entries
        """
        from ..models import QuestionEntry

        entry_ids = None

        # Try graph first for entry ID retrieval (P2.5)
        # Only trust non-empty results — empty could mean unpopulated graph edges
        if getattr(self, '_graph_read_ready', False):
            try:
                graph_ids = self._graph_get_entries_for_subject(
                    subject_id, include_children=include_children,
                )
                if graph_ids:
                    entry_ids = graph_ids
            except Exception as e:
                logger.warning("Graph read failed for get_entries_by_subject, falling back to SQLite: %s", e)

        if entry_ids is not None:
            # Graph provided IDs — fetch full entries from SQLite
            placeholders = ','.join(['?'] * len(entry_ids))
            query = f"""
                SELECT DISTINCT qe.*
                FROM question_entries qe
                JOIN review_sessions rs ON qe.review_session_id = rs.id
                WHERE rs.user_id = ? AND qe.id IN ({placeholders})
                ORDER BY rs.date_encountered DESC, qe.created_at DESC
            """
            params = [self.user_id] + entry_ids
            if limit:
                query += f" LIMIT {limit}"
            rows = self.fetchall(query, tuple(params))
        else:
            # SQLite fallback — full query
            subject_ids = [subject_id]
            if include_children:
                subject_ids.extend(self._get_descendant_node_ids(subject_id))

            placeholders = ','.join(['?'] * len(subject_ids))
            query = f"""
                SELECT DISTINCT qe.*
                FROM question_entries qe
                JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
                JOIN review_sessions rs ON qe.review_session_id = rs.id
                WHERE rs.user_id = ? AND esm.subject_node_id IN ({placeholders})
                ORDER BY rs.date_encountered DESC, qe.created_at DESC
            """
            params = [self.user_id] + subject_ids
            if limit:
                query += f" LIMIT {limit}"
            rows = self.fetchall(query, tuple(params))

        entries = []
        for row in rows:
            entry = QuestionEntry.from_db_row(row)
            entry.primary_subjects = self._get_entry_subjects(entry.id, 'primary')
            entry.secondary_subjects = self._get_entry_subjects(entry.id, 'secondary')
            entry.tags = self._get_entry_tags(entry.id)
            entries.append(entry)

        return entries
