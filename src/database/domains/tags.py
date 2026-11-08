"""WIMI Tags database operations.

Since m038 (#888, owner 2026-11-06) error types are **one library per
profile**. Every ``tags`` row has ``exam_context`` NULL, and a type is the
same row wherever it appears: its name, definition and colour are shared, so
rewriting a definition changes it on every exam that lists the type.

Which types an exam's picker and Manage Error Types *offer* is that exam's
**list**, ``exam_error_types`` (``exam_context_id`` -> ``exam_contexts`` ON
DELETE CASCADE, ``tag_id`` -> ``tags`` ON DELETE CASCADE). The list decides
only what can be *added* to an entry. An entry keeps every type it carries
whether or not its exam still lists it.

The rules, each decided on #888:

* **A type is identified by (group name, type name)** (decision 1), enforced
  by ``idx_unique_tag_in_group``. Creating one the library already has lists
  the existing row on the exam instead of making a copy.
* **A type made on an exam is listed on that exam only** (4a). Other exams add
  it on purpose (:meth:`TagsMixin.add_tag_to_exam`, "Add from your other
  exams").
* **Remove from this exam** (:meth:`TagsMixin.remove_tag_from_exam`) deletes
  the list row and nothing else: entries keep the type, analytics count it.
* **The defaults are offered once, to a new exam.** ``exam_error_types_seeded``
  records every exam whose list has ever held a row, and
  :meth:`TagsMixin.seed_default_tags` leaves those alone, so a list the
  student empties with Remove stays empty when the picker reloads.
* **Delete for good** (:meth:`TagsMixin.delete_tag`) is refused while another
  exam lists the type (4b). It removes the library row, so ``entry_tags``'
  cascade takes it off every entry in every exam.

Every public method still takes the exam by NAME, as before, because that is
what the entry form and the bridge hold. The name only picks the exam's list;
nothing is filed under it any more.
"""

from typing import Optional, List, Dict, Any

from ..base_db import DatabaseIntegrityError
from ..exceptions import ValidationError, TagError, QuestionAnalysisError
from ..models import Tag, QuestionAnalysis
from app_logging import ErrorCategory

# FROZEN — mirror of ``DEFAULT_DEFINITIONS`` in
# ``src/database/migrations/user/m010_default_tag_definitions.py``.
# Migrations never import live domain code, hence the deliberate
# duplication; ``tests/database/test_tag_management.py`` asserts the two
# maps stay identical. Covers every group and type name created by
# ``seed_default_tags`` below. If the seeded set changes, update both
# copies AND write a new migration for existing databases.
_DEFAULT_TAG_DEFINITIONS: Dict[str, str] = {
    # ------------------------------------------------------- groups
    'Knowledge Issues': "Mistakes caused by gaps or errors in what you know.",
    'Reading & Interpretation': "Mistakes from misreading or misinterpreting what the question asked.",
    'Execution Errors': "Mistakes made while working the problem, even though you knew the material.",
    'Test Strategy': "Mistakes in how you played the test itself — timing, guessing, and answer changes.",
    'Mental & Physical State': "Mistakes influenced by how you felt — stress, focus, or energy.",
    # ------------------------------------ types: Knowledge Issues
    'Knowledge Gap': "You never learned or covered this material.",
    'Memory Failure': "You studied this before but couldn't recall it when it mattered.",
    'Misunderstanding': "You learned the material but understood it incorrectly.",
    # --------------------------- types: Reading & Interpretation
    'Misread Question': "You misread or overlooked key wording in the question.",
    # ------------------------------------ types: Execution Errors
    'Calculation Error': "You set up the problem correctly but made an arithmetic slip.",
    'Careless Mistake': "You knew the answer but slipped through haste or inattention.",
    'Incomplete Solution': "You started down the right path but didn't carry the work to completion.",
    'Wrong Approach': "You chose a method or strategy that couldn't solve this problem.",
    # --------------------------------------- types: Test Strategy
    'Time Pressure': "Running low on time forced you to rush or abandon the question.",
    'Second-Guessing': "You changed a correct answer to a wrong one.",
    'Elimination Error': "You ruled out the correct answer while narrowing the choices.",
    'Poor Prioritization': "You spent your time on the wrong questions or in the wrong order.",
    'Wrong Guess Strategy': "You had to guess, and your guessing approach didn't pay off.",
    # ---------------------------- types: Mental & Physical State
    'Anxiety Related': "Nervousness or stress interfered with your thinking on this question.",
    'Focus Problem': "You lost concentration or got distracted while answering.",
    'Fatigue Related': "Tiredness or low energy dulled your performance on this question.",
}

# The defaults ``seed_default_tags`` puts in the library, by group, in order.
# Every name here MUST have an entry in _DEFAULT_TAG_DEFINITIONS above (and,
# mirrored, in m010's DEFAULT_DEFINITIONS and m038's copy).
_DEFAULT_TAG_GROUPS = (
    ('Knowledge Issues', '#EF4444',  # Red
     ('Knowledge Gap', 'Memory Failure', 'Misunderstanding')),
    ('Reading & Interpretation', '#F59E0B',  # Amber
     ('Misread Question',)),
    ('Execution Errors', '#10B981',  # Green
     ('Calculation Error', 'Careless Mistake', 'Incomplete Solution',
      'Wrong Approach')),
    ('Test Strategy', '#3B82F6',  # Blue
     ('Time Pressure', 'Second-Guessing', 'Elimination Error',
      'Poor Prioritization', 'Wrong Guess Strategy')),
    ('Mental & Physical State', '#8B5CF6',  # Purple
     ('Anxiety Related', 'Focus Problem', 'Fatigue Related')),
)


class TagsMixin:
    """Mixin for tags operations. Composed into UserDatabase."""

    VALID_TAG_CATEGORIES = {'mistake_type', 'study_method', 'content_type', 'difficulty', 'strategy', 'personal', 'other'}
    VALID_ASSIGNED_BY = {'user', 'auto_suggested'}

    # ------------------------------------------------------------------
    # The library and the exam's list (#888)
    # ------------------------------------------------------------------

    def _tag_exam_id(self, exam_context: Optional[str]) -> Optional[int]:
        """The id of this profile's exam named ``exam_context``, or None."""
        if not exam_context:
            return None
        row = self.fetchone(
            "SELECT id FROM exam_contexts WHERE user_id = ? AND exam_name = ?",
            (self.user_id, exam_context))
        return row['id'] if row else None

    def _require_tag_exam_id(self, exam_context: Optional[str]) -> int:
        exam_id = self._tag_exam_id(exam_context)
        if exam_id is None:
            raise TagError(f'There is no exam called "{exam_context}".')
        return exam_id

    def _find_library_tag(self, tag_name: str, parent_id: Optional[int],
                          is_group: bool) -> Optional[Dict[str, Any]]:
        """The library row on idx_unique_tag_in_group's key, active or not."""
        return self.fetchone(
            "SELECT * FROM tags WHERE IFNULL(parent_id, 0) = IFNULL(?, 0)"
            " AND tag_name = ? AND IFNULL(is_group, 0) = ?",
            (parent_id, tag_name, 1 if is_group else 0))

    def _is_listed(self, exam_id: int, tag_id: int) -> bool:
        return self.fetchone(
            "SELECT 1 FROM exam_error_types WHERE exam_context_id = ? AND tag_id = ?",
            (exam_id, tag_id)) is not None

    def _list_on_exam(self, exam_id: int, tag_id: int) -> int:
        """List a type on an exam, with every group above it. Idempotent.

        The picker draws groups first, so a listed type whose group is not
        listed could never be offered. Returns how many rows were added.
        """
        added = 0
        # The exam has now had a list, so seed_default_tags leaves it alone
        # from here on, even once every row is removed again.
        self.execute("INSERT OR IGNORE INTO exam_error_types_seeded"
                     " (exam_context_id) VALUES (?)", (exam_id,))
        current: Optional[int] = tag_id
        seen = set()
        while current is not None and current not in seen:
            seen.add(current)
            added += self.execute(
                "INSERT OR IGNORE INTO exam_error_types"
                " (exam_context_id, tag_id, display_order)"
                " SELECT ?, id, IFNULL(display_order, 0) FROM tags WHERE id = ?",
                (exam_id, current)).rowcount
            row = self.fetchone("SELECT parent_id FROM tags WHERE id = ?", (current,))
            current = row['parent_id'] if row else None
        return added

    def _tag_descendant_ids(self, tag_id: int, active_only: bool = False) -> List[int]:
        """Every row below ``tag_id`` in the library, nearest first."""
        found: List[int] = []
        frontier = [tag_id]
        active = " AND is_active = TRUE" if active_only else ""
        while frontier:
            marks = ",".join("?" * len(frontier))
            rows = self.fetchall(
                f"SELECT id FROM tags WHERE parent_id IN ({marks}){active}",
                tuple(frontier))
            frontier = [r['id'] for r in rows if r['id'] not in found]
            found.extend(frontier)
        return found

    def _next_tag_display_order(self, parent_id: Optional[int]) -> int:
        row = self.fetchone(
            "SELECT COALESCE(MAX(display_order), -1) + 1 AS next_order"
            " FROM tags WHERE parent_id IS ?", (parent_id,))
        return row['next_order']

    def _adopt_or_refuse(self, existing: Dict[str, Any], exam_id: Optional[int],
                         what: str) -> Tag:
        """The library already has this (group, name): list it, or refuse.

        Refused with a sentence when this exam already offers it, or when
        there is no exam to list it on, since the call could then only have
        meant a second copy (decision 1). Otherwise the existing row is
        listed on this exam and returned; no copy is made.
        """
        name = existing['tag_name']
        active = bool(existing.get('is_active', 1))
        if exam_id is None:
            raise TagError(f'"{name}" is already {what}.')
        if active and self._is_listed(exam_id, existing['id']):
            raise TagError(f'"{name}" is already {what} on this exam.')
        with self.transaction():
            if not active:
                self.execute("UPDATE tags SET is_active = TRUE,"
                             " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                             (existing['id'],))
            self._list_on_exam(exam_id, existing['id'])
        return self.get_tag(existing['id'])

    def create_tag(
        self,
        exam_context: str,
        tag_name: str,
        tag_category: str = 'other',
        color_hex: str = '#2196F3',
        description: Optional[str] = None
    ) -> Tag:
        """
        Create a top-level error type and list it on the exam ``exam_context``.

        If the library already has a top-level type of that name, that row is
        listed on the exam instead and no copy is made (#888 decision 1). A
        :class:`TagError` is raised when the exam already offers it.

        Args:
            exam_context: Name of the exam to list it on (4a: that exam only)
            tag_name: Name of the tag
            tag_category: Category of tag
            color_hex: Hex color for the tag
            description: Optional description

        Returns:
            The Tag (new, or the library row now listed on the exam)
        """
        if tag_category not in self.VALID_TAG_CATEGORIES:
            raise ValidationError(f"Invalid tag category: {tag_category}")

        # Validate hex color
        if not color_hex.startswith('#') or len(color_hex) != 7:
            raise ValidationError(f"Invalid hex color: {color_hex}")

        exam_id = self._tag_exam_id(exam_context)
        existing = self._find_library_tag(tag_name, None, False)
        if existing:
            return self._adopt_or_refuse(existing, exam_id, "an error type")

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO tags (
                        exam_context, tag_name, tag_category,
                        color_hex, description, is_active
                    ) VALUES (NULL, ?, ?, ?, ?, TRUE)
                """, (tag_name, tag_category, color_hex, description))

                tag_id = cursor.lastrowid
                if exam_id is not None:
                    self._list_on_exam(exam_id, tag_id)

                if self.error_logger:
                    self.error_logger.debug(
                        f"Created tag: {tag_name} (ID: {tag_id})",
                        category=ErrorCategory.DATABASE
                    )

                return self.get_tag(tag_id)

        except DatabaseIntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise TagError(f'"{tag_name}" is already an error type.') from e
            raise

    def get_tag(self, tag_id: int) -> Optional[Tag]:
        """Get tag by ID"""
        row = self.fetchone(
            "SELECT * FROM tags WHERE id = ? AND is_active = TRUE",
            (tag_id,)
        )
        return Tag.from_db_row(row) if row else None

    def get_tags_by_exam(
        self,
        exam_context: str,
        category: Optional[str] = None
    ) -> List[Tag]:
        """
        Get every active tag the exam ``exam_context`` lists (#888).

        Args:
            exam_context: Exam name
            category: Optional category filter

        Returns:
            List of Tag objects
        """
        if category and category not in self.VALID_TAG_CATEGORIES:
            raise ValidationError(f"Invalid tag category: {category}")

        exam_id = self._tag_exam_id(exam_context)
        if exam_id is None:
            return []

        query = """
            SELECT t.* FROM tags t
            JOIN exam_error_types l ON l.tag_id = t.id AND l.exam_context_id = ?
            WHERE t.is_active = TRUE
        """
        params: tuple = (exam_id,)
        if category:
            query += " AND t.tag_category = ?"
            params += (category,)
        query += " ORDER BY t.usage_count DESC, t.tag_name"

        rows = self.fetchall(query, params)
        return [Tag.from_db_row(row) for row in rows]

    def tag_question(
        self,
        question_id: int,
        tag_ids: List[int],
        assigned_by: str = 'user'
    ) -> None:
        """
        Apply tags to a question.

        Args:
            question_id: Question analysis ID
            tag_ids: List of tag IDs to apply
            assigned_by: Who assigned the tag ('user' or 'auto_suggestion')
        """
        if assigned_by not in self.VALID_ASSIGNED_BY:
            raise ValidationError(f"Invalid assigned_by value: {assigned_by}")

        # Get question to verify it exists and get exam context
        question = self.get_question_analysis(question_id)
        if not question:
            raise QuestionAnalysisError(f"Question {question_id} not found")

        with self.transaction():
            for tag_id in tag_ids:
                # Verify tag exists
                tag = self.get_tag(tag_id)
                if not tag:
                    raise TagError(f"Tag {tag_id} not found")

                # Check if tag already applied
                existing = self.fetchone("""
                    SELECT id FROM question_tags
                    WHERE question_analysis_id = ? AND tag_id = ?
                """, (question_id, tag_id))

                if not existing:
                    # Apply tag
                    self.execute("""
                        INSERT INTO question_tags (
                            question_analysis_id, tag_id, exam_context, assigned_by
                        ) VALUES (?, ?, ?, ?)
                    """, (question_id, tag_id, question.exam_context, assigned_by))

                    # Update tag usage count
                    self.execute("""
                        UPDATE tags
                        SET usage_count = usage_count + 1,
                            last_used_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (tag_id,))

    def get_questions_by_tag(
        self,
        tag_id: int,
        limit: Optional[int] = None
    ) -> List[QuestionAnalysis]:
        """
        Get questions with a specific tag.

        Args:
            tag_id: Tag ID
            limit: Maximum number of questions to return

        Returns:
            List of QuestionAnalysis objects
        """
        query = """
            SELECT qa.*
            FROM question_analyses qa
            JOIN question_tags qt ON qa.id = qt.question_analysis_id
            WHERE qt.tag_id = ?
            ORDER BY qt.assigned_at DESC
        """

        if limit:
            query += f" LIMIT {limit}"

        rows = self.fetchall(query, (tag_id,))
        return [QuestionAnalysis.from_db_row(row) for row in rows]


    def create_tag_group(
        self,
        exam_context: str,
        group_name: str,
        parent_id: Optional[int] = None,
        color_hex: str = '#6B7280',
        description: Optional[str] = None
    ) -> 'Tag':
        """
        Create a tag group (folder for organizing tags) and list it on the exam.

        A group of that name already in the library (under the same parent)
        is listed on the exam instead of being copied (#888 decision 1).

        Args:
            exam_context: Name of the exam to list the group on
            group_name: Name of the group
            parent_id: Optional parent group ID (for nested groups)
            color_hex: Color for the group
            description: Optional description

        Returns:
            Tag object with is_group=True
        """
        self._ensure_phase4_schema()

        # Check nesting depth (max 3 levels)
        if parent_id:
            depth = self._get_tag_depth(parent_id)
            if depth >= 2:  # 0-indexed, so 2 means we're already at level 3
                raise TagError("Maximum tag hierarchy depth (3 levels) exceeded")

        exam_id = self._tag_exam_id(exam_context)
        existing = self._find_library_tag(group_name, parent_id, True)
        if existing:
            return self._adopt_or_refuse(existing, exam_id, "a group")

        display_order = self._next_tag_display_order(parent_id)

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO tags (
                        exam_context, tag_name, tag_category, color_hex,
                        description, is_active, parent_id, is_group, display_order
                    ) VALUES (NULL, ?, 'other', ?, ?, TRUE, ?, TRUE, ?)
                """, (
                    group_name, color_hex, description,
                    parent_id, display_order
                ))
                group_id = cursor.lastrowid
                if exam_id is not None:
                    self._list_on_exam(exam_id, group_id)

                return self.get_tag(group_id)

        except DatabaseIntegrityError as e:
            raise TagError(f"Failed to create tag group: {e}") from e

    def create_hierarchical_tag(
        self,
        exam_context: str,
        tag_name: str,
        group_id: int,
        color_hex: str = '#2196F3',
        description: Optional[str] = None
    ) -> 'Tag':
        """
        Create a tag within a group and list it on the exam ``exam_context``.

        4a (#888): the new type is listed on that exam only. If the group
        already holds a type of that name in the library, that row is listed
        on the exam instead (its shared definition is kept); if this exam
        already offers it, a :class:`TagError` says so.

        Args:
            exam_context: Name of the exam to list it on
            tag_name: Name of the tag
            group_id: ID of the parent group
            color_hex: Color for the tag
            description: Optional description

        Returns:
            Tag object
        """
        self._ensure_phase4_schema()

        # Validate parent is a group
        parent = self.get_tag(group_id)
        if not parent:
            raise TagError(f"Parent group {group_id} not found")

        # Check nesting depth
        depth = self._get_tag_depth(group_id)
        if depth >= 2:
            raise TagError("Maximum tag hierarchy depth (3 levels) exceeded")

        exam_id = self._tag_exam_id(exam_context)
        existing = self._find_library_tag(tag_name, group_id, False)
        if existing:
            return self._adopt_or_refuse(
                existing, exam_id, f"an error type in {parent.tag_name}")

        display_order = self._next_tag_display_order(group_id)

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO tags (
                        exam_context, tag_name, tag_category, color_hex,
                        description, is_active, parent_id, is_group, display_order
                    ) VALUES (NULL, ?, 'mistake_type', ?, ?, TRUE, ?, FALSE, ?)
                """, (
                    tag_name, color_hex, description,
                    group_id, display_order
                ))
                tag_id = cursor.lastrowid
                if exam_id is not None:
                    self._list_on_exam(exam_id, tag_id)

                return self.get_tag(tag_id)

        except DatabaseIntegrityError as e:
            raise TagError(f"Failed to create tag: {e}") from e

    def _get_tag_depth(self, tag_id: int) -> int:
        """Get the depth of a tag in the hierarchy (0 = root level)"""
        depth = 0
        current_id = tag_id

        while current_id:
            row = self.fetchone(
                "SELECT parent_id FROM tags WHERE id = ?",
                (current_id,)
            )
            if not row or row['parent_id'] is None:
                break
            current_id = row['parent_id']
            depth += 1
            if depth > 10:  # Safety check
                break

        return depth

    def get_tag_usage_count(self, tag_id: int) -> int:
        """
        Get the LIVE number of question entries tagged with a tag.

        Counts ``entry_tags`` rows directly — the ``tags.usage_count``
        column is stale (only the legacy ``question_tags`` path ever
        incremented it) and must not be trusted for display.

        Args:
            tag_id: Tag ID

        Returns:
            Number of entries currently tagged with this tag
        """
        self._ensure_phase4_schema()

        row = self.fetchone(
            "SELECT COUNT(*) as count FROM entry_tags WHERE tag_id = ?",
            (tag_id,)
        )
        return row['count'] if row else 0

    def update_tag_description(self, tag_id: int, description: Optional[str]) -> Tag:
        """
        Update a tag's description (student-facing definition).

        Args:
            tag_id: Tag ID
            description: New description; empty/whitespace-only strings
                are normalized to NULL (clears the definition)

        Returns:
            Refreshed Tag object

        Raises:
            TagError: If the tag does not exist
        """
        tag = self.get_tag(tag_id)
        if not tag:
            raise TagError(f"Tag {tag_id} not found")

        normalized = description.strip() if description else None
        if not normalized:
            normalized = None

        with self.transaction():
            self.execute("""
                UPDATE tags
                SET description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (normalized, tag_id))

        if self.error_logger:
            self.error_logger.debug(
                f"Updated description for tag {tag_id} ({tag.tag_name})",
                category=ErrorCategory.DATABASE
            )

        return self.get_tag(tag_id)


    def delete_tag(self, tag_id: int, exam_context: Optional[str] = None) -> Dict[str, Any]:
        """
        Delete for good: remove a type (or an EMPTY group) from the library.

        ``entry_tags.tag_id`` and legacy ``question_tags.tag_id`` both
        declare ``ON DELETE CASCADE``, so the delete untags the tag on every
        entry in EVERY exam, and every exam's list loses it by the same
        cascade. That is why #888's decision 4b offers it only once no other
        exam lists the type:

        * with ``exam_context``, it is refused if any exam other than that
          one lists the type;
        * without it, it is refused if more than one exam lists the type.

        Groups with active children are refused as before. ``tags.parent_id``
        carries no ON DELETE action, so deleting a populated group would
        FK-error anyway; the guard gives a clean, actionable message. The
        everyday action is :meth:`remove_tag_from_exam`, which deletes nothing.

        Args:
            tag_id: Tag ID
            exam_context: The exam the student is deleting it from, if any

        Returns:
            Dict with 'id', 'name', and 'affected_entries' (number of
            entries, across every exam, that were untagged by the delete)

        Raises:
            TagError: If the tag does not exist, is a group that still
                contains active types, or another exam still lists it
        """
        self._ensure_phase4_schema()

        tag = self.get_tag(tag_id)
        if not tag:
            raise TagError(f"Tag {tag_id} not found")

        # Tag model doesn't carry is_group — read it directly.
        row = self.fetchone("SELECT is_group FROM tags WHERE id = ?", (tag_id,))
        if row and row.get('is_group'):
            child_row = self.fetchone("""
                SELECT COUNT(*) as count FROM tags
                WHERE parent_id = ? AND is_active = TRUE
            """, (tag_id,))
            child_count = child_row['count'] if child_row else 0
            if child_count > 0:
                raise TagError(
                    f"Group '{tag.tag_name}' contains {child_count} types; "
                    f"delete or move them first"
                )

        listers = self.fetchall("""
            SELECT ec.id, ec.exam_name FROM exam_error_types l
            JOIN exam_contexts ec ON ec.id = l.exam_context_id
            WHERE l.tag_id = ? ORDER BY ec.exam_name
        """, (tag_id,))
        if exam_context:
            exam_id = self._tag_exam_id(exam_context)
            others = [r['exam_name'] for r in listers if r['id'] != exam_id]
        else:
            others = [r['exam_name'] for r in listers] if len(listers) > 1 else []
        if others:
            names = ", ".join(f'"{n}"' for n in others)
            raise TagError(
                f'"{tag.tag_name}" is still offered on {names}. Deleting it for '
                f'good would take it off that exam\'s entries too, so remove it '
                f'from there first, or use Remove from this exam.')

        affected = self.get_tag_usage_count(tag_id)

        with self.transaction():
            self.execute("DELETE FROM tags WHERE id = ?", (tag_id,))

        if self.error_logger:
            self.error_logger.info(
                f"Deleted tag {tag_id} ({tag.tag_name}) for good, "
                f"untagged {affected} entries",
                category=ErrorCategory.DATABASE
            )

        return {
            'id': tag_id,
            'name': tag.tag_name,
            'affected_entries': affected
        }

    def add_tag_to_exam(self, exam_context: str, tag_id: int) -> Dict[str, Any]:
        """
        List a library type on an exam ("Add from your other exams", #888 4a).

        A type brings its group. A group brings every active type in it, which
        is what adding a whole group means.

        Returns:
            Dict with 'id', 'name', 'is_group' and 'added' (list rows made)

        Raises:
            TagError: If there is no such exam or no such active type
        """
        exam_id = self._require_tag_exam_id(exam_context)
        row = self.fetchone(
            "SELECT * FROM tags WHERE id = ? AND is_active = TRUE", (tag_id,))
        if not row:
            raise TagError(f"Error type {tag_id} not found")

        is_group = bool(row.get('is_group'))
        ids = [tag_id] + (self._tag_descendant_ids(tag_id, active_only=True)
                          if is_group else [])
        with self.transaction():
            added = sum(self._list_on_exam(exam_id, t) for t in ids)

        if self.error_logger:
            self.error_logger.info(
                f"Listed error type {tag_id} ({row['tag_name']}) on exam "
                f"{exam_id}: {added} rows",
                category=ErrorCategory.DATABASE
            )
        return {'id': tag_id, 'name': row['tag_name'], 'is_group': is_group,
                'added': added}

    def remove_tag_from_exam(self, exam_context: str, tag_id: int) -> Dict[str, Any]:
        """
        Remove from this exam: stop offering a type on one exam (#888).

        Deletes the exam's list row and nothing else. Entries that carry the
        type keep it, on this exam and every other, and analytics still count
        it. A group takes the types listed under it on this exam with it.

        Returns:
            Dict with 'id', 'name', 'is_group', 'removed' (list rows deleted)
            and 'entries_keeping' (this exam's entries that still carry it)

        Raises:
            TagError: If there is no such exam, or it does not list the type
        """
        exam_id = self._require_tag_exam_id(exam_context)
        row = self.fetchone("SELECT * FROM tags WHERE id = ?", (tag_id,))
        if not row or not self._is_listed(exam_id, tag_id):
            name = row['tag_name'] if row else f"Error type {tag_id}"
            raise TagError(f'"{name}" is not offered on this exam.')

        is_group = bool(row.get('is_group'))
        ids = [tag_id] + (self._tag_descendant_ids(tag_id) if is_group else [])
        marks = ",".join("?" * len(ids))
        kept = self.fetchone(f"""
            SELECT COUNT(DISTINCT et.question_entry_id) AS n FROM entry_tags et
            JOIN question_entries qe ON qe.id = et.question_entry_id
            JOIN review_sessions rs ON rs.id = qe.review_session_id
            WHERE rs.exam_context_id = ? AND et.tag_id IN ({marks})
        """, (exam_id, *ids))['n']

        with self.transaction():
            removed = self.execute(
                f"DELETE FROM exam_error_types WHERE exam_context_id = ?"
                f" AND tag_id IN ({marks})", (exam_id, *ids)).rowcount

        if self.error_logger:
            self.error_logger.info(
                f"Removed error type {tag_id} ({row['tag_name']}) from exam "
                f"{exam_id}: {removed} rows; {kept} entries keep it",
                category=ErrorCategory.DATABASE
            )
        return {'id': tag_id, 'name': row['tag_name'], 'is_group': is_group,
                'removed': removed, 'entries_keeping': kept}

    def get_tags_not_on_exam(self, exam_context: str) -> List[Dict[str, Any]]:
        """
        The library's types and groups this exam does not offer, as a tree.

        For "Add from your other exams" (#888 4a). A group appears when it is
        not listed itself or holds a type that is not; ``listed`` says which.
        Each node carries ``exam_count`` (exams that list it) and
        ``entry_count_all`` (entries carrying it, in any exam).

        Raises:
            TagError: If there is no such exam
        """
        exam_id = self._require_tag_exam_id(exam_context)
        rows = self.fetchall("""
            SELECT t.*,
                (SELECT COUNT(*) FROM exam_error_types o
                 WHERE o.tag_id = t.id) AS exam_count,
                (SELECT COUNT(*) FROM entry_tags et
                 WHERE et.tag_id = t.id) AS entry_count_all,
                EXISTS (SELECT 1 FROM exam_error_types l
                        WHERE l.tag_id = t.id AND l.exam_context_id = ?) AS listed
            FROM tags t
            WHERE t.is_active = TRUE
            ORDER BY t.display_order, t.tag_name
        """, (exam_id,))
        by_parent: Dict[Optional[int], List[Dict[str, Any]]] = {}
        for row in rows:
            by_parent.setdefault(row['parent_id'], []).append(row)

        def build(parent_id: Optional[int]) -> List[Dict[str, Any]]:
            out = []
            for row in by_parent.get(parent_id, []):
                is_group = bool(row.get('is_group'))
                children = build(row['id']) if is_group else []
                if row['listed'] and not children:
                    continue
                out.append({
                    'id': row['id'],
                    'name': row['tag_name'],
                    'color': row['color_hex'],
                    'description': row['description'],
                    'is_group': is_group,
                    'listed': bool(row['listed']),
                    'exam_count': row['exam_count'],
                    'entry_count_all': row['entry_count_all'],
                    'children': children,
                })
            return out

        return build(None)

    def get_tag_hierarchy(self, exam_context: str) -> List[Dict[str, Any]]:
        """
        Get the tag hierarchy the exam ``exam_context`` lists (#888).

        Reads through ``exam_error_types``: a library type this exam does not
        list is absent, even when one of its entries carries it.

        Per node:

        * ``usage_count`` -- this exam's entries carrying it, counted LIVE
          from ``entry_tags`` (the ``tags.usage_count`` column is stale);
        * ``entry_count_all`` -- entries carrying it in ANY exam, which is
          what Delete for good would untag;
        * ``other_exam_count`` -- how many OTHER exams list it. Delete for
          good is offered only when this is 0 (4b);
        * ``library_child_count`` -- active types under a group in the whole
          library, listed here or not. A group with any cannot be deleted.

        Group nodes add their listed children's ``usage_count`` and
        ``entry_count_all`` to their own (normally zero).

        Args:
            exam_context: Exam name

        Returns:
            List of tag groups with nested children
        """
        self._ensure_phase4_schema()

        exam_id = self._tag_exam_id(exam_context)
        if exam_id is None:
            return []

        def build_tree(parent_id: Optional[int]) -> List[Dict[str, Any]]:
            rows = self.fetchall("""
                SELECT t.*,
                    (SELECT COUNT(*) FROM entry_tags et
                     JOIN question_entries qe ON qe.id = et.question_entry_id
                     JOIN review_sessions rs ON rs.id = qe.review_session_id
                     WHERE et.tag_id = t.id AND rs.exam_context_id = ?)
                        AS live_usage_count,
                    (SELECT COUNT(*) FROM entry_tags et
                     WHERE et.tag_id = t.id) AS entry_count_all,
                    (SELECT COUNT(*) FROM exam_error_types o
                     WHERE o.tag_id = t.id AND o.exam_context_id != ?)
                        AS other_exam_count,
                    (SELECT COUNT(*) FROM tags c
                     WHERE c.parent_id = t.id AND c.is_active = TRUE)
                        AS library_child_count
                FROM tags t
                JOIN exam_error_types l
                    ON l.tag_id = t.id AND l.exam_context_id = ?
                WHERE t.parent_id IS ? AND t.is_active = TRUE
                ORDER BY l.display_order, t.tag_name
            """, (exam_id, exam_id, exam_id, parent_id))

            result = []
            for row in rows:
                tag_dict = {
                    'id': row['id'],
                    'name': row['tag_name'],
                    'color': row['color_hex'],
                    'description': row['description'],
                    'is_group': bool(row.get('is_group', False)),
                    'usage_count': row['live_usage_count'],
                    'entry_count_all': row['entry_count_all'],
                    'other_exam_count': row['other_exam_count'],
                    'library_child_count': row['library_child_count'],
                    'children': []
                }

                if tag_dict['is_group']:
                    tag_dict['children'] = build_tree(row['id'])
                    # Groups aggregate their children's live counts.
                    tag_dict['usage_count'] += sum(
                        child['usage_count'] for child in tag_dict['children']
                    )
                    tag_dict['entry_count_all'] += sum(
                        child['entry_count_all'] for child in tag_dict['children']
                    )

                result.append(tag_dict)

            return result

        return build_tree(None)

    #: The synthetic group :meth:`get_error_types_for_filter` gathers
    #: carried-but-unlisted types under. Its ``id`` is None: it is not a row.
    NOT_LISTED_GROUP_NAME = 'No longer on this exam'

    def get_error_types_for_filter(self, exam_id: int) -> List[Dict[str, Any]]:
        """The entry browser's error-type list: what the exam lists, plus
        every type its entries carry that it no longer lists (#898).

        The exam's list decides only what can be *added* to an entry (#888):
        an entry keeps a type after *Remove from this exam*, and the
        difficulty and time card still counts it. A filter built from
        :meth:`get_tag_hierarchy` alone could not find those entries, and
        ``applyTagFilter`` dropped such a type on Apply because it had no
        checkbox. So:

        * the listed hierarchy comes first, exactly as
          :meth:`get_tag_hierarchy` returns it, each node marked
          ``listed_on_exam: True``;
        * then, only when there is at least one, a synthetic group with
          ``id: None``, ``not_listed_group: True`` and the name
          :attr:`NOT_LISTED_GROUP_NAME`, whose children are the types (never
          groups) carried by this exam's entries and absent from the
          hierarchy above, each ``listed_on_exam: False`` (or True for a
          listed row the hierarchy hides as inactive), with ``group_name``
          naming its library group and ``usage_count`` counting this exam's
          entries carrying it.

        "Absent from the hierarchy" rather than "not in exam_error_types",
        so that anything the card counts and the list does not show still
        gets a checkbox.

        Args:
            exam_id: The exam's id (not its name).

        Returns:
            List of group (and ungrouped type) nodes, as get_tag_hierarchy.
        """
        row = self.fetchone(
            "SELECT exam_name FROM exam_contexts WHERE id = ? AND user_id = ?",
            (exam_id, self.user_id))
        if not row:
            return []
        hierarchy = self.get_tag_hierarchy(row['exam_name'])

        shown = set()

        def mark(nodes: List[Dict[str, Any]]) -> None:
            for node in nodes:
                node['listed_on_exam'] = True
                shown.add(node['id'])
                mark(node.get('children') or [])

        mark(hierarchy)

        carried = self.fetchall("""
            SELECT t.id, t.tag_name, t.color_hex, t.description,
                   g.tag_name AS group_name,
                   COUNT(DISTINCT et.question_entry_id) AS usage_count,
                   EXISTS (SELECT 1 FROM exam_error_types x
                           WHERE x.exam_context_id = ? AND x.tag_id = t.id)
                       AS listed
            FROM entry_tags et
            JOIN tags t ON t.id = et.tag_id
            LEFT JOIN tags g ON g.id = t.parent_id
            JOIN question_entries qe ON qe.id = et.question_entry_id
            JOIN review_sessions rs ON rs.id = qe.review_session_id
            WHERE rs.exam_context_id = ? AND rs.user_id = ?
              AND IFNULL(t.is_group, 0) = 0
            GROUP BY t.id
            ORDER BY t.tag_name, t.id
        """, (exam_id, exam_id, self.user_id))

        missing = [
            {
                'id': r['id'],
                'name': r['tag_name'],
                'color': r['color_hex'],
                'description': r['description'],
                'is_group': False,
                'usage_count': r['usage_count'],
                'group_name': r['group_name'],
                'listed_on_exam': bool(r['listed']),
                'children': [],
            }
            for r in carried if r['id'] not in shown
        ]
        if missing:
            hierarchy.append({
                'id': None,
                'name': self.NOT_LISTED_GROUP_NAME,
                'color': None,
                'description': None,
                'is_group': True,
                'not_listed_group': True,
                'listed_on_exam': False,
                'usage_count': sum(t['usage_count'] for t in missing),
                'children': missing,
            })
        return hierarchy

    def seed_default_tags(self, exam_context: str) -> None:
        """
        Put the defaults in the library and offer them on ``exam_context`` (#888).

        * The library gains whichever of the 5 default groups and 16 default
          types it lacks, matched on (group name, type name). None is copied.
        * The exam named ``exam_context`` then lists every default group and
          type, but only if it has never had a list
          (``exam_error_types_seeded``). An exam the student has shaped is
          left alone, and so is one whose list they emptied on purpose with
          *Remove from this exam*: that list stays empty.

        The entry form calls this whenever an exam's picker comes up empty,
        which includes every reload after the last group is removed, so the
        question is "has this exam ever had a list", never "is it empty now".
        Idempotent.

        Args:
            exam_context: Name of the exam to offer the defaults on
        """
        self._ensure_phase4_schema()

        exam_id = self._tag_exam_id(exam_context)
        if exam_id is not None and self.fetchone(
                "SELECT 1 FROM exam_error_types_seeded WHERE exam_context_id = ?"
                " UNION ALL SELECT 1 FROM exam_error_types"
                " WHERE exam_context_id = ? LIMIT 1",
                (exam_id, exam_id)):
            return  # This exam has had a list: it is not new.

        default_ids: List[int] = []
        with self.transaction():
            for group_name, color, type_names in _DEFAULT_TAG_GROUPS:
                group_id = self._ensure_library_default(
                    group_name, None, True, color)
                default_ids.append(group_id)
                for tag_name in type_names:
                    default_ids.append(self._ensure_library_default(
                        tag_name, group_id, False, color))
            if exam_id is not None:
                for tag_id in default_ids:
                    self._list_on_exam(exam_id, tag_id)

        if self.error_logger:
            self.error_logger.info(
                f"Seeded default tags for exam context: {exam_context}",
                category=ErrorCategory.DATABASE
            )

    def _ensure_library_default(self, name: str, parent_id: Optional[int],
                                is_group: bool, color: str) -> int:
        """The library row for one default, created (or reactivated) if needed."""
        existing = self._find_library_tag(name, parent_id, is_group)
        if existing:
            if not existing.get('is_active', 1):
                self.execute("UPDATE tags SET is_active = TRUE,"
                             " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                             (existing['id'],))
            return existing['id']
        return self.execute("""
            INSERT INTO tags (
                exam_context, tag_name, tag_category, color_hex,
                description, is_active, parent_id, is_group, display_order
            ) VALUES (NULL, ?, ?, ?, ?, TRUE, ?, ?, ?)
        """, (
            name, 'other' if is_group else 'mistake_type', color,
            _DEFAULT_TAG_DEFINITIONS.get(name), parent_id, is_group,
            self._next_tag_display_order(parent_id),
        )).lastrowid
