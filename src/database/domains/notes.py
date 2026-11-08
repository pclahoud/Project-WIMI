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

    def add_free_note(
        self,
        content_html: Optional[str] = None,
        content_json: Optional[str] = None,
        linked_subject_ids: Optional[List[int]] = None
    ) -> 'EntryNote':
        """Write a note that belongs to no entry (#848 decision 1, m036).

        The row has a NULL ``question_entry_id`` and no junction row, so it is
        reachable through its subject tags (the picker and the deep dive) and
        through :meth:`list_free_notes`. A subject tag is optional (decision
        3). Attaching it to an entry later goes through
        :meth:`attach_existing_note_to_entry` and leaves the origin NULL.

        Returns:
            The created EntryNote, with ``attachment_count`` 0.
        """
        from ..models import EntryNote

        linked_json = json.dumps(linked_subject_ids) if linked_subject_ids else None

        with self.transaction():
            self.execute("""
                INSERT INTO entry_notes (question_entry_id, content_html, content_json, sort_order, linked_subject_ids)
                VALUES (NULL, ?, ?, 0, ?)
            """, (content_html, content_json, linked_json))
            note_id = self.fetchone("SELECT last_insert_rowid() as id")['id']

        if self.error_logger:
            self.error_logger.info(
                f"Created free note {note_id}",
                category=ErrorCategory.DATABASE
            )

        # Graph dual-write (after SQLite commit), the shape add_entry_note uses.
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
        self._dual_write_graph("add_free_note", _graph_write)

        return self.get_entry_note(note_id)

    def _notes_with_attachment_count(self, where_sql: str, params: tuple) -> List['EntryNote']:
        """Read notes with ``attachment_count`` attached as ``_get_entry_notes`` does.

        The count is computed, not a column; it is attached to each instance
        so the serializer can surface it. A database without the m009
        junction (an isolated-migration test) counts 0 attachments.
        """
        from ..models import EntryNote

        junction_exists = bool(self.fetchall(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='entry_note_attachments'"
        ))
        count_sql = (
            "(SELECT COUNT(*) FROM entry_note_attachments WHERE note_id = en.id)"
            if junction_exists else "0"
        )
        rows = self.fetchall(
            f"SELECT en.*, {count_sql} AS attachment_count FROM entry_notes en {where_sql}",
            params,
        )
        notes = []
        for row in rows:
            note = EntryNote.from_db_row(row)
            if note is None:
                continue
            try:
                note.attachment_count = int(row['attachment_count'])
            except (KeyError, TypeError, ValueError):
                note.attachment_count = 0
            notes.append(note)
        return notes

    def get_entry_note(self, note_id: int) -> Optional['EntryNote']:
        """Read one note by id, entry note or free, with ``attachment_count``.

        Returns:
            The EntryNote, or ``None`` when no such note exists.
        """
        notes = self._notes_with_attachment_count("WHERE en.id = ?", (note_id,))
        return notes[0] if notes else None

    def list_free_notes(self, limit: int = 50) -> List['EntryNote']:
        """The notes on no entry, newest first (#848 decision 3's *Your notes*).

        A free note is one whose origin is NULL: written on its own, or left
        behind when its originating entry was deleted or detached while other
        entries still held it. Entry notes are excluded whatever they are
        attached to. Each carries ``attachment_count``.
        """
        return self._notes_with_attachment_count(
            "WHERE en.question_entry_id IS NULL ORDER BY en.updated_at DESC, en.id DESC LIMIT ?",
            (limit,),
        )

    def release_notes_from_entries(self, entry_ids: List[int]) -> dict:
        """#848 decision 2: what becomes of a note when its origin is deleted.

        For each note whose ``question_entry_id`` is one of ``entry_ids``:

        - if ``entry_note_attachments`` holds a row for an entry **outside**
          ``entry_ids``, the note is freed -- origin set NULL, ``updated_at``
          stamped -- and stays on those entries;
        - otherwise the note is deleted (its own attachment rows cascade).

        **Call it inside the caller's transaction and BEFORE the entries are
        deleted.** Every path that removes entry rows calls it:
        ``delete_question_entry``, ``delete_review_session`` (which deletes
        the session's entries itself) and ``hard_delete_exam_context`` (whose
        cascade reaches them). The column's own ``ON DELETE SET NULL`` is the
        fallback for a path that forgets, and it leaves a stray free note the
        student can see and delete rather than destroying a shared one.

        **A note is deleted only with its origin, never with an entry it
        merely sits on.** A free note's origin is NULL, so none of
        ``entry_ids`` names it: deleting the last entry holding a free note
        leaves it with no attachment, still listed by ``list_free_notes``
        (*Your notes*). That is the design, not a gap (#862 item 5).

        The decision is taken in Python per note rather than in one
        ``NOT IN (...)`` statement so a session of any size stays under
        SQLite's bound-variable limit while the *other entry* test is still
        made against the whole set.

        Returns:
            ``{'deleted_note_ids': [...], 'freed_note_ids': [...]}``.
        """
        result = {'deleted_note_ids': [], 'freed_note_ids': []}
        if not entry_ids:
            return result
        if not self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='entry_notes'"
        ):
            return result
        junction_exists = bool(self.fetchall(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='entry_note_attachments'"
        ))

        doomed = set(entry_ids)
        note_ids: List[int] = []
        chunk = 500
        ids = list(doomed)
        for start in range(0, len(ids), chunk):
            part = ids[start:start + chunk]
            placeholders = ", ".join("?" for _ in part)
            note_ids.extend(
                row['id'] for row in self.fetchall(
                    f"SELECT id FROM entry_notes WHERE question_entry_id IN ({placeholders})",
                    tuple(part),
                )
            )

        with self.transaction():
            for note_id in note_ids:
                held_elsewhere = False
                if junction_exists:
                    held_elsewhere = any(
                        row['question_entry_id'] not in doomed
                        for row in self.fetchall(
                            "SELECT question_entry_id FROM entry_note_attachments "
                            "WHERE note_id = ?",
                            (note_id,),
                        )
                    )
                if held_elsewhere:
                    self.execute(
                        "UPDATE entry_notes "
                        "SET question_entry_id = NULL, updated_at = CURRENT_TIMESTAMP "
                        "WHERE id = ?",
                        (note_id,),
                    )
                    result['freed_note_ids'].append(note_id)
                else:
                    self.execute("DELETE FROM entry_notes WHERE id = ?", (note_id,))
                    result['deleted_note_ids'].append(note_id)

        if self.error_logger and note_ids:
            self.error_logger.info(
                f"Entry delete released notes: {len(result['freed_note_ids'])} freed, "
                f"{len(result['deleted_note_ids'])} deleted",
                category=ErrorCategory.DATABASE
            )
        return result

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
            List of EntryNote objects linked to any of the given subjects,
            each carrying ``attachment_count`` (#848 Wave 2a).
        """
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
            "en.linked_subject_ids IS NOT NULL",
            "en.linked_subject_ids != '[]'",
            (
                "EXISTS ("
                " SELECT 1 FROM json_each(en.linked_subject_ids)"
                f" WHERE CAST(json_each.value AS INTEGER) IN ({placeholders})"
                ")"
            ),
        ]
        params: list = list(subject_ids)

        if exclude_entry_id is not None:
            # A free note (#848, m036) has a NULL origin, and ``NULL != x``
            # is NULL, so without the second disjunct every free note would
            # vanish from the picker on every entry. The deep dive calls this
            # without an exclusion and never had the problem.
            where_clauses.append(
                "(en.question_entry_id != ? OR en.question_entry_id IS NULL)"
            )
            params.append(exclude_entry_id)

        params.append(limit)

        # Read through the same helper as list_free_notes so each note carries
        # ``attachment_count`` (#848 Wave 2a). Without it the serializer's
        # default of 1 stood in for every picker row, and the row label could
        # not tell "not on any entry" from "on 3 entries".
        where_sql = (
            "WHERE " + " AND ".join(where_clauses)
            + " ORDER BY en.updated_at DESC LIMIT ?"
        )
        return self._notes_with_attachment_count(where_sql, tuple(params))

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

        **Detaching from the note's originating entry also clears the
        origin** (#848 decision 4's data half). Until m036 the junction row
        went and ``question_entry_id`` stayed, so a note "detached" from its
        origin still died with that entry -- the trap chapter 32 used to warn
        about. Detaching the last attachment is allowed and leaves a free
        note (origin NULL, no junction row), which ``list_free_notes`` returns.

        **Removing the note's LAST attachment clears the origin whichever
        entry it names** (PR #864 round 2). A profile from before m036 can
        hold a note born on X, attached to Y, and detached from X by the old
        Detach, which removed the junction row and left ``question_entry_id
        = X``; m036 repairs only an origin whose entry no longer exists, so
        that row still says X. Clearing the origin only when it equals
        ``entry_id`` would leave such a note with origin X and no junction
        row after *Keep as a note on its own* on Y: absent from
        ``list_free_notes`` (``IS NULL``) while the page's toast promises
        *Your notes*, and back on X's card list through
        ``_get_entry_notes``' legacy fallback (origin matches and no junction
        row) -- the entry the student had deliberately taken it off. With no
        attachment left there is no entry for the origin to mean, so it goes.
        An origin on a note that still has an attachment elsewhere is kept
        unless it names ``entry_id`` itself.

        Args:
            note_id: ID of the note to detach.
            entry_id: ID of the entry to detach the note from.

        Returns:
            ``True`` if a junction row was removed or the origin was cleared,
            ``False`` if the note was not attached to that entry at all.
        """
        with self.transaction():
            cursor = self.execute(
                """
                DELETE FROM entry_note_attachments
                WHERE question_entry_id = ? AND note_id = ?
                """,
                (entry_id, note_id),
            )
            removed = cursor.rowcount > 0
            remaining = self.fetchone(
                "SELECT COUNT(*) AS n FROM entry_note_attachments WHERE note_id = ?",
                (note_id,),
            )
            last_attachment_went = removed and int(remaining['n']) == 0
            if last_attachment_went:
                origin = self.execute(
                    """
                    UPDATE entry_notes
                    SET question_entry_id = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND question_entry_id IS NOT NULL
                    """,
                    (note_id,),
                )
            else:
                origin = self.execute(
                    """
                    UPDATE entry_notes
                    SET question_entry_id = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND question_entry_id = ?
                    """,
                    (note_id, entry_id),
                )
            return removed or origin.rowcount > 0

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
