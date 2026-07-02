"""WIMI Question Entry bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class EntryBridgeMixin:
    """Bridge mixin for question entry operations. Composed into DatabaseBridge."""

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createQuestionEntry(self, entry_data_json: str) -> str:
        """
        Create a new question entry.

        Args:
            entry_data_json: JSON string with entry data

        Returns:
            JSON response with created entry
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = json.loads(entry_data_json)

            entry = self.user_db.create_question_entry(
                review_session_id=data['review_session_id'],
                user_answer=data.get('user_answer', ''),
                correct_answer=data.get('correct_answer', ''),
                question_id=data.get('question_id'),
                perceived_difficulty=data.get('perceived_difficulty'),
                time_spent_seconds=data.get('time_spent_seconds'),
                reflection=data.get('reflection'),
                explanation=data.get('explanation'),
                notes=data.get('notes'),
                reflection_json=data.get('reflection_json'),
                explanation_json=data.get('explanation_json'),
                notes_json=data.get('notes_json'),
                primary_subject_ids=data.get('primary_subject_ids', []),
                secondary_subject_ids=data.get('secondary_subject_ids', []),
                tag_ids=data.get('tag_ids', [])
            )

            return serialize_response(True, data=self._serialize_question_entry(entry))

        except Exception as e:
            self._log_error(
                f'Error creating question entry: {e}',
                {
                    'entry_data_json_len': len(entry_data_json) if entry_data_json else 0,
                    'entry_data_json_preview': entry_data_json[:200] if entry_data_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to create entry: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getQuestionEntry(self, entry_id: int) -> str:
        """
        Get a question entry by ID.

        Args:
            entry_id: Entry ID

        Returns:
            JSON response with entry data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            entry = self.user_db.get_question_entry(entry_id)

            if not entry:
                return serialize_response(False, error='Entry not found')

            return serialize_response(True, data=self._serialize_question_entry(entry))

        except Exception as e:
            self._log_error(
                f'Error getting question entry: {e}',
                {'entry_id': entry_id},
            )
            return serialize_response(False, error=f'Failed to get entry: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getSessionEntries(self, session_id: int) -> str:
        """
        Get all entries for a session.

        Args:
            session_id: Session ID

        Returns:
            JSON response with list of entries
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            entries = self.user_db.get_session_entries(session_id)

            data = [self._serialize_question_entry(e) for e in entries]

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting session entries: {e}',
                {'session_id': session_id},
            )
            return serialize_response(False, error=f'Failed to get entries: {e}')

    @pyqtSlot(str, int, int, result=str)
    @instrumented_slot
    def getEntriesByQuestionId(self, question_id: str, exam_context_id: int, exclude_entry_id: int = -1) -> str:
        """
        Look up entries with the same question_id for auto-fill.

        Args:
            question_id: The user's question reference
            exam_context_id: Exam context to search within
            exclude_entry_id: Optional entry ID to exclude (-1 to include all)

        Returns:
            JSON response with list of matching entries
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            exclude_id = exclude_entry_id if exclude_entry_id > 0 else None
            entries = self.user_db.get_entries_by_question_id(
                question_id=question_id,
                exam_context_id=exam_context_id,
                exclude_entry_id=exclude_id
            )

            data = [self._serialize_question_entry(e) for e in entries]

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting entries by question ID: {e}',
                {
                    'question_id': question_id,
                    'exam_context_id': exam_context_id,
                    'exclude_entry_id': exclude_entry_id,
                },
            )
            return serialize_response(False, error=f'Failed to lookup entries: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateQuestionEntry(self, entry_id: int, updates_json: str) -> str:
        """
        Update a question entry.

        Args:
            entry_id: Entry ID
            updates_json: JSON string with updates

        Returns:
            JSON response with updated entry
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            updates = json.loads(updates_json)

            primary_subject_ids = updates.pop('primary_subject_ids', None)
            secondary_subject_ids = updates.pop('secondary_subject_ids', None)
            tag_ids = updates.pop('tag_ids', None)

            entry = self.user_db.update_question_entry(
                entry_id,
                primary_subject_ids=primary_subject_ids,
                secondary_subject_ids=secondary_subject_ids,
                tag_ids=tag_ids,
                **updates
            )

            return serialize_response(True, data=self._serialize_question_entry(entry))

        except Exception as e:
            self._log_error(
                f'Error updating question entry: {e}',
                {
                    'entry_id': entry_id,
                    'updates_json_len': len(updates_json) if updates_json else 0,
                    'updates_json_preview': updates_json[:200] if updates_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to update entry: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteQuestionEntry(self, entry_id: int) -> str:
        """
        Delete a question entry.

        Args:
            entry_id: Entry ID

        Returns:
            JSON response with delete result
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            self.user_db.delete_question_entry(entry_id)
            return serialize_response(True, data={'id': entry_id, 'deleted': True})

        except Exception as e:
            self._log_error(
                f'Error deleting question entry: {e}',
                {'entry_id': entry_id},
            )
            return serialize_response(False, error=f'Failed to delete entry: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getAllSubjectsForExam(self, exam_context_id: int) -> str:
        """
        Get all subjects for an exam context (for client-side fuzzy search).

        Args:
            exam_context_id: Exam context ID

        Returns:
            JSON response with list of subjects
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            exam_context = config.exam_name

            all_subjects = []

            def collect_subjects(nodes, parent_path=''):
                for node in nodes:
                    current_path = f"{parent_path} > {node.name}" if parent_path else node.name

                    all_subjects.append({
                        'id': node.id,
                        'name': node.name,
                        'path': current_path,
                        'level_type': node.level_type,
                        'weight': node.exam_weight_low or 0
                    })

                    if node.children:
                        collect_subjects(node.children, current_path)

            root_nodes = self.user_db.get_subject_hierarchy(exam_context)
            collect_subjects(root_nodes)

            return serialize_response(True, data=all_subjects)

        except Exception as e:
            self._log_error(
                f'Error getting all subjects: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(False, error=f'Failed to get subjects: {e}')

    @pyqtSlot(int, int, 'QVariant', result=str)
    @instrumented_slot
    def setPrimaryParentForEntry(
        self,
        entry_id: int,
        subject_node_id: int,
        primary_parent_id,
    ) -> str:
        """
        Set (or clear) the per-mapping primary-parent context.

        Per ``docs/planning/POLYHIERARCHY_MIGRATION.md`` §3.3 / §5.4 this
        records which parent-context the user was navigating through
        when they tagged the entry. ``primary_parent_id`` may be ``None``
        (or any falsy non-int from JS) to clear the column back to NULL.

        Args:
            entry_id: Question entry ID.
            subject_node_id: Subject node tagged on the entry.
            primary_parent_id: Parent node ID for the rollup context, or
                ``None`` to clear.

        Returns:
            JSON response with ``{ok: true}``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            # Coerce JS-side falsy values (None, empty string, 0 from
            # ``QVariant`` unwrap) to a true SQL NULL when the caller
            # intends to clear context.
            if primary_parent_id in (None, '', 'null'):
                pp_id = None
            else:
                pp_id = int(primary_parent_id)

            with self.user_db.transaction():
                self.user_db.execute(
                    "UPDATE entry_subject_mappings "
                    "SET primary_parent_id = ? "
                    "WHERE question_entry_id = ? AND subject_node_id = ?",
                    (pp_id, entry_id, subject_node_id),
                )

            return serialize_response(True, data={'ok': True})

        except Exception as e:
            self._log_error(
                f'Error setting primary parent for entry: {e}',
                {
                    'entry_id': entry_id,
                    'subject_node_id': subject_node_id,
                    'primary_parent_id': primary_parent_id,
                },
            )
            return serialize_response(
                False, error=f'Failed to set primary parent for entry: {e}'
            )

    @pyqtSlot(int, str, int, result=str)
    @instrumented_slot
    def searchSubjects(self, exam_context_id: int, query: str, limit: int = 10) -> str:
        """
        Search subjects for autocomplete.

        Args:
            exam_context_id: Exam context ID
            query: Search query
            limit: Maximum results

        Returns:
            JSON response with matching subjects
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            results = self.user_db.search_subjects(exam_context_id, query, limit)
            return serialize_response(True, data=results)

        except Exception as e:
            self._log_error(
                f'Error searching subjects: {e}',
                {
                    'exam_context_id': exam_context_id,
                    'query': query,
                    'limit': limit,
                },
            )
            return serialize_response(False, error=f'Failed to search subjects: {e}')
