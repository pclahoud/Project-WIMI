"""WIMI Entry browsing and filtering bridge operations."""
import json
from datetime import date

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class BrowsingBridgeMixin:
    """Bridge mixin for entry browsing/filtering operations. Composed into DatabaseBridge."""

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getEntriesPaginated(self, params_json: str) -> str:
        """
        Get paginated entries with comprehensive filtering.

        Args:
            params_json: JSON object with filter parameters:
                - exam_context_id: Optional int
                - session_id: Optional int
                - subject_ids: Optional array of ints
                - include_child_subjects: Optional bool (default False)
                - tag_ids: Optional array of ints
                - date_from: Optional ISO date string
                - date_to: Optional ISO date string
                - is_draft: Optional bool
                - search_query: Optional string
                - sort_by: Optional string ('date_desc', 'date_asc', 'difficulty_desc', 'difficulty_asc')
                - page: Optional int (default 1)
                - per_page: Optional int (default 20)

        Returns:
            JSON response with entries array and pagination info
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            params = json.loads(params_json)

            # Parse date parameters
            date_from = None
            date_to = None
            if params.get('date_from'):
                date_from = date.fromisoformat(params['date_from'])
            if params.get('date_to'):
                date_to = date.fromisoformat(params['date_to'])

            entries, total = self.user_db.get_entries_paginated(
                exam_context_id=params.get('exam_context_id'),
                session_id=params.get('session_id'),
                subject_ids=params.get('subject_ids'),
                include_child_subjects=params.get('include_child_subjects', False),
                tag_ids=params.get('tag_ids'),
                date_from=date_from,
                date_to=date_to,
                is_draft=params.get('is_draft'),
                search_query=params.get('search_query'),
                sort_by=params.get('sort_by', 'date_desc'),
                page=params.get('page', 1),
                per_page=params.get('per_page', 20),
                field_filters=params.get('field_filters'),
                subject_mode=params.get('subject_mode', 'or')
            )

            # Convert entries to dictionaries
            entries_data = [self.user_db._entry_to_dict(entry) for entry in entries]

            # Add session date to each entry
            for i, entry in enumerate(entries):
                session = self.user_db.get_review_session(entry.review_session_id)
                if session:
                    entries_data[i]['session_name'] = session.session_name
                    entries_data[i]['session_date'] = session.date_encountered.isoformat() if session.date_encountered else None

            page = params.get('page', 1)
            per_page = params.get('per_page', 20)

            return serialize_response(True, data={
                'entries': entries_data,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page
            })

        except Exception as e:
            self._log_error(
                f'Error getting paginated entries: {e}',
                {
                    'params_json_len': len(params_json) if params_json else 0,
                    'params_json_preview': params_json[:200] if params_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to get entries: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getEntryWithContext(self, entry_id: int) -> str:
        """
        Get a full entry with all context (session, exam, source info).

        Args:
            entry_id: Question entry ID

        Returns:
            JSON response with entry and context
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            result = self.user_db.get_entry_with_context(entry_id)

            if not result:
                return serialize_response(False, error='Entry not found')

            # Add media URLs if media manager is available
            if hasattr(self, 'media_manager') and self.media_manager:
                for media in result['entry'].get('media', []):
                    media['thumbnail_url'] = self._get_media_data_url(
                        entry_id, media['file_uuid'], thumbnail=True
                    )
                    media['full_url'] = self._get_media_data_url(
                        entry_id, media['file_uuid'], thumbnail=False
                    )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error getting entry with context: {e}',
                {'entry_id': entry_id},
            )
            return serialize_response(False, error=f'Failed to get entry: {e}')

    @pyqtSlot(int, int, int, result=str)
    @instrumented_slot
    def getRelatedSubjects(self, subject_id: int, exam_context_id: int, limit: int = 4) -> str:
        """
        Get related subjects for the 'Related Topics to Review' panel.

        Args:
            subject_id: Current subject ID
            exam_context_id: Exam context ID
            limit: Maximum results (default 4)

        Returns:
            JSON response with related subjects
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            related = self.user_db.get_related_subjects(
                subject_id=subject_id,
                exam_context_id=exam_context_id,
                limit=limit
            )

            return serialize_response(True, data=related)

        except Exception as e:
            self._log_error(
                f'Error getting related subjects: {e}',
                {
                    'subject_id': subject_id,
                    'exam_context_id': exam_context_id,
                    'limit': limit,
                },
            )
            return serialize_response(False, error=f'Failed to get related subjects: {e}')

    @pyqtSlot(str, int, int, result=str)
    @instrumented_slot
    def searchEntriesFulltext(self, query: str, exam_context_id: int, limit: int = 50) -> str:
        """
        Full-text search across entry fields.

        Args:
            query: Search query
            exam_context_id: Exam context ID (use -1 for all exams)
            limit: Maximum number of results

        Returns:
            JSON response with matching entries
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            # Use None if -1 passed (meaning all exams)
            ctx_id = exam_context_id if exam_context_id > 0 else None

            entries = self.user_db.search_entries_fulltext(
                query=query,
                exam_context_id=ctx_id,
                limit=limit
            )

            # Convert entries to dictionaries
            entries_data = [self.user_db._entry_to_dict(e) for e in entries]

            return serialize_response(True, data=entries_data)

        except Exception as e:
            self._log_error(
                f'Error searching entries: {e}',
                {
                    'query': query,
                    'exam_context_id': exam_context_id,
                    'limit': limit,
                },
            )
            return serialize_response(False, error=f'Failed to search entries: {e}')

    @pyqtSlot(str, str, result=str)
    @instrumented_slot
    def searchEntriesFulltext(self, query: str, exam_context_id_str: str = '') -> str:
        """
        Full-text search across entry fields.

        Args:
            query: Search query string
            exam_context_id_str: Optional exam context ID as string (empty for all)

        Returns:
            JSON response with matching entries
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            exam_context_id = int(exam_context_id_str) if exam_context_id_str else None

            entries = self.user_db.search_entries_fulltext(
                query=query,
                exam_context_id=exam_context_id,
                limit=50
            )

            entries_data = [self.user_db._entry_to_dict(entry) for entry in entries]

            return serialize_response(True, data=entries_data)

        except Exception as e:
            self._log_error(
                f'Error searching entries: {e}',
                {
                    'query': query,
                    'exam_context_id_str': exam_context_id_str,
                },
            )
            return serialize_response(False, error=f'Failed to search entries: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getEntryStatistics(self, exam_context_id_str: str = '') -> str:
        """
        Get statistics about entries for display.

        Args:
            exam_context_id_str: Optional exam context ID as string (empty for all)

        Returns:
            JSON response with entry statistics
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            exam_context_id = int(exam_context_id_str) if exam_context_id_str else None

            stats = self.user_db.get_entry_statistics(exam_context_id=exam_context_id)

            return serialize_response(True, data=stats)

        except Exception as e:
            self._log_error(
                f'Error getting entry statistics: {e}',
                {'exam_context_id_str': exam_context_id_str},
            )
            return serialize_response(False, error=f'Failed to get statistics: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getSessionsForFilter(self, exam_context_id: int) -> str:
        """
        Get review sessions for the session filter dropdown.

        Args:
            exam_context_id: Exam context ID

        Returns:
            JSON response with sessions list
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            sessions = self.user_db.get_review_sessions(
                exam_context_id=exam_context_id,
                include_completed=True,
                limit=50
            )

            sessions_data = [{
                'id': s.id,
                'name': s.session_name,
                'date': s.date_encountered.isoformat() if s.date_encountered else None,
                'entries_completed': s.entries_completed,
                'total_incorrect': s.total_incorrect,
                'status': s.session_status
            } for s in sessions]

            return serialize_response(True, data=sessions_data)

        except Exception as e:
            self._log_error(
                f'Error getting sessions for filter: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(False, error=f'Failed to get sessions: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getSubjectsForFilter(self, exam_context_id: int) -> str:
        """
        Get subjects hierarchy for the subject filter dropdown.

        Args:
            exam_context_id: Exam context ID

        Returns:
            JSON response with hierarchical subjects
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            # Get exam context name
            exam_config = self.user_db.get_exam_context_config(exam_context_id)
            if not exam_config:
                return serialize_response(False, error='Exam context not found')

            # Get full hierarchy
            hierarchy = self.user_db.get_subject_hierarchy(
                exam_context=exam_config.exam_name,
                parent_id=None,
                include_weights=False
            )

            # Batch-load aliases so the filter UI can match by alias too.
            aliases_by_subject: dict = {}
            for alias in self.user_db.get_aliases_for_exam(exam_config.exam_name):
                aliases_by_subject.setdefault(
                    alias.subject_node_id, []
                ).append(alias.alias_name)

            def build_tree(nodes):
                result = []
                for node in nodes:
                    node_aliases = aliases_by_subject.get(node.id, [])
                    result.append({
                        'id': node.id,
                        'name': node.name,
                        'level_type': node.level_type,
                        'aliases': node_aliases,
                        'aliasesString': ' '.join(node_aliases),
                        'children': build_tree(node.children) if node.children else []
                    })
                return result

            tree = build_tree(hierarchy)

            return serialize_response(True, data=tree)

        except Exception as e:
            self._log_error(
                f'Error getting subjects for filter: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(False, error=f'Failed to get subjects: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getTagsForFilter(self, exam_context_id: int) -> str:
        """
        Get tags hierarchy for the tag filter dropdown.

        Args:
            exam_context_id: Exam context ID

        Returns:
            JSON response with hierarchical tags
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            # Get exam context name
            exam_config = self.user_db.get_exam_context_config(exam_context_id)
            if not exam_config:
                return serialize_response(False, error='Exam context not found')

            # Get tag hierarchy
            hierarchy = self.user_db.get_tag_hierarchy(exam_config.exam_name)

            return serialize_response(True, data=hierarchy)

        except Exception as e:
            self._log_error(
                f'Error getting tags for filter: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(False, error=f'Failed to get tags: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def getSavedDelimiters(self) -> str:
        """Get all saved delimiters for the current user."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            delimiters = self.user_db.get_saved_delimiters()
            return serialize_response(True, data=delimiters)
        except Exception as e:
            # No slot params to include.
            self._log_error(f'Error getting saved delimiters: {e}')
            return serialize_response(False, error=f'Failed to get saved delimiters: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createSavedDelimiter(self, content_json: str) -> str:
        """
        Create a new saved delimiter.

        Args:
            content_json: JSON string with {name, value, hotkey}
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            data = json.loads(content_json) if content_json else {}
            delimiter = self.user_db.create_saved_delimiter(
                name=data.get('name', ''),
                value=data.get('value', ''),
                hotkey=data.get('hotkey')
            )
            return serialize_response(True, data=delimiter)
        except Exception as e:
            self._log_error(
                f'Error creating saved delimiter: {e}',
                {
                    'content_json_len': len(content_json) if content_json else 0,
                    'content_json_preview': content_json[:200] if content_json else '',
                },
            )
            return serialize_response(False, error=f'Failed to create saved delimiter: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteSavedDelimiter(self, delimiter_id: int) -> str:
        """Delete a saved delimiter."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            self.user_db.delete_saved_delimiter(delimiter_id)
            return serialize_response(True, data={'id': delimiter_id, 'deleted': True})
        except Exception as e:
            self._log_error(
                f'Error deleting saved delimiter: {e}',
                {'delimiter_id': delimiter_id},
            )
            return serialize_response(False, error=f'Failed to delete saved delimiter: {e}')
