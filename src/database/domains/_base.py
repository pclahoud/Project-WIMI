"""WIMI Shared helper methods used across multiple domain mixins."""

import json
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger('wimi.graph')


class SharedHelpersMixin:
    """Mixin providing shared helper methods used by multiple domains.

    All methods access the database via ``self.execute()``, ``self.fetchone()``,
    ``self.fetchall()`` which are provided by ``BaseDatabase``.
    """

    # ------------------------------------------------------------------
    # Subject path helpers
    # ------------------------------------------------------------------

    def _build_subject_path(self, node_id: int) -> str:
        """Build full path string for a subject node.

        Graph-primary (P2.5): tries LadybugDB first, falls back to SQLite.

        Polyhierarchy migration: walks UPWARD via ``subject_edges``
        following only ``is_primary=TRUE`` edges — this yields the
        canonical breadcrumb path. Non-primary alternate paths are
        available via :meth:`EdgesMixin.get_paths_to_root`. Falls back
        to ``subject_nodes.parent_id`` if the ``subject_edges`` table
        doesn't exist (very old DBs predating m004).
        """
        # Try graph first — verify node exists in graph before trusting result
        if getattr(self, '_graph_read_ready', False):
            try:
                graph_node = self._graph_get_subject_node(node_id)
                if graph_node:
                    graph_path = self._graph_build_subject_path(node_id)
                    if graph_path:
                        return graph_path
            except Exception as e:
                logger.warning("Graph read failed for _build_subject_path, falling back to SQLite: %s", e)

        # SQLite fallback — walk upward via primary edges first;
        # fall back to subject_nodes.parent_id when no primary edge
        # exists (legacy nodes / tests that seed parent_id but not
        # subject_edges).
        parts: List[str] = []
        seen: set = set()
        current_id = node_id

        edges_available = self.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='subject_edges'"
        ) is not None

        while current_id and current_id not in seen:
            seen.add(current_id)
            row = self.fetchone(
                "SELECT name, parent_id FROM subject_nodes WHERE id = ?",
                (current_id,),
            )
            if not row:
                break
            parts.insert(0, row['name'])

            next_id = None
            if edges_available:
                parent_row = self.fetchone(
                    "SELECT parent_id FROM subject_edges "
                    "WHERE child_id = ? AND is_primary = TRUE LIMIT 1",
                    (current_id,),
                )
                if parent_row is not None:
                    next_id = parent_row['parent_id']
            # Fall back to subject_nodes.parent_id when no primary edge
            # exists (legacy / partially-migrated data).
            if next_id is None:
                next_id = row['parent_id']
            current_id = next_id

            if len(parts) > 32:  # Safety check; deep DAGs allowed but bounded.
                break

        return ' > '.join(parts)

    # ------------------------------------------------------------------
    # Descendant helpers
    # ------------------------------------------------------------------

    def _get_descendant_node_ids(self, parent_id: int) -> List[int]:
        """Get all descendant node IDs recursively (excluding ``parent_id`` itself).

        Graph-primary (P2.5): tries LadybugDB first, falls back to SQLite.

        Polyhierarchy migration: descends via the ``subject_edges``
        junction table so a node reachable through multiple parents is
        still only included once (``UNION`` dedup in the recursive CTE).
        Falls back to ``subject_nodes.parent_id`` if ``subject_edges``
        doesn't exist (legacy DBs predating m004).
        """
        # Try graph first — verify parent node exists in graph before trusting result
        if getattr(self, '_graph_read_ready', False):
            try:
                graph_node = self._graph_get_subject_node(parent_id)
                if graph_node:
                    graph_ids = self._graph_get_descendant_ids(parent_id)
                    if graph_ids is not None:
                        return graph_ids
            except Exception as e:
                logger.warning("Graph read failed for _get_descendant_node_ids, falling back to SQLite: %s", e)

        # SQLite fallback. Use UNION (not UNION ALL) so an accidental
        # data cycle does not produce infinite recursion.
        edges_available = self.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='subject_edges'"
        ) is not None

        # If the parent has any direct edge children in subject_edges,
        # use the edge-based traversal (polyhierarchy-aware). Otherwise
        # fall back to the legacy parent_id walk. This dual mode keeps
        # tests that seed subject_nodes via raw INSERT (without
        # populating subject_edges) working unchanged.
        has_edge_children = False
        if edges_available:
            row = self.fetchone(
                "SELECT 1 FROM subject_edges WHERE parent_id = ? LIMIT 1",
                (parent_id,),
            )
            has_edge_children = row is not None

        if has_edge_children:
            rows = self.fetchall(
                """
                WITH RECURSIVE descendants(id) AS (
                    SELECT child_id FROM subject_edges WHERE parent_id = :root
                    UNION
                    SELECT se.child_id FROM subject_edges se
                    JOIN descendants d ON se.parent_id = d.id
                )
                SELECT DISTINCT d.id
                FROM descendants d
                JOIN subject_nodes sn ON sn.id = d.id
                WHERE sn.status = 'active'
                """,
                {"root": parent_id},
            )
            return [row['id'] for row in rows]

        # Legacy fallback: walk parent_id directly.
        children = self.fetchall(
            "SELECT id FROM subject_nodes WHERE parent_id = ? AND status = 'active'",
            (parent_id,),
        )
        descendant_ids: List[int] = []
        for child in children:
            child_id = child['id']
            descendant_ids.append(child_id)
            descendant_ids.extend(self._get_descendant_node_ids(child_id))
        return descendant_ids

    def _build_descendant_cte(self, node_id: int) -> str:
        """Build a CTE SQL fragment that selects all descendant IDs for a node.

        Polyhierarchy migration: descend via ``subject_edges`` (the
        junction table) rather than ``subject_nodes.parent_id``. Uses
        ``UNION`` (not ``UNION ALL``) so an accidental data cycle does
        not produce infinite recursion. The CTE includes the seed
        ``node_id`` itself so callers can use
        ``IN (SELECT id FROM descendants)`` for "this node and all
        descendants" queries.

        Returns SQL text like::

            WITH RECURSIVE descendants AS (
                SELECT id FROM subject_nodes WHERE id = <node_id> AND status = 'active'
                UNION
                SELECT sn.id FROM subject_nodes sn
                JOIN subject_edges se ON se.child_id = sn.id
                JOIN descendants d ON se.parent_id = d.id
                WHERE sn.status = 'active'
            )
        """
        return f"""
            WITH RECURSIVE descendants AS (
                SELECT id FROM subject_nodes WHERE id = {node_id} AND status = 'active'
                UNION
                SELECT sn.id FROM subject_nodes sn
                JOIN subject_edges se ON se.child_id = sn.id
                JOIN descendants d ON se.parent_id = d.id
                WHERE sn.status = 'active'
            )
        """

    # ------------------------------------------------------------------
    # Entry relation helpers (used by entries, media, notes, analytics)
    # ------------------------------------------------------------------

    def _get_entry_subjects(self, entry_id: int, mapping_type: str) -> list:
        """Get subjects mapped to an entry"""
        from ..models import SubjectNode

        rows = self.fetchall("""
            SELECT sn.* FROM subject_nodes sn
            JOIN entry_subject_mappings esm ON sn.id = esm.subject_node_id
            WHERE esm.question_entry_id = ? AND esm.mapping_type = ?
        """, (entry_id, mapping_type))

        return [SubjectNode.from_db_row(row) for row in rows]

    def _get_entry_tags(self, entry_id: int) -> list:
        """Get tags assigned to an entry"""
        from ..models import Tag

        rows = self.fetchall("""
            SELECT t.* FROM tags t
            JOIN entry_tags et ON t.id = et.tag_id
            WHERE et.question_entry_id = ?
        """, (entry_id,))

        return [Tag.from_db_row(row) for row in rows]

    def _get_entry_media(self, entry_id: int) -> list:
        """Get media attached to an entry via junction table"""
        from ..models import EntryMedia

        rows = self.fetchall("""
            SELECT em.* FROM entry_media em
            JOIN entry_media_mapping emm ON em.id = emm.media_id
            WHERE emm.question_entry_id = ?
            AND emm.is_active = 1
            ORDER BY emm.sort_order
        """, (entry_id,))

        return [EntryMedia.from_db_row(row) for row in rows]

    def _get_entry_notes(self, entry_id: int) -> list:
        """Get notes attached to an entry (private helper for populating QuestionEntry).

        Reads via ``entry_note_attachments`` (m008) so a single note may
        appear on multiple entries — the Wave R3 "Reuse from other
        entries" UX depends on this. Falls back to the legacy direct
        ``entry_notes.question_entry_id`` lookup when the junction table
        is missing (covers pre-m008 DBs that an isolated-migration test
        might construct, and stays out of the way of the existing
        Phase 9 test fixtures that drop and recreate ``entry_notes``).

        Each returned note has an ``attachment_count`` attribute attached
        (computed, not a column) — the Wave R3 delete-confirmation modal
        needs it to warn the user when removing a note that other entries
        reference.
        """
        from ..models import EntryNote

        # Check table exists
        tables = self.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name='entry_notes'")
        if not tables:
            return []

        junction_tables = self.fetchall(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='entry_note_attachments'"
        )
        if junction_tables:
            # Many-to-many read path with a defensive legacy-fallback
            # UNION. Two row sources:
            #
            # 1. Notes joined via the junction table (the canonical
            #    Wave R3 path — includes both originating attachments
            #    written by ``add_entry_note`` and reuse attachments
            #    written by ``attach_existing_note_to_entry``).
            # 2. Notes whose legacy ``entry_notes.question_entry_id``
            #    matches but which have NO junction row at all (covers
            #    pre-m008 DBs that bypass the migration, e.g. tests
            #    that drop+recreate ``entry_notes`` via the legacy
            #    ``_ensure_entry_notes_table`` helper). Without this
            #    branch the legacy-migration tests in
            #    ``tests/database/test_entry_notes.py`` lose their
            #    backfilled rows.
            #
            # The fallback is intentionally restrictive: we only pull
            # in a legacy row when no junction row exists for that
            # note at all. The moment any junction row appears for the
            # note, it becomes the source of truth and the legacy
            # ``question_entry_id`` becomes "originator pointer" only.
            rows = self.fetchall(
                """
                SELECT en.*,
                       ena.sort_order AS attachment_sort_order,
                       (SELECT COUNT(*) FROM entry_note_attachments
                        WHERE note_id = en.id) AS attachment_count
                FROM entry_notes en
                JOIN entry_note_attachments ena ON ena.note_id = en.id
                WHERE ena.question_entry_id = ?
                UNION ALL
                SELECT en.*,
                       en.sort_order AS attachment_sort_order,
                       1 AS attachment_count
                FROM entry_notes en
                WHERE en.question_entry_id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM entry_note_attachments
                      WHERE note_id = en.id
                  )
                ORDER BY attachment_sort_order, id
                """,
                (entry_id, entry_id),
            )
        else:
            # Legacy 1:1 path (pre-m008 DBs only — exercised by tests
            # that drop the junction table entirely).
            rows = self.fetchall(
                """
                SELECT *, 1 AS attachment_count
                FROM entry_notes
                WHERE question_entry_id = ?
                ORDER BY sort_order, id
                """,
                (entry_id,),
            )

        notes = []
        for row in rows:
            note = EntryNote.from_db_row(row)
            if note is not None:
                # attachment_count is computed, not a model column —
                # attach it dynamically so the serializer can surface it
                # without bloating the dataclass.
                try:
                    note.attachment_count = int(row['attachment_count'])
                except (KeyError, TypeError, ValueError):
                    note.attachment_count = 1
            notes.append(note)
        return [n for n in notes if n is not None]

    # ------------------------------------------------------------------
    # Entry / subject conversion helpers
    # ------------------------------------------------------------------

    def _entry_to_dict(self, entry) -> Dict[str, Any]:
        """Convert QuestionEntry to dictionary"""
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
            # Rich text JSON fields (Phase 8)
            'reflection_json': entry.reflection_json,
            'explanation_json': entry.explanation_json,
            'notes_json': entry.notes_json,
            'is_draft': entry.is_draft,
            'draft_missing_fields': entry.draft_missing_fields,
            'completed_at': entry.completed_at.isoformat() if entry.completed_at else None,
            'created_at': entry.created_at.isoformat() if entry.created_at else None,
            'updated_at': entry.updated_at.isoformat() if entry.updated_at else None,
            'primary_subjects': [
                self._subject_with_dimension(s)
                for s in (entry.primary_subjects or [])
            ],
            'secondary_subjects': [
                self._subject_with_dimension(s)
                for s in (entry.secondary_subjects or [])
            ],
            'tags': [
                {'id': t.id, 'name': t.tag_name, 'color': t.color_hex}
                for t in (entry.tags or [])
            ],
            'media': [
                {
                    'id': m.id,
                    'file_uuid': m.file_uuid,
                    'filename': m.user_filename or m.original_filename,
                    'mime_type': m.mime_type
                }
                for m in (entry.media or [])
            ],
            'notes_list': [
                n.to_dict() for n in (entry.notes_list or [])
            ]
        }

    def _subject_with_dimension(self, subject) -> Dict[str, Any]:
        """
        Build subject dict with dimension info.

        Args:
            subject: SubjectNode object or object with id, name attributes

        Returns:
            Dict with id, name, path, and dimension info if available
        """
        subject_dict = {
            'id': subject.id,
            'name': subject.name,
            'path': self._build_subject_path(subject.id)
        }

        # Try to get dimension info for this subject
        dim_info = self.fetchone("""
            SELECT sn.dimension_id, d.name as dimension_name
            FROM subject_nodes sn
            LEFT JOIN exam_dimensions d ON sn.dimension_id = d.id
            WHERE sn.id = ?
        """, (subject.id,))

        if dim_info and dim_info['dimension_id']:
            subject_dict['dimension_id'] = dim_info['dimension_id']
            subject_dict['dimension_name'] = dim_info['dimension_name']

        return subject_dict
