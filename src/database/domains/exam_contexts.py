"""WIMI Exam Contexts database operations."""

import json
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


class ExamContextMixin:
    """Mixin for exam context operations. Composed into UserDatabase."""

    # Default analytics config applied when column is NULL
    DEFAULT_ANALYTICS_CONFIG = {
        "default_dimension_id": None,
        "chart_visibility": {
            "subject_sunburst": True,
            "tag_chart": True,
            "activity_chart": True,
            "activity_heatmap": True,
            "streak_stats": True,
            "weekly_goal": True,
            "difficulty_distribution": True,
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
        from ..exceptions import ExamContextAlreadyExistsError, ExamContextError

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
        is_active: Optional[bool] = None
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

        Returns:
            Updated ExamContextConfig object
        """
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

        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        if is_active is not None:
            updates.append("is_active = ?")
            params.append(is_active)

        if not updates:
            return self.get_exam_context_config(exam_context_id)

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(exam_context_id)

        with self.transaction():
            self.execute(f"""
                UPDATE exam_contexts
                SET {', '.join(updates)}
                WHERE id = ?
            """, tuple(params))

        return self.get_exam_context_config(exam_context_id)

    def hard_delete_exam_context(self, exam_context_id: int) -> List[int]:
        """
        Permanently delete an exam context and all associated data.
        The exam must already be suspended (is_active = FALSE).

        CASCADE constraints handle deletion of:
        - review_sessions (which CASCADE to question_entries, entry_media, etc.)
        - hierarchy_level_definitions
        - exam_dimensions (which CASCADE to question_hierarchy_tags, entry_subject_mappings)

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
            # Delete the exam context row - CASCADE handles related tables
            self.execute(
                "DELETE FROM exam_contexts WHERE id = ?",
                (exam_context_id,)
            )

            if self.error_logger:
                self.error_logger.info(
                    f"Permanently deleted exam context {exam_context_id} "
                    f"({len(deleted_entry_ids)} entries affected)",
                    category=ErrorCategory.DATABASE
                )

        return deleted_entry_ids

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

        config_json = json.dumps(current)

        self.execute(
            "UPDATE exam_contexts SET analytics_config = ? WHERE id = ?",
            (config_json, exam_context_id)
        )
        self.conn.commit()

        return current
