"""WIMI Sources database operations."""

from typing import Any, Dict, List, Optional

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

    # ------------------------------------------------------------------
    # Browser pane
    # ------------------------------------------------------------------

    def get_pane_sources(self) -> List[Dict[str, Any]]:
        """Sources the browser pane offers as shortcut buttons.

        A source earns a button by having a web address. That makes the
        button row a consequence of data the student already maintains
        rather than a second list to curate, and it gives the settings
        panel an obvious empty state: fill in an address, get a button.

        Ordered most-recently-opened first so the one or two banks in
        daily rotation stay visible when the row is capped and the rest
        overflow. Sources never opened in the pane sort after those that
        have, alphabetically, so a new source appears in a stable place
        rather than wherever its id happens to fall.

        **The MRU order and the desktop-site flag are per machine**
        (#126, m021). ``question_sources`` still carries the pre-m021
        columns, but they are not read here: a bank you opened on the
        desktop this morning is not one you opened on the laptop, and a
        qbank that needs a desktop user-agent in a 700px pane may not in
        a full-screen one. The LEFT JOIN is what makes a profile opened
        on a machine it has never met show every bank with defaults
        rather than another machine's history.

        Returns:
            List of dicts with ``id``, ``source_name``, ``url``,
            ``desktop_site`` (bool) and ``last_opened_at``.
        """
        self._claim_legacy_device_rows()
        rows = self.fetchall(
            """
            SELECT qs.id,
                   qs.source_name,
                   qs.url,
                   COALESCE(dss.pane_desktop_site, 1) AS pane_desktop_site,
                   dss.pane_last_opened_at            AS pane_last_opened_at
            FROM question_sources qs
            LEFT JOIN device_source_settings dss
                   ON dss.source_id = qs.id
                  AND dss.device_id = ?
            WHERE qs.user_id = ?
              AND qs.is_active = 1
              AND qs.url IS NOT NULL
              AND TRIM(qs.url) != ''
            ORDER BY
                CASE WHEN dss.pane_last_opened_at IS NULL THEN 1 ELSE 0 END,
                dss.pane_last_opened_at DESC,
                LOWER(qs.source_name)
            """,
            (self.device_id(), self.user_id),
        )
        return [
            {
                'id': r['id'],
                'source_name': r['source_name'],
                'url': r['url'],
                'desktop_site': bool(r['pane_desktop_site']),
                'last_opened_at': r['pane_last_opened_at'],
            }
            for r in rows
        ]

    def touch_pane_source(self, source_id: int) -> None:
        """Record that this machine's pane opened this source, for MRU ordering.

        Scoped to the owning user so a stray id from another profile
        cannot reorder this one's shortcuts — the ownership check is
        explicit here because ``device_source_settings`` has no
        ``user_id`` of its own, only a foreign key.

        Millisecond precision, not ``CURRENT_TIMESTAMP``: that has
        second granularity, so two opens inside the same second tie and
        fall through to the alphabetical tiebreak. Real use is minutes
        apart and would rarely notice, but it made the ordering
        untestable and would surface as a shortcut row that sometimes
        ignores the click you just made.
        """
        if not self._owns_source(source_id):
            return
        stamp = self.fetchone(
            "SELECT strftime('%Y-%m-%d %H:%M:%f', 'now') AS ts"
        )['ts']
        self._upsert_device_source(source_id, 'pane_last_opened_at', stamp)

    def set_pane_desktop_site(self, source_id: int, enabled: bool) -> None:
        """Whether this machine's pane sends a desktop user-agent for this source.

        Per-source rather than global: one qbank may serve a cramped
        mobile layout to an embedded view while another is fine, and the
        student sets it once per site rather than toggling it mid-study.
        Per-device as well as per-source since m021 — the pane is half a
        window's width on one machine and a whole one on another.
        """
        if not self._owns_source(source_id):
            return
        self._upsert_device_source(
            source_id, 'pane_desktop_site', 1 if enabled else 0
        )

    def _owns_source(self, source_id: int) -> bool:
        """Whether ``source_id`` belongs to this profile's user."""
        row = self.fetchone(
            "SELECT 1 AS ok FROM question_sources WHERE id = ? AND user_id = ?",
            (source_id, self.user_id),
        )
        return bool(row)
