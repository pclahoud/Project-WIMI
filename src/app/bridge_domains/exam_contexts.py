"""WIMI Exam Context bridge operations."""
import json
from datetime import date

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from ..bridge_helpers import serialize_response
from database.base_db import BaseDatabaseError
from database.domains.exam_contexts import ExamContextMixin as _ExamContextMixin
from database.exceptions import (
    ValidationError, ExamContextAlreadyExistsError, HierarchyLevelError
)


def _parse_optional_int(value: str) -> 'int | None':
    """Parse a string slot arg to an Optional[int].

    Empty / whitespace-only strings (the "no value" sentinel for slot
    args that are typed as ``str``) return ``None``. Non-numeric input
    raises ``ValueError`` so the caller can surface a clean error.
    """
    if value is None:
        return None
    stripped = str(value).strip()
    if stripped == '':
        return None
    return int(stripped)


class ExamContextBridgeMixin:
    """Bridge mixin for exam context operations. Composed into DatabaseBridge."""

    @pyqtSlot(str, str, str, str, str, str, result=str)
    @instrumented_slot
    def createExamContext(
        self,
        exam_name: str,
        exam_description: str = '',
        exam_date: str = '',
        weight_rules_json: str = '',
        hierarchy_levels_json: str = '',
        notes: str = ''
    ) -> str:
        """
        Create a new exam context.

        Args:
            exam_name: Name of the exam (required)
            exam_description: Optional description
            exam_date: Optional date in ISO format (YYYY-MM-DD)
            weight_rules_json: Optional JSON string of weight validation rules
            hierarchy_levels_json: Optional JSON string of hierarchy level names
            notes: Optional notes

        Returns:
            JSON response with created exam context data
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            exam_date_obj = None
            if exam_date:
                exam_date_obj = date.fromisoformat(exam_date)

            weight_rules = None
            if weight_rules_json:
                weight_rules = json.loads(weight_rules_json)

            hierarchy_levels = None
            if hierarchy_levels_json:
                hierarchy_levels = json.loads(hierarchy_levels_json)

            exam_context = self.user_db.create_exam_context(
                exam_name=exam_name,
                exam_description=exam_description if exam_description else None,
                exam_date=exam_date_obj,
                weight_validation_rules=weight_rules,
                hierarchy_levels=hierarchy_levels,
                notes=notes if notes else None
            )

            config = self.user_db.get_exam_context_config(exam_context.id)

            self.examContextCreated.emit(str(exam_context.id))

            return serialize_response(True, data={
                'id': config.id,
                'exam_name': config.exam_name,
                'exam_description': config.exam_description,
                'exam_date': config.exam_date,
                'is_active': config.is_active,
                'autonomous_balancing': config.autonomous_balancing,
                'precision': config.precision,
                'balancing_algorithm': config.balancing_algorithm,
                'requires_exact_100': config.requires_exact_100,
                'hierarchy_levels': config.default_hierarchy_levels,
                'notes': config.notes,
                'created_at': config.created_at
            })

        except ExamContextAlreadyExistsError as e:
            return serialize_response(False, error=f'Exam "{exam_name}" already exists')
        except ValidationError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error creating exam context: {e}',
                {
                    'exam_name': exam_name,
                    'exam_description': exam_description,
                    'exam_date': exam_date,
                    'has_weight_rules_json': bool(weight_rules_json),
                    'has_hierarchy_levels_json': bool(hierarchy_levels_json),
                    'notes_len': len(notes) if notes else 0,
                },
            )
            return serialize_response(False, error=f'Failed to create exam context: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getExamContext(self, exam_context_id: int) -> str:
        """Get exam context by ID."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.get_exam_context_config(exam_context_id)

            if not config:
                return serialize_response(False, error='Exam context not found')

            return serialize_response(True, data={
                'id': config.id,
                'exam_name': config.exam_name,
                'exam_description': config.exam_description,
                'exam_date': config.exam_date,
                'is_active': config.is_active,
                'autonomous_balancing': config.autonomous_balancing,
                'precision': config.precision,
                'balancing_algorithm': config.balancing_algorithm,
                'requires_exact_100': config.requires_exact_100,
                'hierarchy_levels': config.default_hierarchy_levels,
                'notes': config.notes,
                'created_at': config.created_at,
                # Stage 4 — length triple (always present in payload).
                'length_kind': config.length_kind,
                'length_min': config.length_min,
                'length_max': config.length_max,
                'length_typical': config.length_typical,
                'length_note': config.length_note,
            })

        except Exception as e:
            self._log_error(f'Error getting exam context: {e}', {'exam_context_id': exam_context_id})
            return serialize_response(False, error=f'Failed to get exam context: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getExamContextByName(self, exam_name: str) -> str:
        """Get exam context by name."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.get_exam_context_by_name(exam_name)

            if not config:
                return serialize_response(False, error='Exam context not found')

            return serialize_response(True, data={
                'id': config.id,
                'exam_name': config.exam_name,
                'exam_description': config.exam_description,
                'exam_date': config.exam_date,
                'is_active': config.is_active,
                'autonomous_balancing': config.autonomous_balancing,
                'precision': config.precision,
                'balancing_algorithm': config.balancing_algorithm,
                'requires_exact_100': config.requires_exact_100,
                'hierarchy_levels': config.default_hierarchy_levels,
                'notes': config.notes,
                'created_at': config.created_at
            })

        except Exception as e:
            self._log_error(f'Error getting exam context by name: {e}', {'exam_name': exam_name})
            return serialize_response(False, error=f'Failed to get exam context: {e}')

    @pyqtSlot(bool, result=str)
    @instrumented_slot
    def getAllExamContexts(self, active_only: bool = True) -> str:
        """Get all exam contexts."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            contexts = self.user_db.get_all_exam_contexts(active_only=active_only)

            data = [{
                'id': ctx.id,
                'exam_name': ctx.exam_name,
                'exam_description': ctx.exam_description,
                'exam_date': ctx.exam_date,
                'is_active': ctx.is_active,
                'created_date': ctx.created_date,
                'created_at': ctx.created_at,
            } for ctx in contexts]

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(
                f'Error getting all exam contexts: {e}',
                {'active_only': active_only},
            )
            return serialize_response(False, error=f'Failed to get exam contexts: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateExamContextSettings(self, exam_context_id: int, settings_json: str) -> str:
        """Update exam context settings."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            settings = json.loads(settings_json)

            kwargs = {}

            if 'exam_description' in settings:
                kwargs['exam_description'] = settings['exam_description']
            if 'exam_date' in settings:
                kwargs['exam_date'] = date.fromisoformat(settings['exam_date']) if settings['exam_date'] else None
            if 'is_active' in settings:
                kwargs['is_active'] = settings['is_active']
            if 'notes' in settings:
                kwargs['notes'] = settings['notes']

            weight_rules = {}
            if 'autonomous_balancing' in settings:
                weight_rules['autonomous_weight_balancing'] = settings['autonomous_balancing']
            if 'precision' in settings:
                weight_rules['precision_decimal_places'] = settings['precision']
            if 'balancing_algorithm' in settings:
                weight_rules['balancing_algorithm'] = settings['balancing_algorithm']
            if 'requires_exact_100' in settings:
                weight_rules['require_exact_100'] = settings['requires_exact_100']

            if weight_rules:
                kwargs['weight_validation_rules'] = weight_rules

            config = self.user_db.update_exam_context_settings(exam_context_id, **kwargs)

            self.examContextUpdated.emit(str(exam_context_id))

            return serialize_response(True, data={
                'id': config.id,
                'exam_name': config.exam_name,
                'exam_description': config.exam_description,
                'exam_date': config.exam_date,
                'is_active': config.is_active,
                'autonomous_balancing': config.autonomous_balancing,
                'precision': config.precision,
                'balancing_algorithm': config.balancing_algorithm,
                'requires_exact_100': config.requires_exact_100,
                'hierarchy_levels': config.default_hierarchy_levels,
                'notes': config.notes
            })

        except ValidationError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error updating exam context: {e}',
                {
                    'exam_context_id': exam_context_id,
                    'settings_json_len': len(settings_json) if settings_json else 0,
                },
            )
            return serialize_response(False, error=f'Failed to update exam context: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getHierarchyLevels(self, exam_context_id: int) -> str:
        """Get hierarchy levels for an exam context."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            levels = self.user_db.get_hierarchy_levels(exam_context_id)

            data = [{
                'id': level.id,
                'exam_context_id': level.exam_context_id,
                'level_name': level.level_name,
                'level_order': level.level_order,
                'is_required': level.is_required,
                'display_name_template': level.display_name_template,
                'is_custom_level': level.is_custom_level
            } for level in levels]

            return serialize_response(True, data=data)

        except Exception as e:
            self._log_error(f'Error getting hierarchy levels: {e}', {'exam_context_id': exam_context_id})
            return serialize_response(False, error=f'Failed to get hierarchy levels: {e}')

    @pyqtSlot(int, str, str, result=str)
    @instrumented_slot
    def addCustomHierarchyLevel(
        self,
        exam_context_id: int,
        level_name: str = '',
        display_name_template: str = ''
    ) -> str:
        """Add a custom hierarchy level beyond the default 5."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            level = self.user_db.add_custom_hierarchy_level(
                exam_context_id=exam_context_id,
                level_name=level_name if level_name else None,
                display_name_template=display_name_template if display_name_template else None
            )

            return serialize_response(True, data={
                'id': level.id,
                'exam_context_id': level.exam_context_id,
                'level_name': level.level_name,
                'level_order': level.level_order,
                'is_required': level.is_required,
                'display_name_template': level.display_name_template,
                'is_custom_level': level.is_custom_level
            })

        except HierarchyLevelError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error adding custom hierarchy level: {e}',
                {
                    'exam_context_id': exam_context_id,
                    'level_name': level_name,
                    'display_name_template': display_name_template,
                },
            )
            return serialize_response(False, error=f'Failed to add hierarchy level: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteExamContext(self, exam_context_id: int) -> str:
        """Soft-delete an exam context (sets is_active to False)."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.update_exam_context_settings(
                exam_context_id,
                is_active=False
            )

            if not config:
                return serialize_response(False, error='Exam context not found')

            return serialize_response(True, data={
                'id': exam_context_id,
                'deleted': True
            })

        except Exception as e:
            self._log_error(f'Error deleting exam context: {e}', {'exam_context_id': exam_context_id})
            return serialize_response(False, error=f'Failed to delete exam context: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def reactivateExamContext(self, exam_context_id: int) -> str:
        """Reactivate a suspended exam context (sets is_active to True)."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.update_exam_context_settings(
                exam_context_id,
                is_active=True
            )

            if not config:
                return serialize_response(False, error='Exam context not found')

            return serialize_response(True, data={
                'id': exam_context_id,
                'reactivated': True
            })

        except Exception as e:
            self._log_error(f'Error reactivating exam context: {e}', {'exam_context_id': exam_context_id})
            return serialize_response(False, error=f'Failed to reactivate exam context: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def hardDeleteExamContext(self, exam_context_id: int) -> str:
        """Permanently delete an exam context and all associated data."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            if config.is_active:
                return serialize_response(False, error='Exam must be suspended before permanent deletion')

            # Collect file_uuids for media cleanup before DB deletion cascades
            orphan_uuids = []
            if hasattr(self, 'media_manager') and self.media_manager:
                try:
                    rows = self.user_db.fetchall("""
                        SELECT DISTINCT em.file_uuid FROM entry_media em
                        JOIN entry_media_mapping emm ON em.id = emm.media_id
                        JOIN question_entries qe ON emm.question_entry_id = qe.id
                        JOIN review_sessions rs ON qe.review_session_id = rs.id
                        WHERE rs.exam_context_id = ?
                    """, (exam_context_id,))
                    orphan_uuids = [r['file_uuid'] for r in rows]
                except Exception:
                    pass

            deleted_entry_ids = self.user_db.hard_delete_exam_context(exam_context_id)

            # Clean up orphaned media files (junction rows cascaded on entry delete)
            if hasattr(self, 'media_manager') and self.media_manager and orphan_uuids:
                for file_uuid in orphan_uuids:
                    try:
                        # Check if this media is still linked to other entries
                        remaining = self.user_db.fetchone(
                            "SELECT COUNT(*) as cnt FROM entry_media_mapping WHERE media_id = ("
                            "  SELECT id FROM entry_media WHERE file_uuid = ?"
                            ")", (file_uuid,)
                        )
                        if not remaining or remaining['cnt'] == 0:
                            self.media_manager.delete_media(0, file_uuid)
                            self.user_db.execute(
                                "DELETE FROM entry_media WHERE file_uuid = ?",
                                (file_uuid,)
                            )
                    except Exception as media_err:
                        self._log_error(
                            f'Error cleaning up media {file_uuid}: {media_err}',
                            {
                                'exam_context_id': exam_context_id,
                                'file_uuid': file_uuid,
                            },
                        )

            return serialize_response(True, data={
                'id': exam_context_id,
                'permanently_deleted': True
            })

        except Exception as e:
            self._log_error(f'Error permanently deleting exam context: {e}', {'exam_context_id': exam_context_id})
            return serialize_response(False, error=f'Failed to permanently delete exam context: {e}')

    # ====================================================================
    # Stage 4 — Exam Length Triple bridge surface.
    # See HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md §3.2 (design) and
    # WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md "Stage 4" (scope). Args
    # are typed as ``str`` so empty strings can stand in for SQL NULL
    # (Qt's PyJSON marshalling makes this the cleanest cross-language
    # NULL contract for integer columns).
    # ====================================================================

    @pyqtSlot(int, str, str, str, str, str, result=str)
    @instrumented_slot
    def updateExamLength(
        self,
        exam_context_id: int,
        kind: str,
        min_str: str = '',
        max_str: str = '',
        typical_str: str = '',
        note: str = '',
    ) -> str:
        """Persist the exam-length triple for an exam context.

        Validates kind/value invariants in the user_db layer (see
        :func:`ExamContextMixin.update_exam_length`) and surfaces any
        failure as ``{success: false, error: ...}`` so the wizard can
        keep the focus on the offending input rather than crashing.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            length_min = _parse_optional_int(min_str)
            length_max = _parse_optional_int(max_str)
            length_typical = _parse_optional_int(typical_str)
        except ValueError as e:
            return serialize_response(
                False,
                error=f'Invalid integer length value: {e}',
            )

        try:
            config = self.user_db.update_exam_length(
                exam_context_id=exam_context_id,
                kind=kind,
                min=length_min,
                max=length_max,
                typical=length_typical,
                note=note if note else None,
            )

            self.examContextUpdated.emit(str(exam_context_id))

            return serialize_response(True, data={
                'ok': True,
                'length': {
                    'kind': config.length_kind,
                    'min': config.length_min,
                    'max': config.length_max,
                    'typical': config.length_typical,
                    'note': config.length_note,
                },
            })

        except BaseDatabaseError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error updating exam length: {e}',
                {
                    'exam_context_id': exam_context_id,
                    'kind': kind,
                    'min_str': min_str,
                    'max_str': max_str,
                    'typical_str': typical_str,
                    'note_len': len(note) if note else 0,
                },
            )
            return serialize_response(
                False,
                error=f'Failed to update exam length: {e}',
            )

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getExamLength(self, exam_context_id: int) -> str:
        """Return the exam-length triple for an exam context.

        ``length_kind`` is always present in the response — a NULL/empty
        value (unmigrated row) is coerced to ``'unknown'`` so JS can
        switch on it without first checking for null.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            length = self.user_db.get_exam_length(exam_context_id)
            return serialize_response(True, data=length)
        except BaseDatabaseError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error getting exam length: {e}',
                {'exam_context_id': exam_context_id},
            )
            return serialize_response(
                False,
                error=f'Failed to get exam length: {e}',
            )

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getKnownExamLength(self, exam_name: str) -> str:
        """Look up the canonical length data for a named exam.

        Used by the wizard to pre-fill the length step when the user
        types/selects a recognized standardized exam name (USMLE Step 1,
        NCLEX-RN, etc.). Returns ``{found: false}`` for unknown names so
        the JS can fall back to the empty form without a special-case
        error path.
        """
        spec = _ExamContextMixin.get_known_exam_length(exam_name)
        if not spec:
            return serialize_response(True, data={'found': False})
        return serialize_response(True, data={
            'found': True,
            'kind': spec['kind'],
            'min': spec.get('min'),
            'max': spec.get('max'),
            'typical': spec.get('typical'),
            'note': spec.get('note'),
        })

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getExamContextStats(self, exam_context_id: int) -> str:
        """Get statistics for an exam context."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            config = self.user_db.get_exam_context_config(exam_context_id)
            if not config:
                return serialize_response(False, error='Exam context not found')

            subject_count = 0
            question_count = 0

            try:
                subjects = self.user_db.get_subject_hierarchy(config.exam_name)

                def count_nodes(nodes):
                    count = 0
                    for node in nodes:
                        count += 1
                        if hasattr(node, 'children') and node.children:
                            count += count_nodes(node.children)
                    return count

                subject_count = count_nodes(subjects)

                questions = self.user_db.get_recent_questions(
                    exam_context=config.exam_name,
                    days_back=3650
                )
                question_count = len(questions) if questions else 0

            except Exception:
                pass

            return serialize_response(True, data={
                'subject_count': subject_count,
                'question_count': question_count,
                'weight_configured': subject_count > 0
            })

        except Exception as e:
            self._log_error(f'Error getting exam context stats: {e}', {'exam_context_id': exam_context_id})
            return serialize_response(False, error=f'Failed to get exam context stats: {e}')
