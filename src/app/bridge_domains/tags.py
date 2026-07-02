"""WIMI Tag bridge operations."""
from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class TagBridgeMixin:
    """Bridge mixin for tag operations. Composed into DatabaseBridge."""

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getTagHierarchy(self, exam_context: str) -> str:
        """
        Get tag hierarchy for an exam context.

        Args:
            exam_context: Exam context name

        Returns:
            JSON response with tag hierarchy
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            hierarchy = self.user_db.get_tag_hierarchy(exam_context)
            return serialize_response(True, data=hierarchy)

        except Exception as e:
            self._log_error(
                f'Error getting tag hierarchy: {e}',
                {'exam_context': exam_context},
            )
            return serialize_response(False, error=f'Failed to get tags: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def seedDefaultTags(self, exam_context: str) -> str:
        """
        Seed default tags for an exam context.

        Args:
            exam_context: Exam context name

        Returns:
            JSON response with result
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            self.user_db.seed_default_tags(exam_context)
            return serialize_response(True, data={'seeded': True})

        except Exception as e:
            self._log_error(
                f'Error seeding default tags: {e}',
                {'exam_context': exam_context},
            )
            return serialize_response(False, error=f'Failed to seed tags: {e}')

    @pyqtSlot(str, str, int, result=str)
    @instrumented_slot
    def createTagInGroup(self, exam_context: str, tag_name: str, group_id: int) -> str:
        """
        Create a new tag within an existing group (for inline tag creation).

        Args:
            exam_context: Exam context name
            tag_name: Name of the new tag
            group_id: ID of the parent group

        Returns:
            JSON response with created tag
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            parent_group = self.user_db.get_tag(group_id)
            color = parent_group.color_hex if parent_group else '#6B7280'

            tag = self.user_db.create_hierarchical_tag(
                exam_context=exam_context,
                tag_name=tag_name,
                group_id=group_id,
                color_hex=color
            )

            return serialize_response(True, data={
                'id': tag.id,
                'name': tag.tag_name,
                'color': tag.color_hex,
                'group_id': group_id,
                'is_group': False
            })

        except Exception as e:
            self._log_error(
                f'Error creating tag: {e}',
                {
                    'exam_context': exam_context,
                    'tag_name': tag_name,
                    'group_id': group_id,
                },
            )
            return serialize_response(False, error=f'Failed to create tag: {e}')
