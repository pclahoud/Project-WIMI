"""WIMI Notes database operations."""

import json
from typing import Optional, List

from app_logging import ErrorCategory


class NotesMixin:
    """Mixin for notes operations. Composed into UserDatabase."""

    def add_entry_note(
        self,
        entry_id: int,
        content_html: Optional[str] = None,
        content_json: Optional[str] = None,
        linked_subject_ids: Optional[List[int]] = None
    ) -> 'EntryNote':
        """
        Add a new note to an entry.

        Args:
            entry_id: Question entry ID
            content_html: HTML content of the note
            content_json: JSON content of the note (TinyMCE format)
            linked_subject_ids: Optional list of subject IDs to link

        Returns:
            Created EntryNote object
        """
        from ..models import EntryNote

        # Get next sort_order
        row = self.fetchone("""
            SELECT COALESCE(MAX(sort_order), -1) + 1 as next_order
            FROM entry_notes WHERE question_entry_id = ?
        """, (entry_id,))
        next_order = row['next_order'] if row else 0

        linked_json = json.dumps(linked_subject_ids) if linked_subject_ids else None

        # Detect the m008 junction table once — older DBs that haven't
        # had m008 applied (isolated-migration tests, mostly) just keep
        # the legacy 1:1 behaviour where the read path falls back to
        # ``entry_notes.question_entry_id``.
        junction_exists = bool(self.fetchall(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='entry_note_attachments'"
        ))

        with self.transaction():
            self.execute("""
                INSERT INTO entry_notes (question_entry_id, content_html, content_json, sort_order, linked_subject_ids)
                VALUES (?, ?, ?, ?, ?)
            """, (entry_id, content_html, content_json, next_order, linked_json))

            note_id = self.fetchone("SELECT last_insert_rowid() as id")['id']

            # Originating attachment row — keeps the new read path (which
            # joins through ``entry_note_attachments``) showing this
            # note on its originating entry without requiring callers to
            # remember a second write. Wave R3 "reuse" attachments go
            # through ``attach_existing_note_to_entry``; both writers
            # produce the same junction shape so the read path doesn't
            # care which one created the row.
            if junction_exists:
                self.execute(
                    "INSERT OR IGNORE INTO entry_note_attachments "
                    "(question_entry_id, note_id, sort_order) "
                    "VALUES (?, ?, ?)",
                    (entry_id, note_id, next_order),
                )

        # Graph dual-write (after SQLite commit)
        def _graph_write():
            self._graph_execute(
                "MERGE (n:Note {sqlite_id: $id})",
                {"id": note_id}
            )
            if linked_subject_ids:
                for sid in linked_subject_ids:
                    self._graph_execute(
                        "MATCH (n:Note {sqlite_id: $nid}), (s:Subject {sqlite_id: $sid}) "
                        "CREATE (n)-[:NOTE_LINKED_TO]->(s)",
                        {"nid": note_id, "sid": sid}
                    )
        self._dual_write_graph("add_entry_note", _graph_write)

        note_row = self.fetchone("SELECT * FROM entry_notes WHERE id = ?", (note_id,))
        return EntryNote.from_db_row(note_row)

    def get_entry_notes_list(self, entry_id: int) -> List['EntryNote']:
        """
        Get all notes for an entry ordered by sort_order.

        Args:
            entry_id: Question entry ID

        Returns:
            List of EntryNote objects
        """
        return self._get_entry_notes(entry_id)

    def update_entry_note(
        self,
        note_id: int,
        content_html: Optional[str] = None,
        content_json: Optional[str] = None,
        linked_subject_ids=None
    ) -> Optional['EntryNote']:
        """
        Update an existing entry note.

        Args:
            note_id: Note ID
            content_html: New HTML content (or None to skip)
            content_json: New JSON content (or None to skip)
            linked_subject_ids: New linked subject IDs (list, empty list, or None to skip)

        Returns:
            Updated EntryNote object or None if not found
        """
        from ..models import EntryNote

        updates = []
        params = []

        if content_html is not None:
            updates.append("content_html = ?")
            params.append(content_html)
        if content_json is not None:
            updates.append("content_json = ?")
            params.append(content_json)
        if linked_subject_ids is not None:
            updates.append("linked_subject_ids = ?")
            linked_json = json.dumps(linked_subject_ids) if linked_subject_ids else None
            params.append(linked_json)

        if not updates:
            note_row = self.fetchone("SELECT * FROM entry_notes WHERE id = ?", (note_id,))
            return EntryNote.from_db_row(note_row)

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(note_id)

        with self.transaction():
            self.execute(
                f"UPDATE entry_notes SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )

        # Graph dual-write for linked_subject_ids changes (after SQLite commit)
        if linked_subject_ids is not None:
            def _graph_write():
                # Delete old links
                self._graph_execute(
                    "MATCH (n:Note {sqlite_id: $nid})-[r:NOTE_LINKED_TO]->() DELETE r",
                    {"nid": note_id}
                )
                # Create new links
                if linked_subject_ids:
                    for sid in linked_subject_ids:
                        self._graph_execute(
                            "MATCH (n:Note {sqlite_id: $nid}), (s:Subject {sqlite_id: $sid}) "
                            "CREATE (n)-[:NOTE_LINKED_TO]->(s)",
                            {"nid": note_id, "sid": sid}
                        )
            self._dual_write_graph("update_entry_note", _graph_write)

        note_row = self.fetchone("SELECT * FROM entry_notes WHERE id = ?", (note_id,))
        return EntryNote.from_db_row(note_row)

    def delete_entry_note(self, note_id: int) -> bool:
        """
        Delete an entry note.

        Args:
            note_id: Note ID

        Returns:
            True if deleted
        """
        with self.transaction():
            self.execute("DELETE FROM entry_notes WHERE id = ?", (note_id,))

        # Graph dual-write (after SQLite commit)
        def _graph_write():
            self._graph_execute(
                "MATCH (n:Note {sqlite_id: $nid}) DETACH DELETE n",
                {"nid": note_id}
            )
        self._dual_write_graph("delete_entry_note", _graph_write)

        return True

    def get_notes_by_subjects(
        self,
        subject_ids: list,
        *,
        exclude_entry_id: Optional[int] = None,
        limit: int = 20
    ) -> List['EntryNote']:
        """
        Get entry notes linked to ANY of the given subjects.

        Plural sibling matching :meth:`MediaMixin.get_media_by_subjects`. Used
        by the "Related from other entries" UI surface on entry edit/detail
        pages. The ``entry_notes`` table has no ``dimension_id`` column so
        there is no dimension filter; user scoping is implicit (this is a
        per-user database).

        Args:
            subject_ids: List of subject node IDs to match (any-of, union
                semantics). Empty list returns ``[]`` without running SQL.
            exclude_entry_id: Optional entry ID to exclude (e.g. the current
                entry).
            limit: Maximum results.

        Returns:
            List of EntryNote objects linked to any of the given subjects.
        """
        from ..models import EntryNote

        if not subject_ids:
            return []

        # Defensive: bail if the entry_notes table hasn't been created yet
        # (matches the guard used by _get_entry_notes in _base.py).
        tables = self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='entry_notes'"
        )
        if not tables:
            return []

        placeholders = ", ".join("?" for _ in subject_ids)

        where_clauses = [
            "linked_subject_ids IS NOT NULL",
            "linked_subject_ids != '[]'",
            (
                "EXISTS ("
                " SELECT 1 FROM json_each(linked_subject_ids)"
                f" WHERE CAST(json_each.value AS INTEGER) IN ({placeholders})"
                ")"
            ),
        ]
        params: list = list(subject_ids)

        if exclude_entry_id is not None:
            where_clauses.append("question_entry_id != ?")
            params.append(exclude_entry_id)

        params.append(limit)

        sql = (
            "SELECT * FROM entry_notes WHERE "
            + " AND ".join(where_clauses)
            + " ORDER BY updated_at DESC LIMIT ?"
        )

        rows = self.fetchall(sql, tuple(params))
        return [EntryNote.from_db_row(row) for row in rows]

    def attach_existing_note_to_entry(
        self,
        note_id: int,
        entry_id: int,
        *,
        sort_order: Optional[int] = None,
    ) -> bool:
        """Attach an existing note to an entry via the ``entry_note_attachments`` junction.

        Idempotent — re-attaching an already-attached note is a no-op
        (returns ``False``). Both the note and the entry must already
        exist; missing ids raise :class:`ValidationError`.

        Args:
            note_id: ID of an existing row in ``entry_notes``.
            entry_id: ID of an existing row in ``question_entries``.
            sort_order: Optional explicit sort order. When ``None`` (default)
                this is computed as ``MAX(sort_order) + 1`` for the entry,
                defaulting to ``0`` when the entry has no attachments yet.

        Returns:
            ``True`` if a new attachment row was created, ``False`` if the
            note was already attached to the entry.
        """
        from ..exceptions import ValidationError

        note_row = self.fetchone(
            "SELECT id FROM entry_notes WHERE id = ?", (note_id,)
        )
        if not note_row:
            raise ValidationError(f"Note {note_id} not found")

        entry_row = self.fetchone(
            "SELECT id FROM question_entries WHERE id = ?", (entry_id,)
        )
        if not entry_row:
            raise ValidationError(f"Question entry {entry_id} not found")

        if sort_order is None:
            row = self.fetchone(
                """
                SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order
                FROM entry_note_attachments
                WHERE question_entry_id = ?
                """,
                (entry_id,),
            )
            sort_order = row['next_order'] if row else 0

        with self.transaction():
            cursor = self.execute(
                """
                INSERT OR IGNORE INTO entry_note_attachments
                    (question_entry_id, note_id, sort_order)
                VALUES (?, ?, ?)
                """,
                (entry_id, note_id, sort_order),
            )
            return cursor.rowcount > 0

    def detach_note_from_entry(self, note_id: int, entry_id: int) -> bool:
        """Remove the attachment of a note from an entry.

        Does NOT delete the note record itself — only the row in the
        ``entry_note_attachments`` junction table. The note remains
        attached to any other entries it was reused on.

        Args:
            note_id: ID of the note to detach.
            entry_id: ID of the entry to detach the note from.

        Returns:
            ``True`` if a junction row was removed, ``False`` if no such
            attachment existed.
        """
        with self.transaction():
            cursor = self.execute(
                """
                DELETE FROM entry_note_attachments
                WHERE question_entry_id = ? AND note_id = ?
                """,
                (entry_id, note_id),
            )
            return cursor.rowcount > 0

    def clear_entry_note(self, note_id: int) -> Optional['EntryNote']:
        """
        Clear a note's content but keep the record.

        Args:
            note_id: Note ID

        Returns:
            Updated EntryNote object with empty content
        """
        from ..models import EntryNote

        with self.transaction():
            self.execute("""
                UPDATE entry_notes
                SET content_html = '', content_json = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (note_id,))

        note_row = self.fetchone("SELECT * FROM entry_notes WHERE id = ?", (note_id,))
        return EntryNote.from_db_row(note_row)
