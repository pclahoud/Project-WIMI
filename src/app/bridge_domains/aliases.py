"""WIMI Subject Alias bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class AliasBridgeMixin:
    """Bridge mixin for subject alias operations. Composed into DatabaseBridge."""

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getAllSubjectsWithAliasesForExam(self, exam_context_id: int) -> str:
        """
        Get all subjects for an exam with their aliases (for client-side fuzzy search).

        Args:
            exam_context_id: Exam context ID

        Returns:
            JSON response with list of subjects including aliases
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            exam_context = config.exam_name
            all_subjects = self.user_db.get_all_subjects_with_aliases_for_exam(exam_context)

            return serialize_response(True, data=all_subjects)

        except Exception as e:
            self._log_error(
                f'Error getting subjects with aliases: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(False, error=f'Failed to get subjects: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createSubjectAlias(self, alias_data_json: str) -> str:
        """
        Create a new alias for a subject.

        Args:
            alias_data_json: JSON string with alias data

        Returns:
            JSON response with created alias
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = json.loads(alias_data_json)

            alias = self.user_db.create_subject_alias(
                subject_node_id=data['subject_node_id'],
                exam_context=data['exam_context'],
                alias_name=data['alias_name'],
                alias_type=data.get('alias_type', 'alternate_name'),
                is_primary=data.get('is_primary', False),
                notes=data.get('notes')
            )

            return serialize_response(True, data=alias.to_dict())

        except Exception as e:
            _data = locals().get('data') if isinstance(locals().get('data'), dict) else {}
            self._log_error(
                f'Error creating alias: {e}',
                {
                    'subject_node_id': _data.get('subject_node_id'),
                    'exam_context': _data.get('exam_context'),
                    'alias_name': _data.get('alias_name'),
                    'alias_type': _data.get('alias_type'),
                    'is_primary': _data.get('is_primary'),
                },
            )
            return serialize_response(False, error=f'Failed to create alias: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getAliasesForSubject(self, subject_node_id: int) -> str:
        """
        Get all aliases for a specific subject.

        Args:
            subject_node_id: Subject node ID

        Returns:
            JSON response with list of aliases
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            aliases = self.user_db.get_aliases_for_subject(subject_node_id)
            return serialize_response(True, data=[a.to_dict() for a in aliases])

        except Exception as e:
            self._log_error(
                f'Error getting aliases: {e}',
                {'subject_node_id': subject_node_id},
            )
            return serialize_response(False, error=f'Failed to get aliases: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def updateSubjectAlias(self, update_data_json: str) -> str:
        """
        Update an existing alias.

        Args:
            update_data_json: JSON string with alias_id and fields to update

        Returns:
            JSON response with updated alias
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            data = json.loads(update_data_json)
            alias_id = data.pop('alias_id')

            alias = self.user_db.update_subject_alias(alias_id, **data)

            if alias:
                return serialize_response(True, data=alias.to_dict())
            else:
                return serialize_response(False, error='Alias not found')

        except Exception as e:
            _data = locals().get('data') if isinstance(locals().get('data'), dict) else {}
            self._log_error(
                f'Error updating alias: {e}',
                {
                    'alias_id': locals().get('alias_id'),
                    'update_fields': sorted(list(_data.keys())),
                },
            )
            return serialize_response(False, error=f'Failed to update alias: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteSubjectAlias(self, alias_id: int) -> str:
        """
        Delete an alias.

        Args:
            alias_id: Alias ID to delete

        Returns:
            JSON response with success status
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            deleted = self.user_db.delete_subject_alias(alias_id)

            if deleted:
                return serialize_response(True, data={'deleted': True})
            else:
                return serialize_response(False, error='Alias not found')

        except Exception as e:
            self._log_error(
                f'Error deleting alias: {e}',
                {'alias_id': alias_id},
            )
            return serialize_response(False, error=f'Failed to delete alias: {e}')

    @pyqtSlot(str, str, int, result=str)
    @instrumented_slot
    def checkAliasConflicts(self, exam_context: str, alias_name: str, exclude_subject_id: int = -1) -> str:
        """
        Check for existing subjects with conflicting aliases.

        Args:
            exam_context: Exam context name
            alias_name: Alias name to check
            exclude_subject_id: Subject ID to exclude from results (-1 for none)

        Returns:
            JSON response with list of conflicts
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            exclude_id = exclude_subject_id if exclude_subject_id > 0 else None
            conflicts = self.user_db.check_alias_conflicts(
                exam_context=exam_context,
                alias_name=alias_name,
                exclude_subject_id=exclude_id
            )

            return serialize_response(True, data={
                'has_conflicts': len(conflicts) > 0,
                'conflicts': conflicts
            })

        except Exception as e:
            self._log_error(
                f'Error checking alias conflicts: {e}',
                {
                    'exam_context': exam_context,
                    'alias_name': alias_name,
                    'exclude_subject_id': exclude_subject_id,
                },
            )
            return serialize_response(False, error=f'Failed to check conflicts: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def incrementAliasUsage(self, alias_id: int) -> str:
        """
        Increment the usage count for an alias.

        Args:
            alias_id: Alias ID

        Returns:
            JSON response with success status
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            self.user_db.increment_alias_usage(alias_id)
            return serialize_response(True, data={'success': True})

        except Exception as e:
            self._log_error(
                f'Error incrementing alias usage: {e}',
                {'alias_id': alias_id},
            )
            return serialize_response(False, error=f'Failed to update usage: {e}')
