"""WIMI Tag bridge operations."""
from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from database.exceptions import TagError

from ..bridge_helpers import serialize_response


class TagBridgeMixin:
    """Bridge mixin for tag operations. Composed into DatabaseBridge."""

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getTagHierarchy(self, exam_context: str) -> str:
        """
        Get the error types an exam offers (its list, #888), as a tree.

        Each node carries ``usage_count`` (this exam's entries),
        ``entry_count_all`` (entries in every exam) and ``other_exam_count``
        (other exams that list it), which Manage Error Types reads to decide
        whether Delete for good may be offered.

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

    @pyqtSlot(str, str, int, str, result=str)
    @instrumented_slot
    def createTagInGroup(
        self,
        exam_context: str,
        tag_name: str,
        group_id: int,
        description: str = ''
    ) -> str:
        """
        Create a new tag within an existing group (for inline tag creation).

        #888 4a: the type is offered on this exam only. If the library
        already has that name in that group, the existing type is offered
        here instead of a copy being made.

        NOTE: QWebChannel dispatches by arity — the JS wrapper in
        ``src/web/js/api/tags.js`` always passes all four arguments
        (defaulting description to '').

        Args:
            exam_context: Exam context name
            tag_name: Name of the new tag
            group_id: ID of the parent group
            description: Optional student-facing definition ('' means none)

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
                color_hex=color,
                description=description or None
            )

            return serialize_response(True, data={
                'id': tag.id,
                'name': tag.tag_name,
                'color': tag.color_hex,
                'description': tag.description,
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

    @pyqtSlot(int, result=str)
    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def deleteTag(self, tag_id: int, exam_context: str = '') -> str:
        """
        Delete for good: remove a type (or an EMPTY group) from the library.

        Cascades untag the tag from every entry in every exam
        (``entry_tags`` / ``question_tags`` both declare ON DELETE CASCADE).
        Refused with a user-facing message (success=false) for a group that
        still contains types, and while another exam lists the type (#888
        decision 4b).

        Two registered signatures on purpose, as ``deleteSubjectNode`` has.
        ``deleteTag(int)`` is the pre-#888 contract and is refused whenever
        more than one exam lists the type. ``deleteTag(int, str)`` names the
        exam the student is on, and is refused when any OTHER exam lists it.
        QWebChannel resolves the two by argument count.

        Args:
            tag_id: Tag ID
            exam_context: Name of the exam the delete is made from ('' for none)

        Returns:
            JSON response with {'id', 'name', 'affected_entries'}
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            result = self.user_db.delete_tag(tag_id, exam_context or None)
            return serialize_response(True, data=result)

        except TagError as e:
            # Expected, user-facing failures (missing tag, non-empty
            # group, listed elsewhere) — relay the domain message verbatim.
            return serialize_response(False, error=str(e))

        except Exception as e:
            self._log_error(
                f'Error deleting tag: {e}',
                {'tag_id': tag_id, 'exam_context': exam_context},
            )
            return serialize_response(False, error=f'Failed to delete tag: {e}')

    @pyqtSlot(str, int, result=str)
    @instrumented_slot
    def addTagToExam(self, exam_context: str, tag_id: int) -> str:
        """
        Offer a library error type on an exam ("Add from your other exams", #888).

        A type brings its group; a group brings every type in it.

        Returns:
            JSON response with {'id', 'name', 'is_group', 'added'}
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            return serialize_response(
                True, data=self.user_db.add_tag_to_exam(exam_context, tag_id))
        except TagError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error adding tag to exam: {e}',
                {'exam_context': exam_context, 'tag_id': tag_id},
            )
            return serialize_response(False, error=f'Failed to add the error type: {e}')

    @pyqtSlot(str, int, result=str)
    @instrumented_slot
    def removeTagFromExam(self, exam_context: str, tag_id: int) -> str:
        """
        Remove from this exam: stop offering a type on one exam (#888).

        Deletes the exam's list row only. Entries keep the type and analytics
        still count it; a group takes the types listed under it here.

        Returns:
            JSON response with {'id', 'name', 'is_group', 'removed',
            'entries_keeping'}
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            return serialize_response(
                True, data=self.user_db.remove_tag_from_exam(exam_context, tag_id))
        except TagError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error removing tag from exam: {e}',
                {'exam_context': exam_context, 'tag_id': tag_id},
            )
            return serialize_response(False, error=f'Failed to remove the error type: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getTagsNotOnExam(self, exam_context: str) -> str:
        """
        The library's error types this exam does not offer, grouped (#888).

        Returns:
            JSON response with a list of nodes, each with 'id', 'name',
            'color', 'description', 'is_group', 'listed', 'exam_count',
            'entry_count_all' and 'children'
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            return serialize_response(
                True, data=self.user_db.get_tags_not_on_exam(exam_context))
        except TagError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error listing tags not on exam: {e}',
                {'exam_context': exam_context},
            )
            return serialize_response(False, error=f'Failed to list error types: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateTagDescription(self, tag_id: int, description: str) -> str:
        """
        Update a tag's description (student-facing definition).

        Empty/whitespace-only descriptions clear the definition (NULL).

        Args:
            tag_id: Tag ID
            description: New description ('' clears it)

        Returns:
            JSON response with {'id', 'description'}
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            tag = self.user_db.update_tag_description(tag_id, description)
            return serialize_response(True, data={
                'id': tag.id,
                'description': tag.description
            })

        except TagError as e:
            return serialize_response(False, error=str(e))

        except Exception as e:
            self._log_error(
                f'Error updating tag description: {e}',
                {'tag_id': tag_id},
            )
            return serialize_response(
                False, error=f'Failed to update tag description: {e}'
            )
