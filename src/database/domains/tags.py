"""WIMI Tags database operations."""

from typing import Optional, List, Dict, Any

from ..base_db import DatabaseIntegrityError
from ..exceptions import ValidationError, TagError, QuestionAnalysisError
from ..models import Tag, QuestionAnalysis
from app_logging import ErrorCategory


class TagsMixin:
    """Mixin for tags operations. Composed into UserDatabase."""

    VALID_TAG_CATEGORIES = {'mistake_type', 'study_method', 'content_type', 'difficulty', 'strategy', 'personal', 'other'}
    VALID_ASSIGNED_BY = {'user', 'auto_suggested'}

    def create_tag(
        self,
        exam_context: str,
        tag_name: str,
        tag_category: str = 'other',
        color_hex: str = '#2196F3',
        description: Optional[str] = None
    ) -> Tag:
        """
        Create a new tag.

        Args:
            exam_context: Exam code
            tag_name: Name of the tag
            tag_category: Category of tag
            color_hex: Hex color for the tag
            description: Optional description

        Returns:
            Created Tag object
        """
        if tag_category not in self.VALID_TAG_CATEGORIES:
            raise ValidationError(f"Invalid tag category: {tag_category}")

        # Validate hex color
        if not color_hex.startswith('#') or len(color_hex) != 7:
            raise ValidationError(f"Invalid hex color: {color_hex}")

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO tags (
                        exam_context, tag_name, tag_category,
                        color_hex, description, is_active
                    ) VALUES (?, ?, ?, ?, ?, TRUE)
                """, (exam_context, tag_name, tag_category, color_hex, description))

                tag_id = cursor.lastrowid

                if self.error_logger:
                    self.error_logger.debug(
                        f"Created tag: {tag_name} (ID: {tag_id})",
                        category=ErrorCategory.DATABASE
                    )

                return self.get_tag(tag_id)

        except DatabaseIntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise TagError(
                    f"Tag already exists: {exam_context}/{tag_name}"
                ) from e
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
        Get all tags for an exam context.

        Args:
            exam_context: Exam code
            category: Optional category filter

        Returns:
            List of Tag objects
        """
        if category:
            if category not in self.VALID_TAG_CATEGORIES:
                raise ValidationError(f"Invalid tag category: {category}")

            query = """
                SELECT * FROM tags
                WHERE exam_context = ? AND tag_category = ? AND is_active = TRUE
                ORDER BY usage_count DESC, tag_name
            """
            params = (exam_context, category)
        else:
            query = """
                SELECT * FROM tags
                WHERE exam_context = ? AND is_active = TRUE
                ORDER BY usage_count DESC, tag_name
            """
            params = (exam_context,)

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
        Create a tag group (folder for organizing tags).

        Args:
            exam_context: Exam context code
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

        # Get next display order
        row = self.fetchone("""
            SELECT COALESCE(MAX(display_order), -1) + 1 as next_order
            FROM tags WHERE exam_context = ? AND parent_id IS ?
        """, (exam_context, parent_id))
        display_order = row['next_order']

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO tags (
                        exam_context, tag_name, tag_category, color_hex,
                        description, is_active, parent_id, is_group, display_order
                    ) VALUES (?, ?, 'other', ?, ?, TRUE, ?, TRUE, ?)
                """, (
                    exam_context, group_name, color_hex, description,
                    parent_id, display_order
                ))

                return self.get_tag(cursor.lastrowid)

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
        Create a tag within a group.

        Args:
            exam_context: Exam context code
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

        # Get next display order
        row = self.fetchone("""
            SELECT COALESCE(MAX(display_order), -1) + 1 as next_order
            FROM tags WHERE exam_context = ? AND parent_id = ?
        """, (exam_context, group_id))
        display_order = row['next_order']

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO tags (
                        exam_context, tag_name, tag_category, color_hex,
                        description, is_active, parent_id, is_group, display_order
                    ) VALUES (?, ?, 'mistake_type', ?, ?, TRUE, ?, FALSE, ?)
                """, (
                    exam_context, tag_name, color_hex, description,
                    group_id, display_order
                ))

                return self.get_tag(cursor.lastrowid)

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

    def get_tag_hierarchy(self, exam_context: str) -> List[Dict[str, Any]]:
        """
        Get the full tag hierarchy for an exam context.

        Args:
            exam_context: Exam context code

        Returns:
            List of tag groups with nested children
        """
        self._ensure_phase4_schema()

        def build_tree(parent_id: Optional[int]) -> List[Dict[str, Any]]:
            if parent_id is None:
                rows = self.fetchall("""
                    SELECT * FROM tags
                    WHERE exam_context = ? AND parent_id IS NULL AND is_active = TRUE
                    ORDER BY display_order, tag_name
                """, (exam_context,))
            else:
                rows = self.fetchall("""
                    SELECT * FROM tags
                    WHERE exam_context = ? AND parent_id = ? AND is_active = TRUE
                    ORDER BY display_order, tag_name
                """, (exam_context, parent_id))

            result = []
            for row in rows:
                tag_dict = {
                    'id': row['id'],
                    'name': row['tag_name'],
                    'color': row['color_hex'],
                    'description': row['description'],
                    'is_group': bool(row.get('is_group', False)),
                    'usage_count': row.get('usage_count', 0),
                    'children': []
                }

                if tag_dict['is_group']:
                    tag_dict['children'] = build_tree(row['id'])

                result.append(tag_dict)

            return result

        return build_tree(None)

    def seed_default_tags(self, exam_context: str) -> None:
        """
        Seed default mistake category tags for an exam context.

        Args:
            exam_context: Exam context code
        """
        self._ensure_phase4_schema()

        # Check if tags already exist for this exam
        existing = self.fetchone(
            "SELECT COUNT(*) as count FROM tags WHERE exam_context = ?",
            (exam_context,)
        )
        if existing and existing['count'] > 0:
            return  # Already seeded

        # Default tag structure
        default_tags = {
            'Knowledge Issues': {
                'color': '#EF4444',  # Red
                'tags': ['Knowledge Gap', 'Memory Failure', 'Misunderstanding']
            },
            'Reading & Interpretation': {
                'color': '#F59E0B',  # Amber
                'tags': ['Misread Question']
            },
            'Execution Errors': {
                'color': '#10B981',  # Green
                'tags': ['Calculation Error', 'Careless Mistake', 'Incomplete Solution', 'Wrong Approach']
            },
            'Test Strategy': {
                'color': '#3B82F6',  # Blue
                'tags': ['Time Pressure', 'Second-Guessing', 'Elimination Error', 'Poor Prioritization', 'Wrong Guess Strategy']
            },
            'Mental & Physical State': {
                'color': '#8B5CF6',  # Purple
                'tags': ['Anxiety Related', 'Focus Problem', 'Fatigue Related']
            }
        }

        with self.transaction():
            for group_name, group_data in default_tags.items():
                # Create group
                group = self.create_tag_group(
                    exam_context=exam_context,
                    group_name=group_name,
                    color_hex=group_data['color']
                )

                # Create tags within group
                for tag_name in group_data['tags']:
                    self.create_hierarchical_tag(
                        exam_context=exam_context,
                        tag_name=tag_name,
                        group_id=group.id,
                        color_hex=group_data['color']
                    )

        if self.error_logger:
            self.error_logger.info(
                f"Seeded default tags for exam context: {exam_context}",
                category=ErrorCategory.DATABASE
            )
