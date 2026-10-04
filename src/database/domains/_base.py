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
        """The canonical breadcrumb path as a display string.

        Thin wrapper over :meth:`_build_subject_path_info`, which owns the
        walk. **There is deliberately only one walk** — #301 existed because
        this helper had its own, and two independent traversals of the same
        table drift apart silently (that is the whole shape of the bug).
        Anything that needs to know *what the walk removed* must call
        ``_build_subject_path_info``; re-walking unfiltered at the call site
        to recover the archived names would reintroduce the disagreement.
        """
        return self._build_subject_path_info(node_id)['path']

    def _build_subject_path_info(self, node_id: int) -> Dict[str, Any]:
        """The canonical breadcrumb path, plus what was left out of it.

        Returns ``{'path', 'parts', 'omitted_ancestors', 'shortened'}``.

        Polyhierarchy migration: walks UPWARD via ``subject_edges``
        following only ``is_primary=TRUE`` edges — this yields the
        canonical breadcrumb path. Non-primary alternate paths are
        available via :meth:`EdgesMixin.get_paths_to_root`. Falls back
        to ``subject_nodes.parent_id`` if the ``subject_edges`` table
        doesn't exist (very old DBs predating m004).

        **An archived ancestor is not named, and the walk says so (#301,
        owner's decision 2026-10-03).** Both steps filter
        ``status = 'active'``, so this agrees with the #262-fixed
        ``get_paths_to_root`` / ``_primary_path_to_root`` and with
        ``RelationsMixin._ancestor_sets`` — *an edge from an archived node
        is not a live context*. Before that it had no status predicate in
        either step, so an active ``Child`` under an archived ``Parent``
        rendered ``'Parent > Child'`` while ``get_paths_to_root`` returned
        ``[[Child]]``: one of them named a subject the tree no longer shows,
        and this one is the string a student reads.

        The owner's decision was **neither** of the options #301 offered:
        filter *and* explain. The objection to filtering alone was that a
        shortened path "can look wrong without explaining why", so
        ``omitted_ancestors`` carries the archived names up to the UI for a
        hover tooltip. One rule for the path, a second channel for the
        caveat — rather than putting archived names back into the primary
        reading line, which is what #15's soft delete was getting away from.

        ``omitted_ancestors`` is **empty unless the walk was actually cut
        short**, because an affordance that always appears means nothing. It
        names the archived parent the walk refused to step onto — the
        *reason* the path is short — and does not continue above it to
        reconstruct the whole historical chain. Reconstruction is the
        Archived subjects panel's job (#37); this is an explanation.

        ``node_id`` itself is emitted whatever its status, because the
        caller named it — the same rule ``get_paths_to_root`` states, and
        without it the deep dive of an archived subject would render an
        empty breadcrumb.

        **Not delegated to ``_primary_path_to_root``**, close as the two
        now are: that one has no legacy ``subject_nodes.parent_id``
        fallback, and this is the one helper that still handles pre-m004
        data and fixtures that seed ``parent_id`` without an edge row
        (``tests/database/test_descendant_walk_sources.py`` pins it).

        SQLite is authoritative here — see the note on
        :meth:`_get_descendant_node_ids` for why the former
        "graph-primary (P2.5)" shortcut was removed. Same defect, same
        cause: the graph's ``HAS_CHILD`` edges and its cached
        ``full_path`` property are both derived from
        ``subject_nodes.parent_id`` by ``GraphMixin._etl_subjects``, a
        column the polyhierarchy migration deprecated. A node whose
        primary edge no longer matches its legacy ``parent_id`` (or whose
        ``parent_id`` is NULL because it was only ever attached via
        ``subject_edges``) got a stale path, or just its own bare name.
        """
        # Walk upward via primary edges first; fall back to
        # subject_nodes.parent_id when no primary edge exists (legacy
        # nodes / tests that seed parent_id but not subject_edges).
        parts: List[str] = []
        omitted: List[str] = []
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
            has_primary_edge = False
            if edges_available:
                # The parent-status JOIN is the #301 fix, and it has to be
                # in the JOIN rather than applied afterwards: a NULL row
                # here means "no live parent", which is the same answer as
                # "no parent at all" and makes this node a root -- the
                # predicate #260 gave the root finders.
                parent_row = self.fetchone(
                    "SELECT se.parent_id AS parent_id FROM subject_edges se "
                    "JOIN subject_nodes p "
                    "  ON p.id = se.parent_id AND p.status = 'active' "
                    "WHERE se.child_id = ? AND se.is_primary = TRUE LIMIT 1",
                    (current_id,),
                )
                if parent_row is not None:
                    next_id = parent_row['parent_id']
                else:
                    # Does a primary edge exist AT ALL? Status-blind on
                    # purpose, and it decides precedence rather than
                    # membership -- see the fallback below.
                    has_primary_edge = self.fetchone(
                        "SELECT 1 FROM subject_edges "
                        "WHERE child_id = ? AND is_primary = TRUE LIMIT 1",
                        (current_id,),
                    ) is not None
            # Fall back to subject_nodes.parent_id ONLY where the junction
            # table has nothing to say (legacy / partially-migrated data).
            #
            # `not has_primary_edge` is the load-bearing half. Without it,
            # a node whose primary edge points at an ARCHIVED parent would
            # fall through to the legacy column -- and that column is a
            # mirror that is allowed to diverge (`add_parent` writes edges
            # and not `parent_id`; this method's own docstring describes a
            # node "whose primary edge no longer matches its legacy
            # parent_id"). So the walk would cross from the canonical
            # source to a stale one mid-path and report a chain that no
            # edge supports, which is the defect class
            # `_get_descendant_node_ids` is wholly about. `subject_edges`
            # having an archived answer IS an answer.
            #
            # The legacy target is itself status-filtered: #301 called that
            # a second decision; it is the same decision reached through
            # pre-m004 data, and leaving it would make the guarantee hold
            # only for databases new enough to carry `subject_edges`.
            if (next_id is None and not has_primary_edge
                    and row['parent_id'] is not None):
                legacy_row = self.fetchone(
                    "SELECT id FROM subject_nodes "
                    "WHERE id = ? AND status = 'active'",
                    (row['parent_id'],),
                )
                if legacy_row is not None:
                    next_id = legacy_row['id']

            if next_id is None:
                # Nothing live above this node. Name the archived parent the
                # walk declined to step onto, if there is one -- that is the
                # tooltip's whole content, and it is read with no status
                # filter on purpose.
                omitted = self._archived_ancestor_names(current_id)
            current_id = next_id

            if len(parts) > 32:  # Safety check; deep DAGs allowed but bounded.
                break

        return {
            'path': ' > '.join(parts),
            'parts': parts,
            'omitted_ancestors': omitted,
            'shortened': bool(omitted),
        }

    def _archived_ancestor_names(self, node_id: int) -> List[str]:
        """Names of the archived parents that cut ``node_id``'s path short.

        The tooltip's content (#301). Call it on the **topmost** node of a
        rendered path: a non-empty answer means that path really was
        shortened, an empty one means the node is a genuine root and the
        path is complete. Any path built from a status-filtered upward walk
        can be explained this way, which is why
        ``get_subject_deep_dive`` uses it for ``path_via_parent`` (built
        from the #262-filtered ``get_paths_to_root``) as well as for
        ``full_path``.

        Deliberately status-blind: it exists to report what the status
        filter removed, so filtering it would make it return nothing,
        always. It names the immediate archived parent — the *reason* the
        path stops — and does not climb further to reconstruct the whole
        historical chain; that is the Archived subjects panel's job (#37).
        """
        node = self.fetchone(
            "SELECT parent_id FROM subject_nodes WHERE id = ?", (node_id,))
        if node is None:
            return []
        legacy_parent_id = node['parent_id']
        edges_available = self.fetchone(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='subject_edges'"
        ) is not None

        names: List[str] = []
        if edges_available:
            rows = self.fetchall(
                # includes-archived (#301): this read is the tooltip's
                # content -- it reports exactly the ancestors the filtered
                # walk above refused to step onto, so filtering it would
                # make it return nothing, always.
                "SELECT p.name AS name FROM subject_edges se "
                "JOIN subject_nodes p ON p.id = se.parent_id "
                "WHERE se.child_id = ? AND se.is_primary = TRUE "
                "  AND p.status != 'active' "
                "ORDER BY p.name",
                (node_id,),
            )
            names = [row['name'] for row in rows]
        if not names and legacy_parent_id is not None:
            row = self.fetchone(
                "SELECT name FROM subject_nodes "
                "WHERE id = ? AND status != 'active'",
                (legacy_parent_id,),
            )
            if row is not None:
                names = [row['name']]
        return names

    # ------------------------------------------------------------------
    # Descendant helpers
    # ------------------------------------------------------------------

    def _get_descendant_node_ids(self, parent_id: int) -> List[int]:
        """Get all descendant node IDs recursively (excluding ``parent_id`` itself).

        Polyhierarchy migration: descends via the ``subject_edges``
        junction table so a node reachable through multiple parents is
        still only included once (``UNION`` dedup in the recursive CTE).
        Falls back to ``subject_nodes.parent_id`` if ``subject_edges``
        doesn't exist (legacy DBs predating m004).

        **SQLite is authoritative. Do not re-add a graph-first read
        here.** This used to consult LadybugDB first (the "P2.5
        graph-primary" optimisation) and return its answer whenever the
        parent node existed in the graph. The graph's ``HAS_CHILD``
        edges are built by ``GraphMixin._etl_subjects`` exclusively from
        ``subject_nodes.parent_id`` — the legacy single-parent column the
        polyhierarchy migration deprecated — and ``EdgesMixin`` performs
        no graph dual-write at all. So a second parent added through
        ``add_parent``/``add_edge`` never reached the graph, and asking
        that parent for its descendants returned an **empty list**: the
        graph knew the node, so the shortcut fired, and the node simply
        had no outgoing ``HAS_CHILD``.

        That silently reverted polyhierarchy behaviour everywhere
        downstream, because callers derive query scope from this helper
        (e.g. ``get_entries_paginated``'s subject filter, whose SQL is
        correct but was being fed a wrong id set). Reading
        ``subject_edges`` directly is the only source of truth; the cost
        is one recursive CTE, which is not worth a wrong answer.
        Re-enabling the shortcut requires rebuilding the ETL on
        ``subject_edges`` *and* adding graph dual-writes to
        ``EdgesMixin`` first.

        Uses UNION (not UNION ALL) so an accidental data cycle does not
        produce infinite recursion.
        """
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

    def _primary_parent_scope_sql(
        self,
        scope_node_ids,
        alias: str = 'esm',
    ) -> tuple:
        """Predicate: does a mapping row roll up into ``scope_node_ids``?

        Implements ``POLYHIERARCHY_MIGRATION.md`` §5.4, which is a
        conditional and is easy to half-implement:

        * ``primary_parent_id IS NULL`` — the student never disambiguated
          this tag, so the entry rolls up through **every** ancestor
          reachable from the leaf. Match on the subject itself being in
          scope. This is the OMOP "honest non-additivity" behaviour of
          §5.3.
        * ``primary_parent_id`` set — the student said which parent they
          meant, so the entry rolls up through **only** that parent's
          ancestors. Match on the chosen parent being in scope, and
          ignore the subject entirely: the leaf is shared, the context is
          not.

        Implementing only the first branch is the bug this helper exists
        to prevent. It counts a disambiguated entry under parents the
        student explicitly excluded, and inflates totals in proportion to
        how many parents a subject has — worst on exactly the
        cross-cutting, high-yield topics.

        This is the **counting** predicate. A surface that retrieves
        entries rather than totalling them wants
        :meth:`_subject_filter_scope_sql`, which wraps this one — see
        that docstring, and "Counting vs finding" in CLAUDE.md.

        Args:
            scope_node_ids: the target subtree — typically a node plus
                its descendants, from ``_get_descendant_node_ids``.
            alias: table alias for ``entry_subject_mappings`` in the
                caller's query.

        Returns:
            ``(sql, params)``. ``sql`` is a parenthesised boolean
            expression safe to AND into a WHERE clause; ``params`` are
            the bind values in order. An empty ``scope_node_ids`` yields
            ``('(0)', [])`` — matches nothing, rather than an invalid
            ``IN ()``.
        """
        ids = list(scope_node_ids)
        if not ids:
            return '(0)', []
        placeholders = ','.join(['?'] * len(ids))
        sql = (
            f"(({alias}.primary_parent_id IS NULL"
            f"   AND {alias}.subject_node_id IN ({placeholders}))"
            f" OR ({alias}.primary_parent_id IS NOT NULL"
            f"   AND {alias}.primary_parent_id IN ({placeholders})))"
        )
        return sql, ids + ids

    def _subject_filter_scope_sql(
        self,
        direct_node_ids,
        scope_node_ids,
        alias: str = 'esm',
    ) -> tuple:
        """Predicate for a *finding* surface: "is this entry about S?"

        **Counting is primary-only; finding is all tags** (CLAUDE.md,
        settled on Forgejo #13). This is the finding half's scope rule,
        and it is deliberately more permissive than
        :meth:`_primary_parent_scope_sql`. Filtering by subject S means
        the union of:

        * entries tagged S **directly**, whatever parent context they
          carry — ``subject_node_id IN direct_node_ids``, unconditional;
        * entries that roll up into S's subtree under §5.4 — the
          conditional from :meth:`_primary_parent_scope_sql` over
          ``scope_node_ids``.

        The first clause is the fix for #13. A student tagged a question
        with shared leaf D, said "the Pregnancy one", and could then no
        longer find it by filtering for D: the §5.4 predicate asks
        whether the *chosen parent* is in scope, and filtering by the
        leaf alone means it is not. §5.4 governs rollup *through
        ancestors*; the leaf is not an ancestor, it is the subject the
        entry actually carries, so a parent context narrows which chain
        an entry rolls up through without making it stop being about D.

        **The two id sets are not interchangeable.** ``direct_node_ids``
        is what the user named; ``scope_node_ids`` is that plus its
        descendants. Widening the unconditional clause to the whole
        descendant set would return an entry on a shared leaf pinned to
        one parent under *every* parent of that leaf — the §5.4 defect
        this codebase already fixed once. Pinned by
        ``test_entry_filter_rolls_descendants_up_through_the_chosen_parent``.

        Do not use this for anything that totals mistakes. Top Subjects,
        both sunbursts and the weight quadrant stay on the strict §5.4
        predicate and on ``mapping_type = 'primary'``.

        Args:
            direct_node_ids: the subjects the caller actually named.
            scope_node_ids: the rollup scope — typically those nodes plus
                their descendants, from ``_get_descendant_node_ids``.
            alias: table alias for ``entry_subject_mappings`` in the
                caller's query.

        Returns:
            ``(sql, params)``, ``sql`` a parenthesised boolean expression
            safe to AND into a WHERE clause. Empty inputs degrade the way
            :meth:`_primary_parent_scope_sql` does — ``('(0)', [])``
            matches nothing rather than emitting an invalid ``IN ()``.
        """
        scope_sql, scope_params = self._primary_parent_scope_sql(
            scope_node_ids, alias=alias
        )
        direct = list(direct_node_ids)
        if not direct:
            return scope_sql, scope_params
        placeholders = ','.join(['?'] * len(direct))
        sql = (
            f"(({alias}.subject_node_id IN ({placeholders}))"
            f" OR {scope_sql})"
        )
        return sql, direct + scope_params

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
            Dict with id, name, path, and dimension info if available.

        ``path_omitted_ancestors`` is present **only when the path was
        actually shortened** by #301's status filter, because an affordance
        that always appears means nothing — a reader of the payload can treat
        the key's absence as "nothing to explain" rather than having to
        compare an empty list. This is the per-entry subject dict, so it is
        also the broadest payload carrying a path: the entry browser's subject
        chips and the entry detail breadcrumb both read it.
        """
        path_info = self._build_subject_path_info(subject.id)
        subject_dict = {
            'id': subject.id,
            'name': subject.name,
            'path': path_info['path']
        }
        if path_info['omitted_ancestors']:
            subject_dict['path_omitted_ancestors'] = \
                path_info['omitted_ancestors']

        # Try to get dimension info for this subject
        dim_info = self.fetchone("""
            SELECT sn.dimension_id, d.name as dimension_name
            FROM subject_nodes sn
            LEFT JOIN exam_dimensions d
                   ON sn.dimension_id = d.id AND d.status = 'active'
            WHERE sn.id = ?
        """, (subject.id,))

        if dim_info and dim_info['dimension_id']:
            subject_dict['dimension_id'] = dim_info['dimension_id']
            subject_dict['dimension_name'] = dim_info['dimension_name']

        return subject_dict
