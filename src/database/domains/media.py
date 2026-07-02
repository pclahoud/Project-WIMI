"""WIMI Media database operations."""

import json
from typing import Optional, List, Dict, Any
from ..base_db import DatabaseIntegrityError
from app_logging import ErrorCategory


class MediaMixin:
    """Mixin for media operations. Composed into UserDatabase."""

    def add_entry_media(
        self,
        entry_id: int,
        file_uuid: str,
        original_filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        linked_subject_ids: Optional[List[int]] = None
    ) -> 'EntryMedia':
        """
        Add media to a question entry.

        Args:
            entry_id: ID of the question entry
            file_uuid: UUID of the file on disk
            original_filename: Original filename
            mime_type: MIME type of the file
            file_size_bytes: File size in bytes
            linked_subject_ids: Subject IDs to link (defaults to entry's primary subjects)

        Returns:
            EntryMedia object
        """
        from ..models import EntryMedia
        from ..exceptions import MediaError, QuestionEntryNotFoundError

        # Validate entry exists
        entry = self.get_question_entry(entry_id)
        if not entry:
            raise QuestionEntryNotFoundError(f"Question entry {entry_id} not found")

        # Default linked subjects to entry's primary subjects
        if linked_subject_ids is None:
            linked_subject_ids = [s.id for s in entry.primary_subjects]

        # Get next sort order from junction table
        row = self.fetchone("""
            SELECT COALESCE(MAX(sort_order), -1) + 1 as next_order
            FROM entry_media_mapping WHERE question_entry_id = ?
        """, (entry_id,))
        sort_order = row['next_order'] if row else 0

        try:
            with self.transaction():
                # Insert media record (user-level)
                cursor = self.execute("""
                    INSERT INTO entry_media (
                        question_entry_id, file_uuid, original_filename, user_filename,
                        mime_type, file_size_bytes, sort_order, linked_subject_ids,
                        user_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry_id, file_uuid, original_filename, original_filename,
                    mime_type, file_size_bytes, sort_order,
                    json.dumps(linked_subject_ids) if linked_subject_ids else None,
                    self.user_id
                ))

                media_id = cursor.lastrowid

                # Link to entry via junction table
                self.execute("""
                    INSERT OR IGNORE INTO entry_media_mapping
                        (question_entry_id, media_id, sort_order, is_active)
                    VALUES (?, ?, ?, 1)
                """, (entry_id, media_id, sort_order))

                return self.get_entry_media(media_id)

        except DatabaseIntegrityError as e:
            raise MediaError(f"Failed to add media: {e}") from e

    def get_entry_media(self, media_id: int) -> Optional['EntryMedia']:
        """Get entry media by ID"""
        from ..models import EntryMedia

        row = self.fetchone(
            "SELECT * FROM entry_media WHERE id = ?",
            (media_id,)
        )
        return EntryMedia.from_db_row(row) if row else None

    def update_entry_media(
        self,
        media_id: int,
        user_filename: Optional[str] = None,
        sort_order: Optional[int] = None,
        linked_subject_ids: Optional[List[int]] = None,
        dimension_id: Optional[int] = None
    ) -> 'EntryMedia':
        """
        Update entry media.

        Args:
            media_id: ID of the media to update
            user_filename: New user-defined filename
            sort_order: New sort order
            linked_subject_ids: New linked subject IDs
            dimension_id: Dimension ID for multi-dimensional exams

        Returns:
            Updated EntryMedia object
        """
        updates = []
        params = []

        if user_filename is not None:
            updates.append("user_filename = ?")
            params.append(user_filename)

        if sort_order is not None:
            updates.append("sort_order = ?")
            params.append(sort_order)

        if linked_subject_ids is not None:
            updates.append("linked_subject_ids = ?")
            params.append(json.dumps(linked_subject_ids))

        if dimension_id is not None:
            updates.append("dimension_id = ?")
            params.append(dimension_id if dimension_id > 0 else None)

        if not updates:
            return self.get_entry_media(media_id)

        params.append(media_id)

        with self.transaction():
            self.execute(f"""
                UPDATE entry_media
                SET {', '.join(updates)}
                WHERE id = ?
            """, tuple(params))

        return self.get_entry_media(media_id)

    def delete_entry_media(self, media_id: int) -> bool:
        """
        Delete entry media record and its junction table links.
        File must be deleted separately via media_manager.

        Args:
            media_id: ID of the media to delete

        Returns:
            True if deleted successfully
        """
        with self.transaction():
            self.execute(
                "DELETE FROM entry_media_mapping WHERE media_id = ?",
                (media_id,)
            )
            self.execute("DELETE FROM entry_media WHERE id = ?", (media_id,))
        return True

    def unlink_media_from_entry(self, media_id: int) -> bool:
        """
        Unlink media from its entry by setting is_active = 0 on the junction row.
        The media record and file remain so the image can be rediscovered
        via the image browser.

        Args:
            media_id: ID of the media to unlink

        Returns:
            True if unlinked successfully
        """
        with self.transaction():
            self.execute(
                "UPDATE entry_media_mapping SET is_active = 0 WHERE media_id = ?",
                (media_id,)
            )
        return True

    def get_media_by_id(self, media_id: int) -> Optional['EntryMedia']:
        """
        Get entry media by ID (alias for get_entry_media).

        Args:
            media_id: ID of the media

        Returns:
            EntryMedia object or None
        """
        return self.get_entry_media(media_id)

    def link_media_to_entry(self, media_id: int, entry_id: int) -> Optional['EntryMedia']:
        """
        Link an existing media record to an entry via the junction table.
        Used when attaching a previously-uploaded image to a new entry.

        Args:
            media_id: ID of the existing media record
            entry_id: ID of the entry to attach to

        Returns:
            EntryMedia object, or None if media not found
        """
        media = self.get_entry_media(media_id)
        if not media:
            return None

        # Get next sort order for this entry
        row = self.fetchone("""
            SELECT COALESCE(MAX(sort_order), -1) + 1 as next_order
            FROM entry_media_mapping WHERE question_entry_id = ?
        """, (entry_id,))
        sort_order = row['next_order'] if row else 0

        with self.transaction():
            self.execute("""
                INSERT OR IGNORE INTO entry_media_mapping
                    (question_entry_id, media_id, sort_order, is_active)
                VALUES (?, ?, ?, 1)
            """, (entry_id, media_id, sort_order))

        return media

    def attach_existing_media_to_entry(
        self,
        media_id: int,
        entry_id: int,
        *,
        sort_order: Optional[int] = None,
    ) -> bool:
        """Attach an existing media item to an entry via ``entry_media_mapping``.

        Idempotent for the active case — re-attaching a media item that is
        already actively mapped to the entry is a no-op (returns
        ``False``). If a *soft-deleted* mapping exists (``is_active=0``)
        the row is re-activated rather than INSERT-conflicting. Both ids
        must exist; missing ids raise :class:`ValidationError`.

        Args:
            media_id: ID of an existing row in ``entry_media``.
            entry_id: ID of an existing row in ``question_entries``.
            sort_order: Optional explicit sort order for a newly created
                mapping. When ``None`` (default) this is computed as
                ``MAX(sort_order) + 1`` for the entry, defaulting to ``0``.
                Ignored when re-activating an existing soft-deleted row
                (its prior ``sort_order`` is preserved).

        Returns:
            ``True`` if a new mapping row was inserted *or* a soft-deleted
            mapping was re-activated. ``False`` if the mapping was already
            active.
        """
        from ..exceptions import ValidationError

        media_row = self.fetchone(
            "SELECT id FROM entry_media WHERE id = ?", (media_id,)
        )
        if not media_row:
            raise ValidationError(f"Media {media_id} not found")

        entry_row = self.fetchone(
            "SELECT id FROM question_entries WHERE id = ?", (entry_id,)
        )
        if not entry_row:
            raise ValidationError(f"Question entry {entry_id} not found")

        with self.transaction():
            existing = self.fetchone(
                """
                SELECT id, is_active FROM entry_media_mapping
                WHERE question_entry_id = ? AND media_id = ?
                """,
                (entry_id, media_id),
            )

            if existing is not None:
                if existing['is_active']:
                    return False
                # Re-activate the soft-deleted mapping.
                self.execute(
                    """
                    UPDATE entry_media_mapping
                    SET is_active = 1
                    WHERE id = ?
                    """,
                    (existing['id'],),
                )
                return True

            if sort_order is None:
                row = self.fetchone(
                    """
                    SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order
                    FROM entry_media_mapping
                    WHERE question_entry_id = ?
                    """,
                    (entry_id,),
                )
                sort_order = row['next_order'] if row else 0

            self.execute(
                """
                INSERT INTO entry_media_mapping
                    (question_entry_id, media_id, sort_order, is_active)
                VALUES (?, ?, ?, 1)
                """,
                (entry_id, media_id, sort_order),
            )
            return True

    def detach_media_from_entry(self, media_id: int, entry_id: int) -> bool:
        """Soft-detach: set ``is_active = 0`` on the (entry, media) mapping.

        Mirrors the existing soft-delete pattern used by
        :meth:`unlink_media_from_entry` — the row is preserved so the
        media remains rediscoverable via the image browser and so
        re-attachment can re-activate the same row without losing its
        ``sort_order``. Returns ``False`` (and is a no-op) when the
        mapping is already inactive or does not exist.

        Args:
            media_id: ID of the media to detach.
            entry_id: ID of the entry to detach the media from.

        Returns:
            ``True`` if a row's ``is_active`` was changed from ``1`` to
            ``0``, ``False`` otherwise.
        """
        with self.transaction():
            cursor = self.execute(
                """
                UPDATE entry_media_mapping
                SET is_active = 0
                WHERE question_entry_id = ?
                  AND media_id = ?
                  AND is_active = 1
                """,
                (entry_id, media_id),
            )
            return cursor.rowcount > 0

    def get_entry_media_list(self, entry_id: int) -> List['EntryMedia']:
        """
        Get all media for a question entry via junction table.

        Args:
            entry_id: ID of the question entry

        Returns:
            List of EntryMedia objects ordered by sort_order
        """
        from ..models import EntryMedia

        rows = self.fetchall("""
            SELECT em.* FROM entry_media em
            JOIN entry_media_mapping emm ON em.id = emm.media_id
            WHERE emm.question_entry_id = ?
            AND emm.is_active = 1
            ORDER BY emm.sort_order
        """, (entry_id,))

        return [EntryMedia.from_db_row(row) for row in rows]

    def update_media_filename(self, media_id: int, new_filename: str) -> 'EntryMedia':
        """
        Update the user-defined filename for a media item.

        Args:
            media_id: ID of the media to update
            new_filename: New user-defined filename

        Returns:
            Updated EntryMedia object
        """
        with self.transaction():
            self.execute("""
                UPDATE entry_media
                SET user_filename = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_filename, media_id))

        return self.get_entry_media(media_id)

    def reorder_entry_media(self, entry_id: int, media_ids: List[int]) -> bool:
        """
        Reorder media for an entry via junction table.

        Args:
            entry_id: ID of the question entry
            media_ids: List of media IDs in desired order

        Returns:
            True if reordered successfully
        """
        with self.transaction():
            for order, media_id in enumerate(media_ids):
                self.execute("""
                    UPDATE entry_media_mapping
                    SET sort_order = ?
                    WHERE media_id = ? AND question_entry_id = ?
                """, (order, media_id, entry_id))
        return True

    def search_media(
        self,
        query: str = '',
        limit: int = 50
    ) -> List['EntryMedia']:
        """
        Search media files globally for the current user by filename.

        Args:
            query: Search query (matches user_filename or original_filename)
            limit: Maximum results

        Returns:
            List of EntryMedia objects matching the search
        """
        from ..models import EntryMedia

        self._ensure_phase4_schema()

        if query and query.strip():
            search_term = f"%{query.strip()}%"
            sql = """
                SELECT * FROM entry_media
                WHERE user_id = ?
                AND (user_filename LIKE ? OR original_filename LIKE ?)
                ORDER BY updated_at DESC
                LIMIT ?
            """
            params = (self.user_id, search_term, search_term, limit)
        else:
            sql = """
                SELECT * FROM entry_media
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
            """
            params = (self.user_id, limit)

        rows = self.fetchall(sql, params)
        return [EntryMedia.from_db_row(row) for row in rows]

    def get_media_by_subject(
        self,
        subject_node_id: int,
        limit: int = 20,
        dimension_id: Optional[int] = None
    ) -> List['EntryMedia']:
        """
        Get media files globally for the current user that are linked to a subject.

        Args:
            subject_node_id: Subject node ID to match
            limit: Maximum results
            dimension_id: Optional dimension ID to filter by

        Returns:
            List of EntryMedia objects linked to this subject
        """
        from ..models import EntryMedia

        self._ensure_phase4_schema()

        if dimension_id is not None and dimension_id > 0:
            sql = """
                SELECT * FROM entry_media
                WHERE user_id = ?
                AND linked_subject_ids IS NOT NULL
                AND linked_subject_ids != '[]'
                AND EXISTS (
                    SELECT 1 FROM json_each(linked_subject_ids)
                    WHERE json_each.value = ?
                )
                AND dimension_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
            """
            rows = self.fetchall(sql, (self.user_id, subject_node_id, dimension_id, limit))
        else:
            sql = """
                SELECT * FROM entry_media
                WHERE user_id = ?
                AND linked_subject_ids IS NOT NULL
                AND linked_subject_ids != '[]'
                AND EXISTS (
                    SELECT 1 FROM json_each(linked_subject_ids)
                    WHERE json_each.value = ?
                )
                ORDER BY updated_at DESC
                LIMIT ?
            """
            rows = self.fetchall(sql, (self.user_id, subject_node_id, limit))

        return [EntryMedia.from_db_row(row) for row in rows]

    def get_media_by_subjects(
        self,
        subject_ids: list,
        *,
        exclude_entry_id: Optional[int] = None,
        limit: int = 20,
        dimension_id: Optional[int] = None
    ) -> List['EntryMedia']:
        """
        Get media files for the current user linked to ANY of the given subjects.

        Plural sibling of :meth:`get_media_by_subject`. Used by the "Related from
        other entries" UI surface on entry edit/detail pages.

        Args:
            subject_ids: List of subject node IDs to match (any-of, union semantics).
                Empty list returns ``[]`` without running SQL.
            exclude_entry_id: Optional entry ID to exclude (e.g. the current entry).
            limit: Maximum results.
            dimension_id: Optional dimension ID to filter by.

        Returns:
            List of EntryMedia objects linked to any of the given subjects.
        """
        from ..models import EntryMedia

        if not subject_ids:
            return []

        self._ensure_phase4_schema()

        placeholders = ", ".join("?" for _ in subject_ids)

        where_clauses = [
            "user_id = ?",
            "linked_subject_ids IS NOT NULL",
            "linked_subject_ids != '[]'",
            (
                "EXISTS ("
                " SELECT 1 FROM json_each(linked_subject_ids)"
                f" WHERE CAST(json_each.value AS INTEGER) IN ({placeholders})"
                ")"
            ),
        ]
        params: list = [self.user_id, *subject_ids]

        if exclude_entry_id is not None:
            where_clauses.append("question_entry_id != ?")
            params.append(exclude_entry_id)

        if dimension_id is not None and dimension_id > 0:
            where_clauses.append("dimension_id = ?")
            params.append(dimension_id)

        params.append(limit)

        sql = (
            "SELECT * FROM entry_media WHERE "
            + " AND ".join(where_clauses)
            + " ORDER BY updated_at DESC LIMIT ?"
        )

        rows = self.fetchall(sql, tuple(params))
        return [EntryMedia.from_db_row(row) for row in rows]
