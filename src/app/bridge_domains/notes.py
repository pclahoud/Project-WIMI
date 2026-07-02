"""WIMI Entry Notes bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class NoteBridgeMixin:
    """Bridge mixin for entry note operations. Composed into DatabaseBridge."""

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def addEntryNote(self, entry_id: int, content_json: str) -> str:
        """
        Add a new note to a question entry.

        Args:
            entry_id: Question entry ID
            content_json: JSON string with {content_html, content_json, linked_subject_ids}

        Returns:
            JSON response with created note
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = json.loads(content_json) if content_json else {}
            note = self.user_db.add_entry_note(
                entry_id=entry_id,
                content_html=data.get('content_html'),
                content_json=data.get('content_json'),
                linked_subject_ids=data.get('linked_subject_ids')
            )
            return serialize_response(True, data=self._serialize_entry_note(note))
        except Exception as e:
            self._log_error(
                f'Error adding entry note: {e}',
                {
                    'entry_id': entry_id,
                    'content_json_len': len(content_json) if content_json else 0,
                    'content_json_preview': content_json[:200] if content_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to add note: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getEntryNotes(self, entry_id: int) -> str:
        """
        Get all notes for a question entry.

        Args:
            entry_id: Question entry ID

        Returns:
            JSON response with list of notes
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            notes = self.user_db.get_entry_notes_list(entry_id)
            data = [self._serialize_entry_note(n) for n in notes]
            return serialize_response(True, data=data)
        except Exception as e:
            self._log_error(
                f'Error getting entry notes: {e}',
                {'entry_id': entry_id},
            )
            return serialize_response(False, error=f'Failed to get notes: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateEntryNote(self, note_id: int, updates_json: str) -> str:
        """
        Update an existing entry note.

        Args:
            note_id: Note ID
            updates_json: JSON string with {content_html, content_json, linked_subject_ids}

        Returns:
            JSON response with updated note
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = json.loads(updates_json) if updates_json else {}
            note = self.user_db.update_entry_note(
                note_id=note_id,
                content_html=data.get('content_html'),
                content_json=data.get('content_json'),
                linked_subject_ids=data.get('linked_subject_ids')
            )
            if note:
                return serialize_response(True, data=self._serialize_entry_note(note))
            return serialize_response(False, error='Note not found')
        except Exception as e:
            self._log_error(
                f'Error updating entry note: {e}',
                {
                    'note_id': note_id,
                    'updates_json_len': len(updates_json) if updates_json else 0,
                    'updates_json_preview': updates_json[:200] if updates_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to update note: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteEntryNote(self, note_id: int) -> str:
        """
        Delete an entry note.

        Args:
            note_id: Note ID

        Returns:
            JSON response with delete result
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            self.user_db.delete_entry_note(note_id)
            return serialize_response(True, data={'id': note_id, 'deleted': True})
        except Exception as e:
            self._log_error(
                f'Error deleting entry note: {e}',
                {'note_id': note_id},
            )
            return serialize_response(False, error=f'Failed to delete note: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def clearEntryNote(self, note_id: int) -> str:
        """
        Clear a note's content but keep the record.

        Args:
            note_id: Note ID

        Returns:
            JSON response with cleared note
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            note = self.user_db.clear_entry_note(note_id)
            if note:
                return serialize_response(True, data=self._serialize_entry_note(note))
            return serialize_response(False, error='Note not found')
        except Exception as e:
            self._log_error(
                f'Error clearing entry note: {e}',
                {'note_id': note_id},
            )
            return serialize_response(False, error=f'Failed to clear note: {e}')

    @pyqtSlot(str, int, int, result=str)
    @instrumented_slot
    def getNotesBySubjects(
        self,
        subject_ids_json: str,
        exclude_entry_id: int = 0,
        limit: int = 20,
    ) -> str:
        """
        Get entry notes linked to any of the given subjects, optionally excluding
        a specific entry. Used by the "Related from other entries" surface.

        Args:
            subject_ids_json: JSON-encoded list of subject IDs (e.g. "[12, 47]")
            exclude_entry_id: Entry ID to exclude from results (0 = no exclusion)
            limit: Maximum results

        Returns:
            JSON response with list of matching notes
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            try:
                subject_ids = json.loads(subject_ids_json) if subject_ids_json else []
            except json.JSONDecodeError as e:
                return serialize_response(False, error=f'Invalid JSON: {e}')

            if not isinstance(subject_ids, list):
                return serialize_response(False, error='subject_ids must be a JSON array')
            if not all(isinstance(s, int) for s in subject_ids):
                return serialize_response(False, error='subject_ids must contain only integers')

            notes = self.user_db.get_notes_by_subjects(
                subject_ids=subject_ids,
                exclude_entry_id=exclude_entry_id if exclude_entry_id > 0 else None,
                limit=limit,
            )

            data = [self._serialize_entry_note(n) for n in notes]

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting notes by subjects: {e}',
                {
                    'subject_ids_json_len': len(subject_ids_json) if subject_ids_json else 0,
                    'subject_ids_json_preview': subject_ids_json[:200] if subject_ids_json else '',
                    'exclude_entry_id': exclude_entry_id,
                    'limit': limit,
                },
            )
            return serialize_response(False, error=f'Failed to get notes: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def attachExistingNoteToEntry(self, note_id: int, entry_id: int) -> str:
        """
        Attach an existing note to an entry via the entry_note_attachments
        junction table. Idempotent — re-attaching an already-attached note
        returns success with ``created=False``.

        Args:
            note_id: ID of an existing row in ``entry_notes``.
            entry_id: ID of an existing row in ``question_entries``.

        Returns:
            JSON response with ``{'created': bool}`` — True when a new
            junction row was inserted, False when the note was already
            attached.
        """
        from database.exceptions import ValidationError

        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            created = self.user_db.attach_existing_note_to_entry(note_id, entry_id)
            return serialize_response(True, data={'created': bool(created)})
        except ValidationError as e:
            # User-correctable (unknown ids) — don't log as an error.
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error attaching existing note to entry: {e}',
                {
                    'note_id': note_id,
                    'entry_id': entry_id,
                },
            )
            return serialize_response(False, error=f'Failed to attach note: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def detachNoteFromEntry(self, note_id: int, entry_id: int) -> str:
        """
        Detach a note from an entry by removing the junction row. Does
        NOT delete the underlying ``entry_notes`` record — the note
        remains attached to any other entries that reuse it.

        Args:
            note_id: ID of the note to detach.
            entry_id: ID of the entry to detach the note from.

        Returns:
            JSON response with ``{'removed': bool}`` — True when a
            junction row was deleted, False when no such attachment
            existed (idempotent no-op).
        """
        from database.exceptions import ValidationError

        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            removed = self.user_db.detach_note_from_entry(note_id, entry_id)
            return serialize_response(True, data={'removed': bool(removed)})
        except ValidationError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error detaching note from entry: {e}',
                {
                    'note_id': note_id,
                    'entry_id': entry_id,
                },
            )
            return serialize_response(False, error=f'Failed to detach note: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateNoteLinkedSubjects(self, note_id: int, subject_ids_json: str) -> str:
        """
        Update the linked subject IDs for a note.

        Args:
            note_id: Note ID
            subject_ids_json: JSON array of subject node IDs

        Returns:
            JSON response with updated note
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            subject_ids = json.loads(subject_ids_json) if subject_ids_json else []
            if not isinstance(subject_ids, list):
                return serialize_response(False, error='subject_ids must be a JSON array')

            note = self.user_db.update_entry_note(
                note_id=note_id,
                linked_subject_ids=subject_ids
            )
            if note:
                return serialize_response(True, data=self._serialize_entry_note(note))
            return serialize_response(False, error='Note not found')
        except json.JSONDecodeError as e:
            return serialize_response(False, error=f'Invalid JSON: {e}')
        except Exception as e:
            self._log_error(
                f'Error updating note linked subjects: {e}',
                {
                    'note_id': note_id,
                    'subject_ids_json_len': len(subject_ids_json) if subject_ids_json else 0,
                    'subject_ids_json_preview': subject_ids_json[:200] if subject_ids_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to update note subjects: {e}')
