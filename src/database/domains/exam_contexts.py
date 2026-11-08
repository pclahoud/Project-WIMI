"""WIMI Exam Contexts database operations."""

import json
import re
from typing import Optional, List, Dict, Any
from datetime import date
from ..base_db import DatabaseIntegrityError, BaseDatabaseError
from app_logging import ErrorCategory


# Stage 4: known exam length defaults used by ``seed_known_exam_lengths``.
# Source: ``HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`` §3.2 reference table.
# Each entry is ``(kind, min, max, typical, note)``. The seeder writes
# these into ``exam_contexts`` rows whose name matches (case-insensitive)
# AND whose ``length_kind`` is still ``'unknown'`` — never clobbers a
# user-set value. The exam-name list intentionally covers only well-known
# standardized exams; custom user exams stay ``unknown`` until the user
# fills the wizard.
KNOWN_EXAM_LENGTHS: Dict[str, Dict[str, Any]] = {
    "usmle step 1": {
        "kind": "fixed", "min": 280, "max": 280, "typical": 280, "note": None,
    },
    "usmle step 2 ck": {
        "kind": "fixed", "min": 318, "max": 318, "typical": 318, "note": None,
    },
    "mcat": {
        "kind": "fixed", "min": 230, "max": 230, "typical": 230, "note": None,
    },
    "gre general": {
        "kind": "fixed", "min": 54, "max": 54, "typical": 54, "note": None,
    },
    "nbme shelf": {
        "kind": "fixed", "min": 110, "max": 110, "typical": 110, "note": None,
    },
    "nclex-rn": {
        "kind": "range", "min": 85, "max": 150, "typical": 100,
        "note": "CAT — exam ends when the algorithm reaches a confident decision.",
    },
}


# #718: the tables that name their exam by TEXT, in an ``exam_context``
# column, rather than by ``exam_contexts.id``. None of these columns has a
# foreign key, so nothing in SQLite follows a rename. A rename that moved
# ``exam_contexts.exam_name`` alone would leave the subject tree, the aliases
# and the tags filed under a name no exam has. The exam would open empty, and
# the next exam created under the old name would inherit the lot.
# ``tests/database/test_exam_rename.py`` reads every table's columns off a live
# database and fails if one gains an ``exam_context`` column that is not
# listed here.
#
# ``tags`` left this list with m038 (#888). Error types are one library per
# profile, ``tags.exam_context`` is NULL on every row, and an exam's types are
# its ``exam_error_types`` rows, keyed by ``exam_contexts.id`` with ON DELETE
# CASCADE. So a rename moves nothing, and a permanent delete removes the
# exam's list by cascade and never a type: deleting types here is what took
# them off OTHER exams' entries through ``entry_tags``' cascade (#887).
# ``question_tags`` stays listed, as a legacy table.
EXAM_NAME_KEYED_TABLES = (
    "subject_nodes",
    "subject_aliases",
    "question_tags",
    "question_sources",
    "question_analyses",
    "question_topic_assignments",
)


class ExamContextMixin:
    """Mixin for exam context operations. Composed into UserDatabase."""

    # Default analytics config applied when column is NULL
    # The weight card's minimum before a subject can be over-represented
    # (#828, owner 2026-10-14). 3 to start with; 1 is the behaviour before.
    MIN_MISTAKES_TO_FLAG_DEFAULT = 3
    MIN_MISTAKES_TO_FLAG_RANGE = (1, 50)

    DEFAULT_ANALYTICS_CONFIG = {
        "default_dimension_id": None,
        "min_mistakes_to_flag": MIN_MISTAKES_TO_FLAG_DEFAULT,
        "chart_visibility": {
            "subject_sunburst": True,
            "tag_chart": True,
            "activity_chart": True,
            "activity_heatmap": True,
            "streak_stats": True,
            "weekly_goal": True,
            "difficulty_distribution": True,
            "difficulty_time": True,
            "patterns_insights": True,
            "cross_dimension_heatmap": True,
            "study_recommendations": True,
            "interaction_effects": True,
            "weight_analysis": True
        },
        "chart_sizes": {}
    }

    def create_exam_context(
        self,
        exam_name: str,
        exam_description: Optional[str] = None,
        exam_date: Optional[date] = None,
        weight_validation_rules: Optional[Dict[str, Any]] = None,
        hierarchy_levels: Optional[List[str]] = None,
        notes: Optional[str] = None
    ) -> 'ExamContextConfig':
        """
        Create a new exam context with default settings.

        Args:
            exam_name: Name of the exam (e.g., "USMLE Step 1")
            exam_description: Optional description
            exam_date: Optional scheduled exam date
            weight_validation_rules: Optional custom weight rules
            hierarchy_levels: Optional custom hierarchy level names
            notes: Optional notes

        Returns:
            ExamContextConfig object

        Raises:
            ExamContextAlreadyExistsError: If exam_name already exists for this user
            ExamContextError: If creation fails
        """
        # Ensure Phase 2 tables exist
        self._ensure_phase2_schema()

        # Import here to avoid circular imports
        from ..models import ExamContextConfig
        from ..exceptions import ValidationError, ExamContextAlreadyExistsError, ExamContextError

        # Default weight validation rules
        if weight_validation_rules is None:
            weight_validation_rules = {
                "autonomous_weight_balancing": True,
                "allow_absolute_weight_editing": False,
                "precision_decimal_places": 1,
                "require_exact_100": True,
                "balancing_algorithm": "proportional"
            }

        # Default hierarchy levels
        if hierarchy_levels is None:
            hierarchy_levels = ["System", "Subsystem", "Topic", "Subtopic", "Child"]

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO exam_contexts (
                        user_id, exam_name, exam_description, exam_date,
                        default_hierarchy_levels, weight_validation_rules, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.user_id,
                    exam_name,
                    exam_description,
                    exam_date.isoformat() if exam_date else None,
                    json.dumps(hierarchy_levels),
                    json.dumps(weight_validation_rules),
                    notes
                ))

                exam_context_id = cursor.lastrowid

                # Create hierarchy level definitions
                for order, level_name in enumerate(hierarchy_levels, start=1):
                    self.execute("""
                        INSERT INTO hierarchy_level_definitions (
                            exam_context_id, level_name, level_order,
                            is_required, is_custom_level
                        ) VALUES (?, ?, ?, ?, ?)
                    """, (
                        exam_context_id,
                        level_name,
                        order,
                        order <= 3,  # First 3 levels are required
                        False
                    ))

                # m026: every exam starts with the owner's list of relation
                # types. RelationsMixin owns the seed; reached through self.
                self.seed_relation_types_for_exam(exam_context_id)

                if self.error_logger:
                    self.error_logger.info(
                        f"Created exam context: {exam_name} (ID: {exam_context_id})",
                        category=ErrorCategory.DATABASE
                    )

                return self.get_exam_context_config(exam_context_id)

        except DatabaseIntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise ExamContextAlreadyExistsError(
                    f"Exam context '{exam_name}' already exists for this user"
                ) from e
            raise ExamContextError(f"Failed to create exam context: {e}") from e

    def get_exam_context_config(self, exam_context_id: int) -> Optional['ExamContextConfig']:
        """
        Get exam context configuration by ID.

        Args:
            exam_context_id: ID of the exam context

        Returns:
            ExamContextConfig object or None if not found
        """
        from ..models import ExamContextConfig

        row = self.fetchone(
            "SELECT * FROM exam_contexts WHERE id = ?",
            (exam_context_id,)
        )
        return ExamContextConfig.from_db_row(row) if row else None

    def get_exam_context_by_name(self, exam_name: str) -> Optional['ExamContextConfig']:
        """
        Get exam context configuration by name.

        Args:
            exam_name: Name of the exam

        Returns:
            ExamContextConfig object or None if not found
        """
        from ..models import ExamContextConfig

        row = self.fetchone(
            "SELECT * FROM exam_contexts WHERE user_id = ? AND exam_name = ?",
            (self.user_id, exam_name)
        )
        return ExamContextConfig.from_db_row(row) if row else None

    def get_all_exam_contexts(
        self,
        active_only: bool = True
    ) -> List['ExamContextConfig']:
        """
        Get all exam contexts for this user.

        Args:
            active_only: If True, only return active exam contexts

        Returns:
            List of ExamContextConfig objects
        """
        from ..models import ExamContextConfig

        query = "SELECT * FROM exam_contexts WHERE user_id = ?"
        params = [self.user_id]

        if active_only:
            query += " AND is_active = TRUE"

        query += " ORDER BY created_date DESC"

        rows = self.fetchall(query, tuple(params))
        return [ExamContextConfig.from_db_row(row) for row in rows]

    def update_exam_context_settings(
        self,
        exam_context_id: int,
        weight_validation_rules: Optional[Dict[str, Any]] = None,
        exam_description: Optional[str] = None,
        exam_date: Optional[date] = None,
        notes: Optional[str] = None,
        is_active: Optional[bool] = None,
        color_hex: Optional[str] = None,
        clear_color: bool = False,
        exam_name: Optional[str] = None,
        clear_exam_date: bool = False,
    ) -> 'ExamContextConfig':
        """
        Update exam context settings.

        Args:
            exam_context_id: ID of the exam context
            weight_validation_rules: New weight validation rules
            exam_description: New description
            exam_date: New exam date
            notes: New notes
            is_active: New active status
            exam_name: New name. The rename moves every row filed under the
                old name with it, in the same transaction (#718). See
                :meth:`_rename_exam_context`.
            clear_exam_date: Set the date back to NULL. ``exam_date=None``
                means "not supplied", so a clear needs its own flag, the
                same convention as ``clear_color`` (#718).

        Returns:
            Updated ExamContextConfig object
        """
        if exam_date is not None and clear_exam_date:
            from ..exceptions import ValidationError
            raise ValidationError(
                "An exam date cannot be set and cleared in the same update")

        updates = []
        params = []

        if weight_validation_rules is not None:
            updates.append("weight_validation_rules = ?")
            params.append(json.dumps(weight_validation_rules))

        if exam_description is not None:
            updates.append("exam_description = ?")
            params.append(exam_description)

        if exam_date is not None:
            updates.append("exam_date = ?")
            params.append(exam_date.isoformat())
        elif clear_exam_date:
            updates.append("exam_date = NULL")

        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        if is_active is not None:
            updates.append("is_active = ?")
            params.append(is_active)

        # #778 decision 9: the exam's own colour, '#rrggbb'. Validated here so
        # a bad string from the wizard is a sentence, not a stored value the
        # calendar then paints. clear_color=True sets it back to NULL.
        from ..exceptions import ValidationError
        if color_hex is not None:
            value = color_hex.strip().lower()
            if not re.fullmatch(r"#[0-9a-f]{6}", value):
                raise ValidationError(f"An exam colour is written #rrggbb, not {color_hex!r}")
            updates.append("color_hex = ?")
            params.append(value)
        elif clear_color:
            updates.append("color_hex = NULL")

        if not updates and exam_name is None:
            return self.get_exam_context_config(exam_context_id)

        # One transaction for the rename and the other settings: a refused
        # rename must not leave the date or description half-saved behind a
        # failure the wizard reports as a failure.
        with self.transaction():
            if exam_name is not None:
                self._rename_exam_context(exam_context_id, exam_name)
            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(exam_context_id)
                self.execute(f"""
                    UPDATE exam_contexts
                    SET {', '.join(updates)}
                    WHERE id = ?
                """, tuple(params))

        return self.get_exam_context_config(exam_context_id)

    def _rename_exam_context(self, exam_context_id: int, new_name: str) -> None:
        """Rename an exam and everything filed under its name (#718).

        Called inside :meth:`update_exam_context_settings`'s transaction.
        Raises ``ValidationError`` with a sentence for each refusal, so the
        bridge returns ``success=false`` carrying it and the wizard shows
        it as an error instead of a success (#240).

        Two names are refused:

        * **one another exam holds**, suspended exams included. They keep
          their name (``idx_unique_exam_name_per_user`` covers every row,
          and nothing parks an exam's name the way #244 parks a
          dimension's), so the INSERT path's IntegrityError would otherwise
          come from three frames down.
        * **one rows are still filed under with no exam holding it.** Every
          table in :data:`EXAM_NAME_KEYED_TABLES` links to its exam by
          name, without a foreign key, so a permanently deleted exam leaves
          its rows there. Renaming into that name would silently adopt a
          deleted exam's subject tree.
        """
        from ..exceptions import ValidationError

        name = (new_name or "").strip()
        if not name:
            raise ValidationError("An exam needs a name")
        row = self.fetchone(
            "SELECT exam_name FROM exam_contexts WHERE id = ?",
            (exam_context_id,))
        if row is None:
            raise ValidationError(f"Exam {exam_context_id} does not exist")
        old_name = row["exam_name"]
        if name == old_name:
            return

        taken = self.fetchone(
            "SELECT is_active FROM exam_contexts"
            " WHERE user_id = ? AND exam_name = ? AND id != ?",
            (self.user_id, name, exam_context_id))
        if taken is not None:
            where = "" if taken["is_active"] else " (it is suspended)"
            raise ValidationError(
                f"Another exam is already called \"{name}\"{where}. "
                f"Choose a different name.")

        for table in EXAM_NAME_KEYED_TABLES:
            if self.fetchone(
                    f"SELECT 1 FROM {table} WHERE exam_context = ? LIMIT 1",
                    (name,)) is not None:
                raise ValidationError(
                    f"\"{name}\" still has data from an exam that was "
                    f"permanently deleted, so renaming this exam to it "
                    f"would take that data over. Choose a different name.")

        self.execute(
            "UPDATE exam_contexts SET exam_name = ?,"
            " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (name, exam_context_id))
        for table in EXAM_NAME_KEYED_TABLES:
            self.execute(
                f"UPDATE {table} SET exam_context = ? WHERE exam_context = ?",
                (name, old_name))

    def hard_delete_exam_context(self, exam_context_id: int) -> List[int]:
        """
        Permanently delete an exam context and all associated data.
        The exam must already be suspended (is_active = FALSE).

        CASCADE constraints handle deletion of:
        - review_sessions (which CASCADE to question_entries, entry_media, etc.)
        - hierarchy_level_definitions
        - exam_dimensions (which CASCADE to question_hierarchy_tags, entry_subject_mappings)

        The tables in :data:`EXAM_NAME_KEYED_TABLES` are NOT reached by any
        cascade: they name the exam by text, with no foreign key. They are
        removed by :meth:`_delete_rows_filed_under_exam_name` in the same
        transaction (#873). Before that, the subject tree, aliases and tags
        outlived "delete permanently", and the next exam created with the
        same name opened on them.

        Error types are not the exam's to delete (#888). The exam's list,
        ``exam_error_types``, goes by cascade; every ``tags`` row and every
        other exam's ``entry_tags`` row stays (#887).

        Args:
            exam_context_id: ID of the exam context to permanently delete

        Returns:
            List of entry IDs that were deleted (for media file cleanup)

        Raises:
            ValueError: If exam not found or still active
        """
        # Verify exam exists and is suspended
        config = self.get_exam_context_config(exam_context_id)
        if not config:
            raise ValueError(f"Exam context {exam_context_id} not found")

        if config.is_active:
            raise ValueError("Exam must be suspended before permanent deletion")

        # Collect entry IDs for media cleanup before deletion
        entry_rows = self.fetchall("""
            SELECT qe.id FROM question_entries qe
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.exam_context_id = ?
        """, (exam_context_id,))
        deleted_entry_ids = [row['id'] for row in entry_rows]

        with self.transaction():
            # #848 decision 2 over every entry the cascade below will remove:
            # a note attached only to this exam's entries goes; one also
            # attached to an entry of another exam survives with a NULL origin.
            self.release_notes_from_entries(deleted_entry_ids)

            # #873: the rows that would block the cascade, or outlive it,
            # go first. See _delete_rows_filed_under_exam_name.
            sources = self._delete_rows_filed_under_exam_name(
                config.exam_name, exam_context_id)

            # Delete the exam context row - CASCADE handles related tables
            self.execute(
                "DELETE FROM exam_contexts WHERE id = ?",
                (exam_context_id,)
            )

            # Sources last: review_sessions references question_sources with
            # NO ACTION, so they can only go once the cascade above has
            # removed this exam's sessions.
            self._release_sources_filed_under_exam_name(sources)

            if self.error_logger:
                self.error_logger.info(
                    f"Permanently deleted exam context {exam_context_id} "
                    f"({len(deleted_entry_ids)} entries affected)",
                    category=ErrorCategory.DATABASE
                )

        return deleted_entry_ids

    def _delete_rows_filed_under_exam_name(
        self, exam_name: str, exam_context_id: int,
    ) -> List[int]:
        """Remove what a permanent delete must take that no cascade reaches (#873).

        Runs inside :meth:`hard_delete_exam_context`'s transaction, BEFORE the
        ``exam_contexts`` row goes. Returns the ids of the question sources
        filed under the name, which can only be handled after the cascade
        (see :meth:`_release_sources_filed_under_exam_name`).

        * ``subject_relation_rejections`` references ``subject_nodes`` with
          NO ACTION, so its rows would refuse the subject delete.
        * The subject delete journal (m018) names subjects by id with no
          foreign key. Left behind, its batches would point at nothing.
          Every batch with a root or an item among this exam's subjects is
          this exam's, and its items cascade with it.
        * The dimension journal (m024) carries ``exam_id`` with no foreign
          key, so its rows would outlive the exam too.
        * Then the name-keyed rows themselves. Deleting ``subject_nodes``
          cascades its edges, weights, relations, aliases, entry mappings and
          Anki rejections, all ``ON DELETE CASCADE`` on ``subject_nodes.id``.

        Free-standing notes (#848) are left alone even when tagged with these
        subjects. A free note is the student's own writing, attached to no
        entry. Its ``linked_subject_ids`` is JSON, so a stale id there is
        dropped by every read that joins it.
        """
        subject_ids = "SELECT id FROM subject_nodes WHERE exam_context = ?"
        self.execute(
            f"DELETE FROM subject_relation_rejections"
            f" WHERE from_subject_id IN ({subject_ids})"
            f" OR to_subject_id IN ({subject_ids})",
            (exam_name, exam_name))
        self.execute(
            f"DELETE FROM subject_delete_batches"
            f" WHERE root_node_id IN ({subject_ids})"
            f" OR id IN (SELECT batch_id FROM subject_delete_batch_items"
            f"           WHERE subject_node_id IN ({subject_ids}))",
            (exam_name, exam_name))
        self.execute(
            "DELETE FROM dimension_delete_batches WHERE exam_id = ?",
            (exam_context_id,))

        # Children before parents, so no statement depends on a cascade.
        # Not ``tags`` (#887, #888): error types belong to the profile, and
        # this exam's list goes with the exam_contexts row by cascade.
        for table in ("question_tags", "question_topic_assignments",
                      "question_analyses", "subject_aliases",
                      "subject_nodes"):
            self.execute(f"DELETE FROM {table} WHERE exam_context = ?",
                         (exam_name,))

        return [r["id"] for r in self.fetchall(
            "SELECT id FROM question_sources WHERE exam_context = ?",
            (exam_name,))]

    def _release_sources_filed_under_exam_name(self, source_ids: List[int]) -> None:
        """Delete this exam's question sources, or unfile any still in use (#873).

        A source filed under the exam is offered only to that exam, so after
        the cascade normally nothing references it and it is deleted. One
        that is still referenced, by another exam's session, a session
        template or a plan, is not deleted. That would fail on
        ``review_sessions``' NO ACTION, or quietly null a template's choice.
        It is unfiled instead (``exam_context = NULL``), so no later exam of
        this name inherits it.
        """
        for source_id in source_ids:
            in_use = self.fetchone(
                "SELECT 1 WHERE EXISTS (SELECT 1 FROM review_sessions"
                " WHERE question_source_id = ?)"
                " OR EXISTS (SELECT 1 FROM session_templates"
                " WHERE question_source_id = ?)"
                " OR EXISTS (SELECT 1 FROM planned_sessions"
                " WHERE question_source_id = ?)",
                (source_id, source_id, source_id))
            if in_use:
                self.execute(
                    "UPDATE question_sources SET exam_context = NULL WHERE id = ?",
                    (source_id,))
            else:
                self.execute("DELETE FROM question_sources WHERE id = ?",
                             (source_id,))

    def get_exam_analytics_config(self, exam_context_id: int) -> dict:
        """
        Get analytics config for an exam, merging with defaults for any missing keys.

        Args:
            exam_context_id: ID of the exam context

        Returns:
            Config dict with default_dimension_id and chart_visibility
        """
        self._ensure_phase4_schema()

        row = self.fetchone(
            "SELECT analytics_config FROM exam_contexts WHERE id = ?",
            (exam_context_id,)
        )

        if not row:
            from ..exceptions import ExamContextError
            raise ExamContextError(f"Exam context {exam_context_id} not found")

        config = {}
        if row['analytics_config']:
            try:
                config = json.loads(row['analytics_config'])
            except (json.JSONDecodeError, TypeError):
                config = {}

        # Merge with defaults
        defaults = json.loads(json.dumps(self.DEFAULT_ANALYTICS_CONFIG))
        merged = {**defaults, **config}
        # Deep-merge chart_visibility
        default_vis = defaults.get('chart_visibility', {})
        config_vis = config.get('chart_visibility', {})
        merged['chart_visibility'] = {**default_vis, **config_vis}
        # Deep-merge chart_sizes
        default_sizes = defaults.get('chart_sizes', {})
        config_sizes = config.get('chart_sizes', {})
        merged['chart_sizes'] = {**default_sizes, **config_sizes}

        return merged

    # ====================================================================
    # Stage 4 — Exam Length Triple
    # See HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md §3.2 and
    # WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md "Stage 4 — Exam Length
    # Triple". Migration ``m007_exam_length_triple`` adds the columns;
    # validation invariants are enforced here, not in a SQLite CHECK,
    # because SQLite's single-column CHECK doesn't surface a clean
    # error message for cross-column rules.
    # ====================================================================

    def update_exam_length(
        self,
        exam_context_id: int,
        kind: str,
        min: Optional[int],
        max: Optional[int],
        typical: Optional[int],
        note: Optional[str] = None,
    ) -> 'ExamContextConfig':
        """Update the exam-length triple for an exam context.

        Validates the kind/value invariants from ``HIERARCHICAL_WEIGHT_
        ALLOCATION_REWORK.md`` §3.2 before writing:

        - ``kind='fixed'``  ⇒ ``min == max == typical`` and all three populated
        - ``kind='range'``  ⇒ ``min <= typical <= max``  and all three populated
        - ``kind='unknown'``⇒ all three NULL (note may be retained or cleared)

        Args:
            exam_context_id: Target exam context ID.
            kind: One of ``'fixed' | 'range' | 'unknown'``.
            min: Lower bound integer (inclusive). Required for fixed/range.
            max: Upper bound integer (inclusive). Required for fixed/range.
            typical: Planning baseline integer. Required for fixed/range.
            note: Optional free-form copy (e.g. ``"+13 CCS cases"``).

        Returns:
            The refreshed :class:`ExamContextConfig` after the write.

        Raises:
            BaseDatabaseError: Validation failure or unknown exam context.
        """
        from ..models import ExamContextConfig

        valid_kinds = ('fixed', 'range', 'unknown')
        if kind not in valid_kinds:
            raise BaseDatabaseError(
                f"Invalid length_kind {kind!r}; must be one of {valid_kinds}"
            )

        if kind == 'unknown':
            if min is not None or max is not None or typical is not None:
                raise BaseDatabaseError(
                    "length_kind='unknown' requires length_min, length_max, "
                    "and length_typical to all be NULL"
                )
            stored_min = stored_max = stored_typical = None
        elif kind == 'fixed':
            if min is None or max is None or typical is None:
                raise BaseDatabaseError(
                    "length_kind='fixed' requires length_min, length_max, "
                    "and length_typical to all be populated"
                )
            if not (min == max == typical):
                raise BaseDatabaseError(
                    f"length_kind='fixed' requires min == max == typical "
                    f"(got min={min}, max={max}, typical={typical})"
                )
            stored_min, stored_max, stored_typical = int(min), int(max), int(typical)
        else:  # 'range'
            if min is None or max is None or typical is None:
                raise BaseDatabaseError(
                    "length_kind='range' requires length_min, length_max, "
                    "and length_typical to all be populated"
                )
            if not (min <= typical <= max):
                raise BaseDatabaseError(
                    f"length_kind='range' requires min <= typical <= max "
                    f"(got min={min}, typical={typical}, max={max})"
                )
            if min > max:
                raise BaseDatabaseError(
                    f"length_kind='range' requires min <= max "
                    f"(got min={min}, max={max})"
                )
            stored_min, stored_max, stored_typical = int(min), int(max), int(typical)

        # Existence check — surface a clean error rather than letting the
        # UPDATE silently affect zero rows.
        existing = self.fetchone(
            "SELECT id FROM exam_contexts WHERE id = ?",
            (exam_context_id,),
        )
        if not existing:
            raise BaseDatabaseError(
                f"Exam context {exam_context_id} not found"
            )

        with self.transaction():
            self.execute(
                """
                UPDATE exam_contexts
                SET length_kind = ?,
                    length_min = ?,
                    length_max = ?,
                    length_typical = ?,
                    length_note = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (kind, stored_min, stored_max, stored_typical, note, exam_context_id),
            )

        return self.get_exam_context_config(exam_context_id)

    def save_exam_edit(
        self,
        exam_context_id: int,
        settings: Dict[str, Any],
        length: Optional[Dict[str, Any]] = None,
        dimensions: Optional[List[Dict[str, Any]]] = None,
        existing_subjects: Optional[Dict[str, Any]] = None,
        first_axis: bool = False,
    ) -> Dict[str, Any]:
        """Save the exam wizard's edit mode as ONE transaction (#874).

        The wizard used to save in three independent calls: the settings,
        then the length, then a dimension sync of one call per axis. Only the
        first could fail the save. The others caught their own errors, logged
        them to the console and carried on, so the student was told
        "updated successfully" over a length or an axis that had not been
        saved (#240's *reads-like-success*). Now every part is written inside
        one ``self.transaction()``, so the edit is saved whole or not at all.
        A failure raises ``ValidationError`` with a sentence that names the
        part and says nothing was saved.

        Args:
            settings: keyword arguments for :meth:`update_exam_context_settings`.
            length: ``{kind, min, max, typical, note}`` for
                :meth:`update_exam_length`, or None to leave it alone.
            dimensions: the axes the exam should have, in their final order:
                ``{id (None for a new axis), name, description, is_required,
                allow_multiple}``. Existing active axes that are not listed
                are archived through :meth:`archive_dimension`, #210's whole
                cascade. None leaves the axes alone. ``[]`` archives every
                axis and every subject tree in it, which is why the wizard
                never sends ``[]`` for a Simple exam (#900).
            existing_subjects: the student's answer to the first-axis prompt
                (#605), or None when no question was asked.
                ``{"action": "aside"}`` changes no subject;
                ``{"action": "move", "assignments": [{"subject_id", "axis"}]}``
                moves the exam's top-level subjects outside every axis, with
                their subtrees, into the new axes, where ``axis`` is an index
                into ``dimensions`` in final order. An unlisted subject takes
                the first axis. The move runs in this transaction, so a refused
                move saves nothing, the new axes included.
            first_axis: True when the page believes the exam had no axis when
                it was opened. It is implied by ``existing_subjects``. Either
                one refuses the save if the exam has an active axis now: the
                page's list of axes would otherwise archive an axis it never
                saw, and its question would be about the wrong exam state.

        Returns:
            ``{"exam": ExamContextConfig, "dimension_ids": [...],
            "moved_existing": {...} | None}``: the axes' ids in their final
            order, new ones included, and ``{action, moved, by_axis}`` when the
            first-axis prompt was answered.
        """
        from ..exceptions import ValidationError

        def part(label: str, write):
            try:
                return write()
            except ValidationError as e:
                raise ValidationError(
                    f"Nothing was saved. {label} could not be saved: {e}") from e
            except Exception as e:  # sqlite3 / DatabaseIntegrityError / BaseDatabaseError
                raise ValidationError(
                    f"Nothing was saved. {label} could not be saved: {e}") from e

        action = None
        if existing_subjects is not None:
            action = (existing_subjects or {}).get("action") \
                if isinstance(existing_subjects, dict) else None
            if action not in ("aside", "move"):
                raise ValidationError(
                    "Nothing was saved. The choice about your existing subjects"
                    " could not be read.")
            if not dimensions:
                raise ValidationError(
                    "Nothing was saved. Existing subjects can only be moved"
                    " into an axis this save creates.")

        dimension_ids: List[int] = []
        moved_existing: Optional[Dict[str, Any]] = None
        with self.transaction():
            if first_axis or existing_subjects is not None:
                held = self.fetchone(
                    "SELECT COUNT(*) AS n FROM exam_dimensions"
                    " WHERE exam_id = ? AND status = 'active'",
                    (exam_context_id,))
                if held and held["n"]:
                    raise ValidationError(
                        "Nothing was saved. This exam gained an axis since this"
                        " was opened. Reload.")
            part("The exam's details",
                 lambda: self.update_exam_context_settings(exam_context_id, **settings))
            if length is not None:
                part("The exam's length", lambda: self.update_exam_length(
                    exam_context_id, length.get("kind") or "unknown",
                    length.get("min"), length.get("max"), length.get("typical"),
                    length.get("note")))
            if dimensions is not None:
                dimension_ids = self._sync_exam_dimensions(
                    exam_context_id, dimensions, part)
            if action == "aside":
                moved_existing = {"action": "aside", "moved": 0, "by_axis": []}
            elif action == "move":
                resolved = []
                for item in existing_subjects.get("assignments") or []:
                    axis = item.get("axis") if isinstance(item, dict) else None
                    if isinstance(axis, bool) or not isinstance(axis, int) \
                            or not 0 <= axis < len(dimension_ids):
                        raise ValidationError(
                            "Nothing was saved. A subject was assigned to an"
                            " axis that is not in this exam.")
                    resolved.append({"subject_id": item.get("subject_id"),
                                     "axis_id": dimension_ids[axis]})
                moved_existing = {"action": "move",
                                  **self._move_existing_into_new_axes(
                                      exam_context_id, resolved, dimension_ids[0])}

        return {"exam": self.get_exam_context_config(exam_context_id),
                "dimension_ids": dimension_ids,
                "moved_existing": moved_existing}

    def _sync_exam_dimensions(self, exam_id: int, wanted: List[Dict[str, Any]],
                              part) -> List[int]:
        """Make the exam's active axes match ``wanted``, in an order that cannot collide.

        ``exam_dimensions`` has ``UNIQUE(exam_id, name)`` and
        ``UNIQUE(exam_id, display_order)``, and SQLite checks both per row as
        each statement runs (#211). The wizard's old sync updated and created
        axes before archiving the removed ones, and wrote ``display_order``
        row by row. So a new axis created in a slot that a removed axis still
        held collided, and so did a swap of two names. Here:

        1. archive the axes no longer wanted; archiving parks their order and
           name (#244), which frees both;
        2. park every name that is about to change (#241's rule: parking is
           unconditional, because the case analysis is what gets it wrong);
        3. create the new axes at orders past every one in use;
        4. write each kept axis's final name and flags;
        5. assign the final order 1..N through :meth:`reorder_dimensions`.
        """
        current = {d["id"]: d for d in self.get_exam_dimensions(exam_id)}
        keep = {int(w["id"]) for w in wanted if w.get("id")}
        missing = keep - set(current)
        if missing:
            from ..exceptions import ValidationError
            raise ValidationError(
                "Nothing was saved. A dimension being edited no longer exists"
                " (it may have been archived elsewhere). Reload the wizard.")

        for dim_id, dim in current.items():
            if dim_id not in keep:
                part(f'Archiving the dimension "{dim["name"]}"',
                     lambda dim_id=dim_id: self.archive_dimension(dim_id))

        for w in wanted:
            dim_id = w.get("id")
            if dim_id and current[int(dim_id)]["name"] != w["name"]:
                self.execute("UPDATE exam_dimensions SET name = ? WHERE id = ?",
                             (f"{current[int(dim_id)]['name']} (renaming #{dim_id})",
                              int(dim_id)))

        top = self.fetchone(
            "SELECT COALESCE(MAX(display_order), 0) AS m FROM exam_dimensions"
            " WHERE exam_id = ?  -- includes-archived (#874): archived rows"
            " keep parked orders, and a new axis must clear every slot in use",
            (exam_id,))["m"]
        ids: List[int] = []
        for w in wanted:
            dim_id = w.get("id")
            if dim_id:
                dim_id = int(dim_id)
                part(f'The dimension "{w["name"]}"',
                     lambda w=w, dim_id=dim_id: self.update_dimension(
                         dim_id, name=w["name"],
                         description=w.get("description") or None,
                         is_required=bool(w.get("is_required", True)),
                         allow_multiple=bool(w.get("allow_multiple", False))))
            else:
                top += 1
                dim_id = part(f'The new dimension "{w["name"]}"',
                              lambda w=w, order=top: self.create_dimension(
                                  exam_id=exam_id, name=w["name"],
                                  display_order=order,
                                  is_required=bool(w.get("is_required", True)),
                                  allow_multiple=bool(w.get("allow_multiple", False)),
                                  description=w.get("description") or None))
            ids.append(dim_id)

        if ids:
            part("The dimensions' order",
                 lambda: self.reorder_dimensions(exam_id, ids))
        return ids

    def get_exam_length(self, exam_context_id: int) -> Dict[str, Any]:
        """Return the exam-length triple for an exam context.

        Defensively coerces a NULL ``length_kind`` (unmigrated row, or
        a row that somehow escaped the migration default) to
        ``'unknown'`` so callers can pattern-match on the kind without
        first checking for None.

        Args:
            exam_context_id: Target exam context ID.

        Returns:
            ``{kind, min, max, typical, note}`` — values are integers
            (or None) for the numeric fields and strings (or None) for
            ``kind`` and ``note``.

        Raises:
            BaseDatabaseError: Unknown exam context.
        """
        row = self.fetchone(
            """
            SELECT length_kind, length_min, length_max, length_typical, length_note
            FROM exam_contexts
            WHERE id = ?
            """,
            (exam_context_id,),
        )
        if not row:
            raise BaseDatabaseError(
                f"Exam context {exam_context_id} not found"
            )

        kind = row.get('length_kind') or 'unknown'
        return {
            'kind': kind,
            'min': row.get('length_min'),
            'max': row.get('length_max'),
            'typical': row.get('length_typical'),
            'note': row.get('length_note'),
        }

    def is_adaptive_exam(self, exam_context_id: int) -> bool:
        """Return ``True`` iff the exam context is a variable-length CAT.

        Stage 8 of
        ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``.
        ``length_kind='range'`` is the canonical CAT signal: NCLEX-RN
        and similar adaptive exams have a min/max/typical triple but
        no fixed item count. Callers use this to switch the Hamilton
        allocator into float mode (skipping integer rounding so the UI
        doesn't lie about a precision the exam doesn't have).

        Treats ``length_kind`` missing/NULL/``'unknown'`` as
        non-adaptive — same defensive coercion as
        :meth:`get_exam_length`.

        Args:
            exam_context_id: Target exam context ID.

        Returns:
            ``True`` only when ``length_kind == 'range'``; ``False``
            for ``'fixed'``, ``'unknown'``, NULL, or a missing row
            (defensive — a non-existent context can't be adaptive).
        """
        row = self.fetchone(
            "SELECT length_kind FROM exam_contexts WHERE id = ?",
            (exam_context_id,),
        )
        if not row:
            return False
        kind = row.get('length_kind') or 'unknown'
        return kind == 'range'

    def seed_known_exam_lengths(self) -> int:
        """Idempotently fill in known exam lengths for the named exams.

        Walks ``exam_contexts`` for the current user, matches each row's
        ``exam_name`` against :data:`KNOWN_EXAM_LENGTHS` (case-insensitive),
        and writes the canonical length data **only when** the row's
        ``length_kind`` is still ``'unknown'``. Existing user edits are
        never clobbered.

        Returns:
            Count of rows updated. Useful for tests and migration logging.
        """
        rows = self.fetchall(
            "SELECT id, exam_name, length_kind FROM exam_contexts "
            "WHERE user_id = ?",
            (self.user_id,),
        )

        updated = 0
        for row in rows:
            existing_kind = row.get('length_kind') or 'unknown'
            if existing_kind != 'unknown':
                # Respect user-set or previously-seeded data.
                continue
            name_key = (row.get('exam_name') or '').strip().lower()
            spec = KNOWN_EXAM_LENGTHS.get(name_key)
            if not spec:
                continue
            try:
                self.update_exam_length(
                    exam_context_id=row['id'],
                    kind=spec['kind'],
                    min=spec.get('min'),
                    max=spec.get('max'),
                    typical=spec.get('typical'),
                    note=spec.get('note'),
                )
                updated += 1
            except BaseDatabaseError:
                # Defensive — a single bad row should not abort the seed.
                if self.error_logger:
                    self.error_logger.warning(
                        f"seed_known_exam_lengths: skipped row {row['id']!r} "
                        f"({row.get('exam_name')!r}) due to validation failure",
                        category=ErrorCategory.DATABASE,
                    )
        return updated

    @staticmethod
    def get_known_exam_length(exam_name: str) -> Optional[Dict[str, Any]]:
        """Look up the canonical length data for a named exam.

        Static helper used by the bridge so the wizard can pre-fill the
        length step when the user types/selects a recognized exam name.
        Returns ``None`` for unknown names. Case-insensitive lookup.
        """
        if not exam_name:
            return None
        return KNOWN_EXAM_LENGTHS.get(exam_name.strip().lower())

    def update_exam_analytics_config(self, exam_context_id: int, config: dict) -> dict:
        """
        Update analytics config for an exam.

        Args:
            exam_context_id: ID of the exam context
            config: Config dict (partial or full)

        Returns:
            Updated merged config dict
        """
        self._ensure_phase4_schema()

        # Verify exam exists
        row = self.fetchone(
            "SELECT id FROM exam_contexts WHERE id = ?",
            (exam_context_id,)
        )
        if not row:
            from ..exceptions import ExamContextError
            raise ExamContextError(f"Exam context {exam_context_id} not found")

        # Get current config to merge with
        current = self.get_exam_analytics_config(exam_context_id)

        # Merge incoming config
        if 'default_dimension_id' in config:
            current['default_dimension_id'] = config['default_dimension_id']
        if 'chart_visibility' in config:
            current['chart_visibility'] = {**current['chart_visibility'], **config['chart_visibility']}
        if 'chart_sizes' in config:
            current['chart_sizes'] = {**current.get('chart_sizes', {}), **config['chart_sizes']}
        if config.get('min_mistakes_to_flag') is not None:
            value = config['min_mistakes_to_flag']
            low, high = self.MIN_MISTAKES_TO_FLAG_RANGE
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(
                    f'The minimum number of mistakes must be a whole number from {low} to {high}.')
            current['min_mistakes_to_flag'] = value

        config_json = json.dumps(current)

        self.execute(
            "UPDATE exam_contexts SET analytics_config = ? WHERE id = ?",
            (config_json, exam_context_id)
        )
        self.conn.commit()

        return current
