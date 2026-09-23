"""Tests for the entry-count sources fixed in T3 of ``ENTRY_COUNT_AUDIT.md``.

Three defects, none of which is a §5.4 / ``primary_parent_id`` problem —
recorded here because the distinction keeps getting lost:

1. ``get_subject_deep_dive``'s **child-subjects LIST** was built from the
   legacy ``subject_nodes.parent_id`` column, so a child attached only via
   ``subject_edges`` vanished from the breakdown. The per-child *counts* were
   already correct. Aggregating surface, but the bug was in the list, which a
   rollup predicate cannot fix.
2. ``get_subject_deep_dive``'s **sibling panel** counted secondary tags, read
   the legacy parent column, and — because ``rs.user_id`` was filtered only
   inside an ``if not exam_context_id`` branch — never scoped to the user in
   the normal case. Non-aggregating: direct per-node counts, no ancestor
   walk, so §5.4 is definitionally inapplicable.

   **Superseded by issue #14, which removed the panel outright.** The
   assertions below now pin its *absence* — the defect is gone because the
   surface is. Kept rather than deleted so a reinstated structural sibling
   query fails a test instead of quietly reappearing.
3. ``get_subject_analytics``'s **trend sub-queries** had no ``mapping_type``
   while the main and bucket queries did. Also non-aggregating
   (``esm.subject_node_id = ?``), so the only criterion is ``mapping_type``.

The shape that exposes all three: a node whose only link to its parent is a
``subject_edges`` row, with ``subject_nodes.parent_id`` left NULL (or pointed
somewhere else entirely). ``_make_node`` writes only the legacy column and
``add_edge`` writes only the junction table, so every test states explicitly
which of the two sources knows about each relationship — that is what keeps
these assertions from passing for the wrong reason.
"""
from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def other_user(master_db):
    """A second user, so "scoped to the user" can actually fail."""
    return master_db.create_user(
        username="dd_other",
        display_name="Other Student",
        user_types=["student"],
    )


@pytest.fixture
def test_user(master_db):
    return master_db.create_user(
        username="dd_user",
        display_name="Deep Dive User",
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


# ---------------------------------------------------------------- helpers


def _make_node(user_db, name: str, parent_id=None) -> int:
    """Insert a bare subject node.

    ``parent_id`` writes the LEGACY column only — no ``subject_edges`` row.
    Edges are added explicitly with ``add_edge`` so each test controls
    precisely which of the two sources knows about a relationship.
    """
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, sort_order, status) "
        "VALUES (?, ?, ?, ?, 0, 'active')",
        ("USMLE", name, "Topic", parent_id),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _exam_context_id(user_db, user_id=None) -> int:
    row = user_db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = 'USMLE'"
    )
    if row is not None:
        return row['id']
    cursor = user_db.execute(
        "INSERT INTO exam_contexts (user_id, exam_name, exam_description) "
        "VALUES (?, 'USMLE', 'Test')",
        (user_id if user_id is not None else user_db.user_id,),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _make_session(user_db, exam_context_id, user_id=None, days_ago=0) -> int:
    when = (date.today() - timedelta(days=days_ago)).isoformat()
    cursor = user_db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            user_id if user_id is not None else user_db.user_id,
            "Test session",
            when,
            exam_context_id,
            1,
            1,
        ),
    )
    user_db.conn.commit()
    return cursor.lastrowid


_ENTRY_ORDER = {'n': 0}


def _log_entry(
    user_db,
    session_id,
    subject_node_id,
    mapping_type='primary',
    primary_parent_id=None,
):
    _ENTRY_ORDER['n'] += 1
    cursor = user_db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, ?, ?)",
        (session_id, _ENTRY_ORDER['n'], "A", "B"),
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


# ============================================================ child list


class TestDeepDiveChildList:
    """``get_subject_deep_dive`` → ``child_subjects``.

    This surface DOES aggregate: each child's count walks that child's
    whole subtree through ``subject_edges``. But the defect fixed here is
    the *list* of children, which no rollup predicate can repair — a child
    missing from the list contributes nothing no matter how the counts are
    computed.
    """

    def test_edge_only_child_appears_in_child_list(self, user_db):
        """A child attached to the parent ONLY via ``subject_edges``.

        Its ``subject_nodes.parent_id`` is NULL, so the old
        ``WHERE sn.parent_id = ?`` list dropped it silently even though its
        entries were real and its count would have been correct.
        """
        parent = _make_node(user_db, "Parent")
        legacy_kid = _make_node(user_db, "LegacyKid", parent_id=parent)
        user_db.add_edge(parent, legacy_kid, is_primary=True)

        edge_only_kid = _make_node(user_db, "EdgeOnlyKid")  # parent_id stays NULL
        user_db.add_edge(parent, edge_only_kid, is_primary=True)

        ec = _exam_context_id(user_db)
        session = _make_session(user_db, ec)
        _log_entry(user_db, session, legacy_kid)
        _log_entry(user_db, session, edge_only_kid)
        _log_entry(user_db, session, edge_only_kid)

        payload = user_db.get_subject_deep_dive(subject_id=parent)
        by_name = {c['subject_name']: c for c in payload['child_subjects']}

        assert "EdgeOnlyKid" in by_name, (
            "edge-only child omitted from the Child Subjects breakdown"
        )
        assert by_name["EdgeOnlyKid"]['mistake_count'] == 2
        # The legacy-column child must not regress out of the list.
        assert by_name["LegacyKid"]['mistake_count'] == 1

    def test_child_list_survives_a_relocated_legacy_parent_id(self, user_db):
        """The edge is authoritative even when ``parent_id`` disagrees.

        ``Kid.parent_id`` points at an unrelated node while the only real
        edge says ``Parent → Kid``. Reading the legacy column here does not
        merely omit the child, it attributes it to the wrong parent.
        """
        parent = _make_node(user_db, "Parent")
        decoy = _make_node(user_db, "Decoy")
        kid = _make_node(user_db, "Kid", parent_id=decoy)
        user_db.add_edge(parent, kid, is_primary=True)

        ec = _exam_context_id(user_db)
        session = _make_session(user_db, ec)
        _log_entry(user_db, session, kid)

        under_parent = user_db.get_subject_deep_dive(subject_id=parent)
        under_decoy = user_db.get_subject_deep_dive(subject_id=decoy)

        assert [c['subject_name'] for c in under_parent['child_subjects']] == ["Kid"]
        assert under_decoy['child_subjects'] == []


# ============================================================== siblings


class TestDeepDiveSiblingsRemoved:
    """``get_subject_deep_dive`` no longer returns ``sibling_subjects``.

    This class used to assert the sibling panel's semantics: secondary
    tags excluded, peers read from ``subject_edges`` rather than the
    legacy parent column, user scoping applied even when an exam was
    supplied, and the peer set following the selected parent context.
    Issue #14 removed the panel instead of continuing to refine it — the
    owner's "siblings" are *semantic relations* between topics
    ("hypertension leads to hypertensive nephrosclerosis"), and tree
    adjacency is a weak proxy: two topics can share a parent and have
    nothing to do with each other, and a multi-parent subject has a
    different peer set under each parent. Showing something misleading
    is worse than showing nothing, so the panel is gone and the payload
    key with it.

    The shape is kept rather than deleted so the *absence* is asserted
    against exactly the data that used to make the panel non-empty: a
    multi-parent subject with peers under both parents, each carrying
    entries. If a future change reinstates a structural sibling query,
    this fails.
    """

    def _build(self, user_db):
        """``Parent → {Subject, PeerA}``; ``OtherParent → {Subject, FarPeer}``.

        Subject has two parents, which is the case the old panel could
        not answer coherently.
        """
        parent = _make_node(user_db, "Parent")
        other_parent = _make_node(user_db, "OtherParent")
        subject = _make_node(user_db, "Subject", parent_id=parent)
        peer_a = _make_node(user_db, "PeerA", parent_id=parent)
        far_peer = _make_node(user_db, "FarPeer")

        user_db.add_edge(parent, subject, is_primary=True)
        user_db.add_edge(other_parent, subject, is_primary=False)
        user_db.add_edge(parent, peer_a, is_primary=True)
        user_db.add_edge(other_parent, far_peer, is_primary=True)
        return parent, other_parent, subject, peer_a, far_peer

    def test_payload_has_no_sibling_key(self, user_db):
        """Not an empty list — no key at all.

        Nothing consumes it: the only reader was
        ``subject_deep_dive.js``'s ``renderRelatedTopics``, removed in
        the same change, and the bridge slot passes the dict straight
        through. Leaving an always-empty key would invite a caller to
        start depending on it before the replacement feature exists.
        """
        parent, other_parent, subject, peer_a, far_peer = self._build(user_db)
        ec = _exam_context_id(user_db)
        session = _make_session(user_db, ec)
        _log_entry(user_db, session, peer_a)
        _log_entry(user_db, session, far_peer)

        for parent_context in (None, parent, other_parent):
            payload = user_db.get_subject_deep_dive(
                subject_id=subject,
                exam_context_id=ec,
                primary_parent_id=parent_context,
            )
            assert "sibling_subjects" not in payload, (
                "the sibling panel payload is back "
                f"(parent context {parent_context!r}): {payload!r}"
            )

    def test_the_rest_of_the_deep_dive_still_answers(self, user_db):
        """Removing the sub-query did not take anything else with it."""
        parent, _other, subject, _peer, _far = self._build(user_db)
        ec = _exam_context_id(user_db)
        session = _make_session(user_db, ec)
        _log_entry(user_db, session, subject)

        payload = user_db.get_subject_deep_dive(
            subject_id=subject, exam_context_id=ec, primary_parent_id=parent
        )

        assert payload["subject_name"] == "Subject"
        assert payload["direct_mistakes"] == 1
        assert payload["path_via_parent"]
        assert payload["child_subjects"] == []
        assert payload["recent_entries"]


# ================================================================= trend


class TestSubjectAnalyticsTrend:
    """``get_subject_analytics`` → ``trend``.

    Non-aggregating: both sub-queries pin ``esm.subject_node_id = ?`` with no
    descendant CTE, so §5.4 does not apply and ``mapping_type`` is the whole
    criterion. The arrow feeds Top Subjects and ``get_patterns_and_insights``.
    """

    def _trend_for(self, user_db, subject_id, exam_context_id):
        rows = user_db.get_subject_analytics(
            exam_context_id=exam_context_id, limit=50
        )
        by_id = {r['subject_id']: r for r in rows}
        return by_id.get(subject_id)

    def test_trend_ignores_secondary_tags(self, user_db):
        """Secondary tags this week must not push the arrow up.

        One primary entry 10 days ago (the 'previous' window) and two
        *secondary* entries today. Counting secondary gives recent=2 >
        previous=1 → 'up'; ignoring it gives recent=0 < previous=1 → 'down'.
        """
        subject = _make_node(user_db, "Subject")
        ec = _exam_context_id(user_db)
        old_session = _make_session(user_db, ec, days_ago=10)
        new_session = _make_session(user_db, ec, days_ago=0)

        _log_entry(user_db, old_session, subject, mapping_type='primary')
        _log_entry(user_db, new_session, subject, mapping_type='secondary')
        _log_entry(user_db, new_session, subject, mapping_type='secondary')

        row = self._trend_for(user_db, subject, ec)
        assert row is not None, "subject missing from analytics payload"
        assert row['trend'] == 'down', (
            f"trend arrow moved on secondary tags (got {row['trend']!r})"
        )

    def test_trend_still_tracks_primary_tags(self, user_db):
        """Teeth check: the arrow must still respond to real primary entries."""
        subject = _make_node(user_db, "Subject")
        ec = _exam_context_id(user_db)
        old_session = _make_session(user_db, ec, days_ago=10)
        new_session = _make_session(user_db, ec, days_ago=0)

        _log_entry(user_db, old_session, subject, mapping_type='primary')
        _log_entry(user_db, new_session, subject, mapping_type='primary')
        _log_entry(user_db, new_session, subject, mapping_type='primary')

        row = self._trend_for(user_db, subject, ec)
        assert row is not None
        assert row['trend'] == 'up'
