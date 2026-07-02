"""WIMI shared serialization helpers for bridge mixins."""


class SerializerMixin:
    """Shared serialization methods. Composed into DatabaseBridge."""

    def _get_media_data_url(self, entry_id: int, file_uuid: str, thumbnail: bool = False) -> str:
        """
        Get a data URL for media (base64-encoded for direct embedding).

        Args:
            entry_id: Question entry ID
            file_uuid: File UUID
            thumbnail: Whether to get thumbnail or full image

        Returns:
            Data URL string (data:mime/type;base64,...)
        """
        if not hasattr(self, 'media_manager') or not self.media_manager:
            return ''

        try:
            if thumbnail:
                return self.media_manager.get_thumbnail_as_base64(entry_id, file_uuid) or ''
            else:
                return self.media_manager.get_file_as_base64(entry_id, file_uuid) or ''
        except Exception as e:
            self._log_error(
                f"Error getting media data URL: {e}",
                {
                    'entry_id': entry_id,
                    'file_uuid': file_uuid,
                    'thumbnail': thumbnail,
                },
            )
            return ''

    def _serialize_question_entry(self, entry) -> dict:
        """Serialize a QuestionEntry to a dictionary."""
        # Per-mapping parent-context lookup. POLYHIERARCHY_MIGRATION §3.3 /
        # §5.4: ``entry_subject_mappings.primary_parent_id`` records which
        # parent the entry rolls up through; surfacing it here lets the
        # question-entry form's "Tag context" pill round-trip on reload
        # (§7.3) without an extra bridge call per subject.
        primary_parent_contexts: dict = {}
        if entry.id is not None and getattr(self, 'user_db', None) is not None:
            try:
                rows = self.user_db.fetchall(
                    "SELECT subject_node_id, primary_parent_id "
                    "FROM entry_subject_mappings "
                    "WHERE question_entry_id = ? AND mapping_type = 'primary'",
                    (entry.id,),
                )
                primary_parent_contexts = {
                    r['subject_node_id']: r['primary_parent_id']
                    for r in rows
                }
            except Exception:
                primary_parent_contexts = {}

        return {
            'id': entry.id,
            'review_session_id': entry.review_session_id,
            'entry_order': entry.entry_order,
            'question_id': entry.question_id,
            'user_answer': entry.user_answer,
            'correct_answer': entry.correct_answer,
            'perceived_difficulty': entry.perceived_difficulty,
            'time_spent_seconds': entry.time_spent_seconds,
            'reflection': entry.reflection,
            'explanation': entry.explanation,
            'notes': entry.notes,
            'reflection_json': entry.reflection_json,
            'explanation_json': entry.explanation_json,
            'notes_json': entry.notes_json,
            'is_draft': entry.is_draft,
            'draft_missing_fields': entry.draft_missing_fields,
            'created_at': entry.created_at,
            'updated_at': entry.updated_at,
            'completed_at': entry.completed_at,
            'primary_subjects': [{
                'id': s.id,
                'name': s.name,
                'level_type': s.level_type,
                'primary_parent_id': primary_parent_contexts.get(s.id),
            } for s in (entry.primary_subjects or [])],
            'secondary_subjects': [{
                'id': s.id,
                'name': s.name,
                'level_type': s.level_type
            } for s in (entry.secondary_subjects or [])],
            'tags': [{
                'id': t.id,
                'name': t.tag_name,
                'color': t.color_hex
            } for t in (entry.tags or [])],
            'media': [{
                'id': m.id,
                'file_uuid': m.file_uuid,
                'original_filename': m.original_filename,
                'user_filename': m.user_filename,
                'mime_type': m.mime_type,
                'sort_order': m.sort_order,
                'dimension_id': m.dimension_id,
                'thumbnail_url': self._get_media_data_url(entry.id, m.file_uuid, thumbnail=True),
                'full_url': self._get_media_data_url(entry.id, m.file_uuid, thumbnail=False)
            } for m in (entry.media or [])],
            'notes_list': [
                self._serialize_entry_note(n) for n in (entry.notes_list or [])
            ]
        }

    def _serialize_entry_note(self, note) -> dict:
        """Serialize an EntryNote object to a dictionary.

        ``attachment_count`` is computed by the DB layer (number of rows
        in ``entry_note_attachments`` referencing this note) and attached
        dynamically to the EntryNote instance — see
        ``_get_entry_notes`` in ``database/domains/_base.py``. Code paths
        that build EntryNote objects without going through that helper
        (e.g. ``add_entry_note`` returning a freshly-inserted row) will
        not have it, so we default to 1 (the originating attachment).
        """
        return {
            'id': note.id,
            'question_entry_id': note.question_entry_id,
            'content_html': note.content_html,
            'content_json': note.content_json,
            'sort_order': note.sort_order,
            'linked_subject_ids': note.linked_subject_ids or [],
            'is_general': note.is_general,
            'is_migrated': note.is_migrated,
            'attachment_count': getattr(note, 'attachment_count', 1),
            'created_at': note.created_at.isoformat() if note.created_at else None,
            'updated_at': note.updated_at.isoformat() if note.updated_at else None
        }

    def _serialize_entry_media(self, media) -> dict:
        """Serialize an EntryMedia object to a dictionary with URLs."""
        entry_id = media.question_entry_id
        # Look up exam context names for this media (for global search display)
        exam_names = []
        if hasattr(self, 'user_db') and self.user_db:
            try:
                rows = self.user_db.fetchall("""
                    SELECT DISTINCT ec.name FROM entry_media_mapping emm
                    JOIN question_entries qe ON emm.question_entry_id = qe.id
                    JOIN review_sessions rs ON qe.review_session_id = rs.id
                    JOIN exam_contexts ec ON rs.exam_context_id = ec.id
                    WHERE emm.media_id = ?
                """, (media.id,))
                exam_names = [r['name'] for r in rows]
            except Exception:
                pass

        return {
            'id': media.id,
            'question_entry_id': entry_id,
            'file_uuid': media.file_uuid,
            'original_filename': media.original_filename,
            'user_filename': media.user_filename,
            'mime_type': media.mime_type,
            'file_size': media.file_size_bytes,
            'sort_order': media.sort_order,
            'dimension_id': media.dimension_id,
            'linked_subject_ids': media.linked_subject_ids or [],
            'exam_names': exam_names,
            'thumbnail_url': self._get_media_data_url(entry_id, media.file_uuid, thumbnail=True),
            'full_url': self._get_media_data_url(entry_id, media.file_uuid, thumbnail=False)
        }

    def _subject_node_to_dict(self, node) -> dict:
        """
        Convert a SubjectNode to a dictionary for JSON serialization.
        Includes all weight-related fields.
        """
        return {
            'id': node.id,
            'name': node.name,
            'exam_context': node.exam_context,
            'level_type': node.level_type,
            'parent_id': node.parent_id,
            'sort_order': node.sort_order,
            'exam_weight_low': node.exam_weight_low,
            'exam_weight_high': node.exam_weight_high,
            'exam_source': node.exam_source,
            'relative_weight': node.relative_weight,
            'weight_source': node.weight_source,
            'weight_locked': node.weight_locked,
            'has_absolute_weight': node.has_absolute_weight,
            'has_weight_range': node.has_weight_range,
            'has_relative_weight': node.has_relative_weight,
            'weight_midpoint': node.weight_midpoint,
            'weight_display': node.weight_display,
            'is_official_weight': node.is_official_weight,
            'can_edit_weight': node.can_edit_weight,
            'status': node.status
        }

    def _get_subject_mistake_counts(self, exam_context_id: int) -> dict:
        """
        Get mistake counts per subject for an exam context.

        Returns:
            Dictionary mapping subject_id to mistake count
        """
        query = """
            SELECT esm.subject_node_id, COUNT(DISTINCT qe.id) as count
            FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
            WHERE rs.exam_context_id = ? AND rs.user_id = ? AND esm.mapping_type = 'primary'
            GROUP BY esm.subject_node_id
        """
        rows = self.user_db.fetchall(query, (exam_context_id, self.user_db.user_id))
        return {row['subject_node_id']: row['count'] for row in rows}
