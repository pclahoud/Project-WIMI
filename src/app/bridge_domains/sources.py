"""WIMI Question Source bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class SourceBridgeMixin:
    """Bridge mixin for question source operations. Composed into DatabaseBridge."""

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createQuestionSource(self, source_data_json: str) -> str:
        """
        Create a new question source.

        Args:
            source_data_json: JSON string with source data

        Returns:
            JSON response with created source
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = json.loads(source_data_json)

            source = self.user_db.create_question_source(
                source_name=data['source_name'],
                source_type=data.get('source_type', 'other'),
                exam_context=data.get('exam_context'),
                description=data.get('description'),
                url=data.get('url'),
                total_questions=data.get('total_questions')
            )

            return serialize_response(True, data={
                'id': source.id,
                'user_id': source.user_id,
                'source_name': source.source_name,
                'source_type': source.source_type,
                'exam_context': source.exam_context,
                'description': source.description,
                'url': source.url,
                'total_questions': source.total_questions,
                'is_active': source.is_active,
                'created_at': source.created_at
            })

        except Exception as e:
            self._log_error(
                f'Error creating question source: {e}',
                {
                    'source_data_json_len': len(source_data_json),
                    'source_data_json_preview': source_data_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to create source: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getQuestionSources(self, exam_context: str = '') -> str:
        """
        Get question sources.

        Args:
            exam_context: Optional filter by exam context name

        Returns:
            JSON response with list of sources
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            sources = self.user_db.get_question_sources(
                exam_context=exam_context if exam_context else None
            )

            data = [{
                'id': s.id,
                'user_id': s.user_id,
                'source_name': s.source_name,
                'source_type': s.source_type,
                'exam_context': s.exam_context,
                'description': s.description,
                'url': s.url,
                'total_questions': s.total_questions,
                'is_active': s.is_active,
                'created_at': s.created_at
            } for s in sources]

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting question sources: {e}',
                {'exam_context': exam_context},
            )
            return serialize_response(False, error=f'Failed to get sources: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateQuestionSource(self, source_id: int, updates_json: str) -> str:
        """
        Update a question source.

        Args:
            source_id: Source ID
            updates_json: JSON string with updates

        Returns:
            JSON response with updated source
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            updates = json.loads(updates_json)
            source = self.user_db.update_question_source(source_id, **updates)

            return serialize_response(True, data={
                'id': source.id,
                'user_id': source.user_id,
                'source_name': source.source_name,
                'source_type': source.source_type,
                'exam_context': source.exam_context,
                'description': source.description,
                'url': source.url,
                'total_questions': source.total_questions,
                'is_active': source.is_active,
                'created_at': source.created_at
            })

        except Exception as e:
            self._log_error(
                f'Error updating question source: {e}',
                {
                    'source_id': source_id,
                    'updates_json_len': len(updates_json),
                    'updates_json_preview': updates_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to update source: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteQuestionSource(self, source_id: int) -> str:
        """
        Delete a question source (soft delete).

        Args:
            source_id: Source ID

        Returns:
            JSON response with delete result
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            self.user_db.delete_question_source(source_id)
            return serialize_response(True, data={'id': source_id, 'deleted': True})

        except Exception as e:
            self._log_error(
                f'Error deleting question source: {e}',
                {'source_id': source_id},
            )
            return serialize_response(False, error=f'Failed to delete source: {e}')
