"""WIMI subject-relation bridge operations (issue #14).

Four slots, all of them thin: the decisions live in
``database/domains/relations.py`` and this layer only marshals.

``getSubjectRelations`` carries ``primary_parent_id`` because the deep
dive's context selector is what sets it — and it is worth saying here
too that the parameter **orders** the panel and never filters it
(decision 5). A future reader looking for the filter will not find one.

``createSubjectRelation`` surfaces a missing reason as a plain
``success=false`` with the database layer's message rather than a
stack-flavoured string, because that path is a normal user state
(decision 2: the reason is mandatory, and the UI has to say why).
"""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from database.exceptions import SubjectNodeError, ValidationError

from ..bridge_helpers import serialize_response


class RelationsBridgeMixin:
    """Bridge mixin for ``subject_relations``. Composed into DatabaseBridge."""

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getSubjectRelations(self, params_json: str) -> str:
        """Every visible relation touching a subject, context-ordered.

        Args:
            params_json: JSON with ``subject_id`` (required) and
                optional ``primary_parent_id`` — the deep dive's
                selected parent context, which reorders the list and
                hides nothing.

        Returns:
            JSON response whose ``data`` is the payload described by
            ``RelationsMixin.get_subject_relations``. An empty
            ``relations`` list is a success, not an error: zero
            relations is the normal state for months (decision 11) and
            the page renders nothing at all for it.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            params = json.loads(params_json) if params_json else {}
            subject_id = params.get('subject_id')
            if not subject_id:
                return serialize_response(False, error='subject_id is required')
            return serialize_response(True, data=self.user_db.get_subject_relations(
                subject_id=int(subject_id),
                primary_parent_id=params.get('primary_parent_id'),
            ))
        except SubjectNodeError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'Error getting subject relations: {e}',
                            {'params_json': params_json})
            return serialize_response(
                False, error=f'Failed to get subject relations: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createSubjectRelation(self, params_json: str) -> str:
        """Record one directional relation. The reason is mandatory.

        Args:
            params_json: JSON with ``from_subject_id``,
                ``to_subject_id``, ``reason`` (all required), plus
                optional ``strength`` (``-1`` is "checked — not
                related"), ``origin`` and ``source_entry_id``.

        Returns:
            JSON response with the created row, or ``success=false``
            carrying the reason it was refused. A blank reason lands
            here, and the message is written for the student.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            params = json.loads(params_json) if params_json else {}
            from_id = params.get('from_subject_id')
            to_id = params.get('to_subject_id')
            if not from_id or not to_id:
                return serialize_response(
                    False,
                    error='from_subject_id and to_subject_id are required')

            kwargs = {}
            if params.get('strength') is not None:
                kwargs['strength'] = int(params['strength'])
            if params.get('origin'):
                kwargs['origin'] = params['origin']
            if params.get('source_entry_id'):
                kwargs['source_entry_id'] = int(params['source_entry_id'])

            relation = self.user_db.create_subject_relation(
                int(from_id), int(to_id), params.get('reason'), **kwargs
            )
            return serialize_response(True, data=relation)
        except (ValidationError, SubjectNodeError) as e:
            # Expected refusals — a blank reason, a self-loop, a
            # duplicate, an archived endpoint. The user needs the
            # sentence, not a traceback.
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'Error creating subject relation: {e}',
                            {'params_json': params_json})
            return serialize_response(
                False, error=f'Failed to create relation: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteSubjectRelation(self, relation_id: int) -> str:
        """Remove a relation outright.

        Returns ``data={'deleted': false}`` when it was already gone,
        which is a success: the caller wanted it absent and it is.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            deleted = self.user_db.delete_subject_relation(int(relation_id))
            return serialize_response(True, data={'deleted': bool(deleted)})
        except Exception as e:
            self._log_error(f'Error deleting subject relation: {e}',
                            {'relation_id': relation_id})
            return serialize_response(
                False, error=f'Failed to delete relation: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def searchRelatableSubjects(self, params_json: str) -> str:
        """Candidates for a new relation from a subject.

        Args:
            params_json: JSON with ``subject_id`` (required),
                ``query``, optional ``limit``, and optional
                ``direction`` (``'outgoing'``/``'incoming'``) — which
                hides only the partners that direction already covers,
                so a cycle stays authorable from either end.

        Returns:
            JSON response with a list of candidates, each carrying its
            path, its dimension (relations may cross one — decision 6)
            and its current incoming count for the soft fan-in warning.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            params = json.loads(params_json) if params_json else {}
            subject_id = params.get('subject_id')
            if not subject_id:
                return serialize_response(False, error='subject_id is required')
            return serialize_response(
                True,
                data=self.user_db.search_relatable_subjects(
                    int(subject_id),
                    params.get('query') or '',
                    int(params.get('limit') or 10),
                    direction=params.get('direction'),
                ),
            )
        except SubjectNodeError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'Error searching relatable subjects: {e}',
                            {'params_json': params_json})
            return serialize_response(
                False, error=f'Failed to search subjects: {e}')
