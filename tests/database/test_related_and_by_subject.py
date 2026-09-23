"""Tests for ``EntriesMixin.get_related_subjects`` / ``get_entries_by_subject``.

Companion to ``test_primary_parent_context.py``. Covers the two defects
listed against ``src/database/domains/entries.py`` in
``docs/planning/ENTRY_COUNT_AUDIT.md``:

``get_related_subjects`` — **does not aggregate**. Its count is a direct
per-node count (``esm.subject_node_id = sn.id``, no descendant set, no
ancestor walk), so §5.4 of ``POLYHIERARCHY_MIGRATION.md`` is
inapplicable; what was wrong was that its sibling/aunt/child *discovery*
walked the legacy ``subject_nodes.parent_id`` column, that it counted
secondary "also tested" tags as mistakes, and that it never scoped to a
user or an exam despite taking ``exam_context_id``.

``get_entries_by_subject`` — **does aggregate** when ``include_children``
is set (``subject_id`` + ``_get_descendant_node_ids(subject_id)``), so
§5.4 applies and was absent. It also preferred a LadybugDB read whose
``HAS_CHILD`` edges come from the legacy column, which bypassed the SQL
entirely.

The DAG used by the §5.4 tests is the same diamond as the companion file::

           A
          / \\
         B   C
          \\ /
           D   (D has parents B and C, both rooted in A)
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def test_user(master_db):
    return master_db.create_user(
        username="related_user",
        display_name="Related Subjects User",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db, test_user):
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username,
    )
    yield db
    db.close()


# ----------------------------------------------------------------- helpers


def _make_node(user_db, name: str, legacy_parent_id=None) -> int:
    """Insert a subject node.

    ``legacy_parent_id`` defaults to NULL on purpose: the polyhierarchy
    tests need nodes whose *only* relationship lives in ``subject_edges``,
    which is precisely the shape the legacy ``parent_id`` discovery could
    not see.
    """
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, sort_order, status) "
        "VALUES (?, ?, ?, ?, 0, 'active')",
        ("USMLE", name, "Topic", legacy_parent_id),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _exam_context(user_db, name="USMLE") -> int:
    row = user_db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = ?", (name,)
    )
    if row is not None:
        return row['id']
    cursor = user_db.execute(
        "INSERT INTO exam_contexts (user_id, exam_name, exam_description) "
        "VALUES (?, ?, 'Test')",
        (user_db.user_id, name),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _make_session(user_db, exam_context_id: int, user_id=None) -> int:
    cursor = user_db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            user_db.user_id if user_id is None else user_id,
            "Test session",
            date.today().isoformat(),
            exam_context_id,
            1,
            1,
        ),
    )
    user_db.conn.commit()
    return cursor.lastrowid


_entry_order = {'n': 0}


def _log_entry(
    user_db,
    session_id,
    subject_node_id,
    primary_parent_id=None,
    mapping_type='primary',
):
    _entry_order['n'] += 1
    cursor = user_db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, ?, ?)",
        (session_id, _entry_order['n'], "A", "B"),
    )
    entry_id = cursor.lastrowid
    user_db.execute(
        "INSERT INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type, primary_parent_id) "
        "VALUES (?, ?, ?, ?)",
        (entry_id, subject_node_id, mapping_type, primary_parent_id),
    )
    user_db.conn.commit()
    return entry_id


def _build_diamond(user_db):
    """Build ``A → {B, C} → D`` purely in ``subject_edges``."""
    a = _make_node(user_db, "A")
    b = _make_node(user_db, "B")
    c = _make_node(user_db, "C")
    d = _make_node(user_db, "D")
    user_db.add_edge(a, b, is_primary=True)
    user_db.add_edge(a, c, is_primary=True)
    user_db.add_edge(b, d, is_primary=True)
    user_db.add_edge(c, d, is_primary=False)
    return a, b, c, d


def _by_name(rows):
    return {row['name']: row for row in rows}


# =================================================== get_related_subjects
# All of these assert on a NON-aggregating function: the counts are direct
# per-node counts, so no §5.4 expectation appears below. What is under test
# is discovery (which relatives are found) and scoping (which entries are
# counted).


class TestRelatedSubjectsDiscovery:

    def test_finds_sibling_attached_only_by_edge(self, user_db):
        """A sibling whose relationship exists only in ``subject_edges``.

        Pre-fix, discovery read ``subject_nodes.parent_id``, which is NULL
        for every node here, so the panel came back empty.
        """
        exam_id = _exam_context(user_db)
        parent = _make_node(user_db, "Parent")
        me = _make_node(user_db, "Me")
        edge_sibling = _make_node(user_db, "EdgeSibling")
        user_db.add_edge(parent, me, is_primary=True)
        user_db.add_edge(parent, edge_sibling, is_primary=True)

        related = user_db.get_related_subjects(me, exam_id, limit=4)

        names = {row['name'] for row in related}
        assert names == {"EdgeSibling"}, (
            "edge-only sibling must be discovered; legacy parent_id is NULL here"
        )

    def test_finds_siblings_under_every_parent(self, user_db):
        """A shared subject's relatives come from all of its parents.

        Legacy ``parent_id`` can only name one, so a second parent's other
        children were invisible even when the legacy column was populated.
        """
        exam_id = _exam_context(user_db)
        p1 = _make_node(user_db, "P1")
        p2 = _make_node(user_db, "P2")
        shared = _make_node(user_db, "Shared", legacy_parent_id=p1)
        under_p1 = _make_node(user_db, "UnderP1", legacy_parent_id=p1)
        under_p2 = _make_node(user_db, "UnderP2", legacy_parent_id=p2)
        user_db.add_edge(p1, shared, is_primary=True)
        user_db.add_edge(p2, shared, is_primary=False)
        user_db.add_edge(p1, under_p1, is_primary=True)
        user_db.add_edge(p2, under_p2, is_primary=True)

        related = user_db.get_related_subjects(shared, exam_id, limit=4)

        names = {row['name'] for row in related}
        assert "UnderP2" in names, "second parent's children must be discovered"
        assert "UnderP1" in names

    def test_finds_edge_only_children_and_aunts(self, user_db):
        """Steps 2 and 3 of discovery also read edges, not ``parent_id``."""
        exam_id = _exam_context(user_db)
        grandparent = _make_node(user_db, "Grandparent")
        parent = _make_node(user_db, "Parent")
        aunt = _make_node(user_db, "Aunt")
        me = _make_node(user_db, "Me")
        child = _make_node(user_db, "Child")
        user_db.add_edge(grandparent, parent, is_primary=True)
        user_db.add_edge(grandparent, aunt, is_primary=True)
        user_db.add_edge(parent, me, is_primary=True)
        user_db.add_edge(me, child, is_primary=True)

        related = user_db.get_related_subjects(me, exam_id, limit=10)

        names = {row['name'] for row in related}
        assert "Aunt" in names, "aunt/uncle discovery must walk subject_edges"
        assert "Child" in names, "child discovery must walk subject_edges"
        assert "Me" not in names
        assert "Parent" not in names

    def test_legacy_parent_id_fallback_still_works(self, user_db):
        """A DB with no edges at all (pre-m004 shape) keeps working."""
        exam_id = _exam_context(user_db)
        parent = _make_node(user_db, "LegacyParent")
        me = _make_node(user_db, "LegacyMe", legacy_parent_id=parent)
        _make_node(user_db, "LegacySibling", legacy_parent_id=parent)

        related = user_db.get_related_subjects(me, exam_id, limit=4)

        assert {row['name'] for row in related} == {"LegacySibling"}


class TestRelatedSubjectsCounts:

    def test_secondary_tag_is_not_counted_as_a_mistake(self, user_db):
        """One entry per node, and only where the tag is primary.

        ``entry_count`` ranks "what to review next", so it must mean
        mistakes. Pre-fix there was no ``mapping_type`` filter and an "also
        tested" tag inflated the count.
        """
        exam_id = _exam_context(user_db)
        session = _make_session(user_db, exam_id)
        parent = _make_node(user_db, "Parent")
        me = _make_node(user_db, "Me")
        sibling = _make_node(user_db, "Sibling")
        user_db.add_edge(parent, me, is_primary=True)
        user_db.add_edge(parent, sibling, is_primary=True)

        _log_entry(user_db, session, sibling, mapping_type='primary')
        _log_entry(user_db, session, sibling, mapping_type='secondary')

        related = _by_name(user_db.get_related_subjects(me, exam_id, limit=4))

        assert related["Sibling"]['entry_count'] == 1, (
            "only the primary tag is a mistake on this node"
        )

    def test_one_node_cannot_hold_both_mapping_types_for_one_entry(self, user_db):
        """Pins why ``COUNT(esm.id)`` could not double-count that way.

        The audit listed "an entry tagged both primary and secondary on the
        same node counts twice" as a live defect. It is not reachable:
        ``idx_unique_entry_subject`` is UNIQUE on
        ``(question_entry_id, subject_node_id)`` and is mapping_type
        agnostic. ``COUNT(DISTINCT question_entry_id)`` is therefore an
        intent fix, not a behaviour fix — this test exists so that if the
        index is ever dropped, the assumption fails loudly here rather than
        silently inflating a count.
        """
        exam_id = _exam_context(user_db)
        session = _make_session(user_db, exam_id)
        node = _make_node(user_db, "Solo")
        entry_id = _log_entry(user_db, session, node, mapping_type='primary')

        with pytest.raises(Exception):
            user_db.execute(
                "INSERT INTO entry_subject_mappings "
                "(question_entry_id, subject_node_id, mapping_type) "
                "VALUES (?, ?, 'secondary')",
                (entry_id, node),
            )
        user_db.conn.rollback()

    def test_counts_are_scoped_to_this_user_and_exam(self, user_db, master_db):
        """``exam_context_id`` reached only a config lookup, never the query."""
        exam_id = _exam_context(user_db, "USMLE")
        other_exam_id = _exam_context(user_db, "OtherExam")
        parent = _make_node(user_db, "Parent")
        me = _make_node(user_db, "Me")
        sibling = _make_node(user_db, "Sibling")
        user_db.add_edge(parent, me, is_primary=True)
        user_db.add_edge(parent, sibling, is_primary=True)

        mine = _make_session(user_db, exam_id)
        other_exam = _make_session(user_db, other_exam_id)
        other_user = _make_session(user_db, exam_id, user_id=user_db.user_id + 999)

        _log_entry(user_db, mine, sibling)
        _log_entry(user_db, other_exam, sibling)
        _log_entry(user_db, other_user, sibling)

        related = _by_name(user_db.get_related_subjects(me, exam_id, limit=4))

        assert related["Sibling"]['entry_count'] == 1, (
            "another exam's and another user's entries must not be counted"
        )

    def test_candidate_with_no_in_scope_entries_still_appears(self, user_db):
        """Scoping must not drop the row — the panel needs the name at 0."""
        exam_id = _exam_context(user_db, "USMLE")
        other_exam_id = _exam_context(user_db, "OtherExam")
        parent = _make_node(user_db, "Parent")
        me = _make_node(user_db, "Me")
        sibling = _make_node(user_db, "Sibling")
        user_db.add_edge(parent, me, is_primary=True)
        user_db.add_edge(parent, sibling, is_primary=True)

        _log_entry(user_db, _make_session(user_db, other_exam_id), sibling)

        related = _by_name(user_db.get_related_subjects(me, exam_id, limit=4))

        assert "Sibling" in related
        assert related["Sibling"]['entry_count'] == 0

    def test_context_pin_does_not_change_the_count(self, user_db):
        """The discriminator: this function does not aggregate.

        D is shared by B and C. Pinning the entry to B must not change D's
        own count, because D is the subject the entry actually carries —
        §5.4 governs rollup *through ancestors* and there is no ancestor
        walk here. If someone ever "fixes" this by applying
        ``_primary_parent_scope_sql``, this goes red.
        """
        exam_id = _exam_context(user_db)
        session = _make_session(user_db, exam_id)
        a, b, c, d = _build_diamond(user_db)
        _log_entry(user_db, session, d, primary_parent_id=b)

        from_b = _by_name(user_db.get_related_subjects(b, exam_id, limit=10))
        from_c = _by_name(user_db.get_related_subjects(c, exam_id, limit=10))

        assert from_b["D"]['entry_count'] == 1
        assert from_c["D"]['entry_count'] == 1, (
            "a direct per-node count is context-independent"
        )


# ================================================== get_entries_by_subject


class TestEntriesBySubjectPrimaryParent:

    def test_pinned_parent_scopes_the_rollup(self, user_db):
        """§5.4 on an aggregating query.

        One entry on D, pinned to B. Rolling up through B must find it;
        rolling up through C must not. Pre-fix both returned it, because
        the scope set was ``{C} ∪ descendants(C) = {C, D}`` and the SQL
        asked only ``esm.subject_node_id IN (...)``.
        """
        exam_id = _exam_context(user_db)
        session = _make_session(user_db, exam_id)
        a, b, c, d = _build_diamond(user_db)
        entry_id = _log_entry(user_db, session, d, primary_parent_id=b)

        via_b = user_db.get_entries_by_subject(b, include_children=True)
        via_c = user_db.get_entries_by_subject(c, include_children=True)

        assert [e.id for e in via_b] == [entry_id]
        assert via_c == [], (
            "an entry pinned to B must not roll up through C"
        )

    def test_null_context_rolls_up_through_every_parent(self, user_db):
        """The other half of the §5.4 conditional (OMOP, §5.3)."""
        exam_id = _exam_context(user_db)
        session = _make_session(user_db, exam_id)
        a, b, c, d = _build_diamond(user_db)
        entry_id = _log_entry(user_db, session, d, primary_parent_id=None)

        via_b = user_db.get_entries_by_subject(b, include_children=True)
        via_c = user_db.get_entries_by_subject(c, include_children=True)

        assert [e.id for e in via_b] == [entry_id]
        assert [e.id for e in via_c] == [entry_id]

    def test_edge_only_descendants_are_reachable(self, user_db):
        """The scope set comes from ``subject_edges``, not the graph.

        C → D exists only as a non-primary edge and ``parent_id`` is NULL
        throughout, so a legacy-column walk finds nothing under C.
        """
        exam_id = _exam_context(user_db)
        session = _make_session(user_db, exam_id)
        a, b, c, d = _build_diamond(user_db)
        entry_id = _log_entry(user_db, session, d)

        via_c = user_db.get_entries_by_subject(c, include_children=True)

        assert [e.id for e in via_c] == [entry_id]

    def test_graph_answer_is_not_preferred_over_sqlite(self, user_db, monkeypatch):
        """The graph-first shortcut must stay removed.

        ``_graph_get_entries_for_subject`` resolves ``HAS_CHILD`` edges that
        ``_etl_subjects`` builds from the legacy ``parent_id`` column, so it
        cannot answer a polyhierarchy question — and the shortcut returned
        its answer verbatim, skipping the §5.4 predicate entirely. Feed it a
        deliberately wrong answer and require the SQL result instead.
        """
        exam_id = _exam_context(user_db)
        session = _make_session(user_db, exam_id)
        a, b, c, d = _build_diamond(user_db)
        wanted = _log_entry(user_db, session, d)
        decoy = _log_entry(user_db, session, a)

        # `_graph_read_ready` is a read-only property that is True on a real
        # profile DB with the graph library installed, which is exactly why
        # the shortcut fired in production. It is False wherever that library
        # is absent (CI, any fresh venv), which would let this test pass
        # vacuously -- so force it True on the class for this test rather
        # than require it from the environment. The decoy below is what a
        # reintroduced shortcut would return, in any environment.
        monkeypatch.setattr(
            type(user_db), '_graph_read_ready', property(lambda self: True)
        )
        monkeypatch.setattr(
            user_db,
            '_graph_get_entries_for_subject',
            lambda *args, **kwargs: [decoy],
            raising=False,
        )

        via_c = user_db.get_entries_by_subject(c, include_children=True)

        assert [e.id for e in via_c] == [wanted], (
            "SQLite is authoritative; the graph read must not be consulted"
        )

    def test_exam_context_scoping_is_opt_in(self, user_db):
        """New optional arg; default keeps the old unscoped behaviour."""
        exam_id = _exam_context(user_db, "USMLE")
        other_exam_id = _exam_context(user_db, "OtherExam")
        node = _make_node(user_db, "Solo")
        mine = _log_entry(user_db, _make_session(user_db, exam_id), node)
        theirs = _log_entry(user_db, _make_session(user_db, other_exam_id), node)

        unscoped = user_db.get_entries_by_subject(node, include_children=False)
        scoped = user_db.get_entries_by_subject(
            node, include_children=False, exam_context_id=exam_id
        )

        assert {e.id for e in unscoped} == {mine, theirs}
        assert [e.id for e in scoped] == [mine]

    def test_other_users_entries_are_excluded(self, user_db):
        exam_id = _exam_context(user_db)
        node = _make_node(user_db, "Solo")
        mine = _log_entry(user_db, _make_session(user_db, exam_id), node)
        _log_entry(
            user_db,
            _make_session(user_db, exam_id, user_id=user_db.user_id + 999),
            node,
        )

        result = user_db.get_entries_by_subject(node, include_children=False)

        assert [e.id for e in result] == [mine]

    def test_entries_by_subject_finds_the_leaf_whatever_the_context(self, user_db):
        """The #13 direct-tag clause, on the other caller of the helper.

        Same defect as the entry browser's subject filter and the same
        one-line cause: the scope for D alone is ``{D}``, the entry's
        chosen parent is B, and the strict §5.4 predicate asked only
        whether B was in scope. Browsing D then hid an entry tagged D.

        This surface is the "show me the entries on this subject"
        navigation query, so it takes the finding rule too. The rollup
        half is unchanged and still covered by
        ``test_pinned_parent_scopes_the_rollup`` above.
        """
        exam_id = _exam_context(user_db)
        session = _make_session(user_db, exam_id)
        a, b, c, d = _build_diamond(user_db)
        pinned = _log_entry(user_db, session, d, primary_parent_id=b)

        on_the_leaf = user_db.get_entries_by_subject(d, include_children=False)

        assert [e.id for e in on_the_leaf] == [pinned], (
            "an entry tagged D is about D whichever parent the student "
            "picked for it (Forgejo #13)"
        )

    def test_limit_is_bound_not_interpolated(self, user_db):
        exam_id = _exam_context(user_db)
        session = _make_session(user_db, exam_id)
        node = _make_node(user_db, "Solo")
        _log_entry(user_db, session, node)
        _log_entry(user_db, session, node)

        assert len(user_db.get_entries_by_subject(node, limit=1)) == 1
