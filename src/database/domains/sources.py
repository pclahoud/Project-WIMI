"""WIMI Sources database operations."""

from typing import Optional, List

from ..base_db import DatabaseIntegrityError
from ..exceptions import ValidationError
from app_logging import ErrorCategory


class SourcesMixin:
    """Mixin for sources operations. Composed into UserDatabase."""

    def create_question_source(
        self,
        source_name: str,
        source_type: str = 'other',
        exam_context: Optional[str] = None,
        description: Optional[str] = None,
        url: Optional[str] = None,
        total_questions: Optional[int] = None,
        user_rating: Optional[int] = None
    ) -> 'QuestionSource':
        """
        Create a new question source.

        Args:
            source_name: Name of the source (e.g., "UWorld", "Kaplan")
            source_type: Type of source
            exam_context: Optional exam context association
            description: Optional description
            url: Optional URL
            total_questions: Optional total question count
            user_rating: Optional rating (1-5)

        Returns:
            QuestionSource object
        """
        from ..models import QuestionSource
        from ..exceptions import QuestionSourceError

        self._ensure_phase4_schema()

        # Validate source type
        valid_types = QuestionSource.VALID_SOURCE_TYPES
        if source_type not in valid_types:
            raise ValidationError(f"Invalid source type: {source_type}. Must be one of {valid_types}")

        # Validate rating
        if user_rating is not None and not (1 <= user_rating <= 5):
            raise ValidationError("User rating must be between 1 and 5")

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO question_sources (
                        user_id, source_name, source_type, exam_context,
                        description, url, total_questions, user_rating
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.user_id, source_name, source_type, exam_context,
                    description, url, total_questions, user_rating
                ))

                source_id = cursor.lastrowid

                if self.error_logger:
                    self.error_logger.debug(
                        f"Created question source: {source_name} (ID: {source_id})",
                        category=ErrorCategory.DATABASE
                    )

                return self.get_question_source(source_id)

        except DatabaseIntegrityError as e:
            raise QuestionSourceError(f"Failed to create question source: {e}") from e

    def get_question_source(self, source_id: int) -> Optional['QuestionSource']:
        """Get question source by ID"""
        from ..models import QuestionSource

        row = self.fetchone(
            "SELECT * FROM question_sources WHERE id = ? AND is_active = TRUE",
            (source_id,)
        )
        return QuestionSource.from_db_row(row) if row else None

    def get_question_sources(
        self,
        exam_context: Optional[str] = None,
        include_inactive: bool = False
    ) -> List['QuestionSource']:
        """
        Get all question sources for the user.

        Args:
            exam_context: Optional filter by exam context
            include_inactive: Include inactive sources

        Returns:
            List of QuestionSource objects
        """
        from ..models import QuestionSource

        self._ensure_phase4_schema()

        query = "SELECT * FROM question_sources WHERE user_id = ?"
        params = [self.user_id]

        if not include_inactive:
            query += " AND is_active = TRUE"

        if exam_context:
            query += " AND (exam_context = ? OR exam_context IS NULL)"
            params.append(exam_context)

        query += " ORDER BY source_name"

        rows = self.fetchall(query, tuple(params))
        return [QuestionSource.from_db_row(row) for row in rows]

    def update_question_source(
        self,
        source_id: int,
        **kwargs
    ) -> 'QuestionSource':
        """
        Update a question source.

        Args:
            source_id: ID of the source to update
            **kwargs: Fields to update

        Returns:
            Updated QuestionSource object
        """
        from ..models import QuestionSource

        # Validate source type if provided
        if 'source_type' in kwargs:
            valid_types = QuestionSource.VALID_SOURCE_TYPES
            if kwargs['source_type'] not in valid_types:
                raise ValidationError(f"Invalid source type. Must be one of {valid_types}")

        # Validate rating if provided
        if 'user_rating' in kwargs and kwargs['user_rating'] is not None:
            if not (1 <= kwargs['user_rating'] <= 5):
                raise ValidationError("User rating must be between 1 and 5")

        updates = []
        params = []

        allowed_fields = {
            'source_name', 'source_type', 'exam_context', 'description',
            'url', 'total_questions', 'user_rating', 'is_active'
        }

        for field, value in kwargs.items():
            if field in allowed_fields:
                updates.append(f"{field} = ?")
                params.append(value)

        if not updates:
            return self.get_question_source(source_id)

        params.append(source_id)

        with self.transaction():
            self.execute(f"""
                UPDATE question_sources
                SET {', '.join(updates)}
                WHERE id = ?
            """, tuple(params))

        return self.get_question_source(source_id)

    def delete_question_source(self, source_id: int) -> bool:
        """Soft-delete a question source"""
        with self.transaction():
            self.execute(
                "UPDATE question_sources SET is_active = FALSE WHERE id = ?",
                (source_id,)
            )
        return True
