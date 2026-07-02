"""WIMI Hierarchy Tag bridge operations for multi-dimensional question tagging."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class HierarchyTagBridgeMixin:
    """Bridge mixin for hierarchy tag operations. Composed into DatabaseBridge."""

    @pyqtSlot(int, int, int, result=str)
    @instrumented_slot
    def createHierarchyTag(
        self,
        entry_id: int,
        hierarchy_id: int,
        dimension_id: int
    ) -> str:
        """
        Tag a question entry with a hierarchy node in a specific dimension.

        This creates a link between a question entry and a hierarchy node,
        within the context of a specific dimension.

        Args:
            entry_id: ID of the question entry
            hierarchy_id: ID of the hierarchy node (subject_nodes)
            dimension_id: ID of the dimension

        Returns:
            JSON response with created tag data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            tag_id = self.user_db.create_hierarchy_tag(
                entry_id=entry_id,
                hierarchy_id=hierarchy_id,
                dimension_id=dimension_id
            )

            return serialize_response(True, data={
                'id': tag_id,
                'entry_id': entry_id,
                'hierarchy_id': hierarchy_id,
                'dimension_id': dimension_id
            })

        except Exception as e:
            self._log_error(f'Error creating hierarchy tag: {e}', {
                'entry_id': entry_id,
                'hierarchy_id': hierarchy_id,
                'dimension_id': dimension_id
            })
            return serialize_response(False, error=f'Failed to create hierarchy tag: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getEntryHierarchyTags(self, entry_id: int) -> str:
        """
        Get all hierarchy tags for a question entry.

        Returns tags ordered by dimension display_order, with dimension
        and hierarchy names included.

        Args:
            entry_id: ID of the question entry

        Returns:
            JSON response with list of tags
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            tags = self.user_db.get_entry_tags(entry_id)

            return serialize_response(True, data=tags)

        except Exception as e:
            self._log_error(f'Error getting entry tags: {e}', {
                'entry_id': entry_id
            })
            return serialize_response(False, error=f'Failed to get entry tags: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteHierarchyTag(self, tag_id: int) -> str:
        """
        Delete a single hierarchy tag.

        Args:
            tag_id: ID of the tag to delete

        Returns:
            JSON response with success/failure
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            rows_affected = self.user_db.delete_hierarchy_tag(tag_id)

            if rows_affected == 0:
                return serialize_response(False, error='Tag not found')

            return serialize_response(True, data={
                'id': tag_id,
                'deleted': True
            })

        except Exception as e:
            self._log_error(f'Error deleting hierarchy tag: {e}', {
                'tag_id': tag_id
            })
            return serialize_response(False, error=f'Failed to delete tag: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def deleteEntryTagsByDimension(self, entry_id: int, dimension_id: int) -> str:
        """
        Delete all tags for a question entry in a specific dimension.

        Useful when changing a selection - remove old tags before adding new ones.

        Args:
            entry_id: ID of the question entry
            dimension_id: ID of the dimension

        Returns:
            JSON response with number of deleted tags
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            rows_affected = self.user_db.delete_entry_tags_by_dimension(
                entry_id=entry_id,
                dimension_id=dimension_id
            )

            return serialize_response(True, data={
                'entry_id': entry_id,
                'dimension_id': dimension_id,
                'deleted_count': rows_affected
            })

        except Exception as e:
            self._log_error(f'Error deleting entry tags by dimension: {e}', {
                'entry_id': entry_id,
                'dimension_id': dimension_id
            })
            return serialize_response(False, error=f'Failed to delete tags: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def validateEntryDimensions(self, entry_id: int, exam_context_id: int) -> str:
        """
        Validate that an entry has all required dimension tags.

        Args:
            entry_id: ID of the question entry
            exam_context_id: ID of the exam context

        Returns:
            JSON response with validation result:
                - is_complete: bool
                - missing_dimensions: list of missing required dimension IDs
                - tagged_dimensions: list of tagged dimension IDs
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            result = self.user_db.validate_entry_dimensions_complete(
                entry_id=entry_id,
                exam_id=exam_context_id
            )

            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(f'Error validating entry dimensions: {e}', {
                'entry_id': entry_id,
                'exam_context_id': exam_context_id
            })
            return serialize_response(False, error=f'Failed to validate dimensions: {e}')
