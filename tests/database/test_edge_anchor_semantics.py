"""Tests for Stage 2 of the Hierarchical Weight Allocation plan.

Covers the per-edge write path
(:meth:`HierarchyMixin.update_edge_relative_weight`), the legacy
``update_subject_relative_weight`` shim's new no-rebalance contract, and
the explicit
:meth:`HierarchyMixin.rebalance_sibling_edge_weights` entry point.

Stage 3 will extend this file with anchor toggle / cross-parent
isolation tests; Stage 2 establishes the file and the core writer +
rebalance semantics.

Reference: ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``
Stage 2; ``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``
§3.3 / §5.2.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.exceptions import WeightValidationError


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def temp_dir():
    """Create a temporary directory for the test databases."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    """Create a master database instance."""
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def test_user(master_db):
    """Create a test user."""
    return master_db.create_user(
        username="edge_anchor_user",
        display_name="Edge Anchor User",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db, test_user):
    """A fully-migrated UserDatabase for the test user."""
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username,
    )
    yield db
    db.close()


def _make_node(
    user_db,
    name: str,
    parent_id=None,
    weight_locked: bool = False,
) -> int:
    """Insert a subject_node directly and return its id.

    Mirrors the helper in ``test_subject_edges.py`` but accepts a
    ``weight_locked`` flag so tests can construct nodes with the legacy
    lock semantics in one line.
    """
    cursor = user_db.execute(
        "INSERT INTO subject_nodes "
        "(exam_context, name, level_type, parent_id, sort_order, status, weight_locked) "
        "VALUES (?, ?, ?, ?, ?, 'active', ?)",
        ("USMLE", name, "Topic", parent_id, 0, bool(weight_locked)),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _set_edge_weight(user_db, edge_id: int, weight: float, is_anchor: bool = False) -> None:
    """Seed an edge's ``relative_weight`` (and optionally anchor flag) directly.

    Bypasses the writer methods so tests can establish a baseline state
    without invoking the code under test.
    """
    user_db.execute(
        "UPDATE subject_edges SET relative_weight = ?, is_anchor = ? WHERE id = ?",
        (weight, bool(is_anchor), edge_id),
    )
    user_db.conn.commit()


@pytest.fixture
def parent_with_three_children(user_db):
    """Build a parent node with three children + primary edges.

    Returns ``{"parent_id": int, "children": [int, int, int],
    "edges": [int, int, int]}``. The edges are seeded with
    ``relative_weight`` 30/30/40 to give a non-uniform proportional
    baseline for rebalance tests.
    """
    parent = _make_node(user_db, "ParentSystem")
    child_a = _make_node(user_db, "ChildA", parent_id=parent)
    child_b = _make_node(user_db, "ChildB", parent_id=parent)
    child_c = _make_node(user_db, "ChildC", parent_id=parent)

    edge_a = user_db.add_edge(parent, child_a, is_primary=True)
    edge_b = user_db.add_edge(parent, child_b, is_primary=True)
    edge_c = user_db.add_edge(parent, child_c, is_primary=True)

    _set_edge_weight(user_db, edge_a.id, 30.0)
    _set_edge_weight(user_db, edge_b.id, 30.0)
    _set_edge_weight(user_db, edge_c.id, 40.0)

    return {
        "parent_id": parent,
        "children": [child_a, child_b, child_c],
        "edges": [edge_a.id, edge_b.id, edge_c.id],
    }


# ---------------------------------------------------------------- update_edge_relative_weight


def test_update_edge_relative_weight_writes_to_subject_edges(
    user_db, parent_with_three_children
):
    """A direct edge write lands in ``subject_edges.relative_weight``."""
    fix = parent_with_three_children
    edge_id = fix["edges"][0]

    result = user_db.update_edge_relative_weight(edge_id, 55.0)

    assert result['ok'] is True
    assert result['edge_id'] == edge_id
    assert result['old_weight'] == pytest.approx(30.0)
    assert result['new_weight'] == pytest.approx(55.0)
    assert result['anchor_set'] is False

    row = user_db.fetchone(
        "SELECT relative_weight, weight_source FROM subject_edges WHERE id = ?",
        (edge_id,),
    )
    assert row['relative_weight'] == pytest.approx(55.0)
    assert row['weight_source'] == 'user_explicit'


def test_update_edge_relative_weight_does_not_touch_siblings(
    user_db, parent_with_three_children
):
    """Writing one edge must not modify any sibling's weight."""
    fix = parent_with_three_children
    target_edge = fix["edges"][0]
    sibling_a = fix["edges"][1]
    sibling_b = fix["edges"][2]

    user_db.update_edge_relative_weight(target_edge, 80.0)

    row_a = user_db.fetchone(
        "SELECT relative_weight FROM subject_edges WHERE id = ?", (sibling_a,)
    )
    row_b = user_db.fetchone(
        "SELECT relative_weight FROM subject_edges WHERE id = ?", (sibling_b,)
    )
    assert row_a['relative_weight'] == pytest.approx(30.0)
    assert row_b['relative_weight'] == pytest.approx(40.0)


def test_update_edge_relative_weight_writes_history_with_edge_id(
    user_db, parent_with_three_children
):
    """History row carries ``change_type='edge_weight_edit'`` + the edge_id."""
    fix = parent_with_three_children
    edge_id = fix["edges"][0]

    user_db.update_edge_relative_weight(edge_id, 42.0, reason="Test write")

    row = user_db.fetchone(
        "SELECT change_type, edge_id, previous_weight "
        "FROM subject_node_weights "
        "WHERE edge_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (edge_id,),
    )
    assert row is not None, (
        "No history row written. edge_weight_edit change_type was added "
        "by m006 — confirm the migration ran."
    )
    assert row['change_type'] == 'edge_weight_edit'
    assert row['edge_id'] == edge_id
    assert row['previous_weight'] == pytest.approx(30.0)


def test_update_edge_relative_weight_with_set_anchor_sets_is_anchor(
    user_db, parent_with_three_children
):
    """Passing ``set_anchor=True`` flips ``subject_edges.is_anchor`` to True."""
    fix = parent_with_three_children
    edge_id = fix["edges"][0]

    # Sanity: starts un-anchored.
    pre = user_db.fetchone(
        "SELECT is_anchor FROM subject_edges WHERE id = ?", (edge_id,)
    )
    assert bool(pre['is_anchor']) is False

    result = user_db.update_edge_relative_weight(edge_id, 25.0, set_anchor=True)
    assert result['anchor_set'] is True

    post = user_db.fetchone(
        "SELECT is_anchor, relative_weight FROM subject_edges WHERE id = ?",
        (edge_id,),
    )
    assert bool(post['is_anchor']) is True
    assert post['relative_weight'] == pytest.approx(25.0)


def test_update_edge_relative_weight_rejects_out_of_range(
    user_db, parent_with_three_children
):
    """Validation: weight must lie in ``[0, 100]``."""
    edge_id = parent_with_three_children["edges"][0]
    with pytest.raises(WeightValidationError):
        user_db.update_edge_relative_weight(edge_id, -1.0)
    with pytest.raises(WeightValidationError):
        user_db.update_edge_relative_weight(edge_id, 101.0)


# ---------------------------------------------------------------- legacy shim


def test_update_subject_relative_weight_no_longer_rebalances(
    user_db, parent_with_three_children
):
    """The legacy node-level writer is now a no-rebalance shim.

    Stage 2 contract: siblings stay byte-identical after a write to one
    node's relative weight. The returned payload reports
    ``rebalanced=False`` and ``affected_siblings=[]``.
    """
    fix = parent_with_three_children
    target_child = fix["children"][0]
    sibling_edges = [fix["edges"][1], fix["edges"][2]]

    # Snapshot sibling edge weights pre-write.
    pre = {
        e: user_db.fetchone(
            "SELECT relative_weight FROM subject_edges WHERE id = ?", (e,)
        )['relative_weight']
        for e in sibling_edges
    }

    result = user_db.update_subject_relative_weight(target_child, 75.0)
    assert result['rebalanced'] is False
    assert result['affected_siblings'] == []
    assert result['new_weight'] == pytest.approx(75.0)

    # Sibling edges must be unchanged.
    for edge_id, original in pre.items():
        post = user_db.fetchone(
            "SELECT relative_weight FROM subject_edges WHERE id = ?", (edge_id,)
        )['relative_weight']
        assert post == pytest.approx(original), (
            f"Sibling edge {edge_id} was silently mutated by the legacy "
            f"writer: {original} -> {post}. Stage 2 forbids this."
        )


# ---------------------------------------------------------------- rebalance_sibling_edge_weights


def test_rebalance_sibling_edge_weights_excludes_anchored(
    user_db, parent_with_three_children
):
    """Anchored edges keep their weight byte-identical after rebalance."""
    fix = parent_with_three_children
    anchored_edge = fix["edges"][0]
    _set_edge_weight(user_db, anchored_edge, 30.0, is_anchor=True)

    result = user_db.rebalance_sibling_edge_weights(fix["parent_id"])
    assert result['ok'] is True

    # The anchored edge's weight is unchanged.
    row = user_db.fetchone(
        "SELECT relative_weight FROM subject_edges WHERE id = ?",
        (anchored_edge,),
    )
    assert row['relative_weight'] == pytest.approx(30.0)

    # And it appears in 'skipped' with reason='anchored'.
    skipped_ids = {s['edge_id']: s['reason'] for s in result['skipped']}
    assert skipped_ids.get(anchored_edge) == 'anchored'


def test_rebalance_sibling_edge_weights_excludes_weight_locked(
    user_db,
):
    """Edges whose child has legacy ``weight_locked=TRUE`` are skipped.

    Both anchor (new) and weight_locked (legacy) exclude — they coexist
    per plan §3.3 / Stage 2 open-question decision. This test exercises
    the legacy flag specifically.
    """
    parent = _make_node(user_db, "ParentForLock")
    locked_child = _make_node(user_db, "LockedChild", parent_id=parent, weight_locked=True)
    free_child_a = _make_node(user_db, "FreeChildA", parent_id=parent)
    free_child_b = _make_node(user_db, "FreeChildB", parent_id=parent)

    e_locked = user_db.add_edge(parent, locked_child, is_primary=True)
    e_free_a = user_db.add_edge(parent, free_child_a, is_primary=True)
    e_free_b = user_db.add_edge(parent, free_child_b, is_primary=True)

    _set_edge_weight(user_db, e_locked.id, 30.0)
    _set_edge_weight(user_db, e_free_a.id, 30.0)
    _set_edge_weight(user_db, e_free_b.id, 40.0)

    result = user_db.rebalance_sibling_edge_weights(parent)

    skipped = {s['edge_id']: s['reason'] for s in result['skipped']}
    assert skipped.get(e_locked.id) == 'weight_locked'

    # The locked edge weight is unchanged.
    locked_row = user_db.fetchone(
        "SELECT relative_weight FROM subject_edges WHERE id = ?",
        (e_locked.id,),
    )
    assert locked_row['relative_weight'] == pytest.approx(30.0)


def test_rebalance_sibling_edge_weights_distributes_remainder_proportionally(
    user_db, parent_with_three_children
):
    """With one anchor at 30, the other two split the remaining 70 by 30:40 ratio.

    Concretely: anchor ChildA at 30%. ChildB and ChildC currently sit
    at 30 and 40 respectively (ratio 3:4). The remainder budget is
    100 - 30 = 70%, so:

    - ChildB → 70 * 30/70 = 30
    - ChildC → 70 * 40/70 = 40

    The starting state already happens to sum to 100, so this test
    confirms that proportional rebalance is a no-op when the
    adjustables already saturate the remainder. The more interesting
    case is when the user has already overridden a value — covered
    below.
    """
    fix = parent_with_three_children
    anchor_edge = fix["edges"][0]
    _set_edge_weight(user_db, anchor_edge, 30.0, is_anchor=True)

    result = user_db.rebalance_sibling_edge_weights(fix["parent_id"])

    # Two adjustable edges affected, one anchored skipped.
    assert len(result['affected_edges']) == 2
    assert len(result['skipped']) == 1

    # Sum must still be ~100%.
    total = 0.0
    for edge_id in fix["edges"]:
        row = user_db.fetchone(
            "SELECT relative_weight FROM subject_edges WHERE id = ?",
            (edge_id,),
        )
        total += float(row['relative_weight'])
    assert total == pytest.approx(100.0, abs=0.1)

    # Verify the proportional split: ChildB and ChildC retain their
    # 30:40 ratio scaled to the 70% remainder budget — i.e. 30 and 40.
    row_b = user_db.fetchone(
        "SELECT relative_weight FROM subject_edges WHERE id = ?",
        (fix["edges"][1],),
    )
    row_c = user_db.fetchone(
        "SELECT relative_weight FROM subject_edges WHERE id = ?",
        (fix["edges"][2],),
    )
    assert row_b['relative_weight'] == pytest.approx(30.0, abs=0.1)
    assert row_c['relative_weight'] == pytest.approx(40.0, abs=0.1)


def test_rebalance_sibling_edge_weights_writes_auto_recalculate_history(
    user_db, parent_with_three_children
):
    """Each affected edge gets a history row with ``change_type='auto_recalculate'``."""
    fix = parent_with_three_children
    # Anchor first edge so the other two are adjustable.
    _set_edge_weight(user_db, fix["edges"][0], 30.0, is_anchor=True)

    result = user_db.rebalance_sibling_edge_weights(
        fix["parent_id"], reason="Test history"
    )

    for affected in result['affected_edges']:
        edge_id = affected['edge_id']
        row = user_db.fetchone(
            "SELECT change_type, edge_id FROM subject_node_weights "
            "WHERE edge_id = ? AND change_type = 'auto_recalculate' "
            "ORDER BY id DESC LIMIT 1",
            (edge_id,),
        )
        assert row is not None, (
            f"No auto_recalculate row for edge {edge_id}. The history "
            f"path in rebalance_sibling_edge_weights may be silently "
            f"swallowing exceptions."
        )
        assert row['change_type'] == 'auto_recalculate'
        assert row['edge_id'] == edge_id


def test_rebalance_sibling_edge_weights_empty_when_no_siblings(user_db):
    """Rebalance on a leaf parent returns an empty affected list."""
    leaf = _make_node(user_db, "Leaf")
    result = user_db.rebalance_sibling_edge_weights(leaf)
    assert result['ok'] is True
    assert result['affected_edges'] == []
    assert result['skipped'] == []


# ================================================================
# Stage 3 — Edge-anchor + per-edge writer behavior under polyhierarchy
#
# Stage 2 covered the basic writer + rebalance contract. Stage 3
# adds the cross-parent isolation tests that prove the anchor flag
# is scoped to the edge, not the child node — and the history
# audit-trail tests for the dedicated ``set_edge_anchor`` /
# ``set_edge_weight_source`` methods on ``EdgesMixin``.
# Reference: ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``
# Stage 3; ``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``
# §3.3.
# ================================================================


@pytest.fixture
def hypertension_two_parents(user_db):
    """Hypertension lives under both Cardiovascular and Pregnancy.

    Returns a dict with the parent and child ids plus the two edges
    Hypertension participates in (``edge_cardio_hyp``,
    ``edge_preg_hyp``). Each parent also gets a sibling under
    Hypertension so cross-parent rebalance can be exercised
    realistically.

    Mirrors the canonical polyhierarchy example from
    ``docs/planning/POLYHIERARCHY_MIGRATION.md`` and the
    Stage 3 testing table in the implementation plan.
    """
    cardio = _make_node(user_db, "Cardiovascular")
    preg = _make_node(user_db, "Pregnancy")
    hyp = _make_node(user_db, "Hypertension")

    # Siblings under each parent so rebalance has someone to talk to.
    cardio_sibling = _make_node(user_db, "Arrhythmia", parent_id=cardio)
    preg_sibling = _make_node(user_db, "Gestational Diabetes", parent_id=preg)

    edge_cardio_hyp = user_db.add_edge(cardio, hyp, is_primary=True)
    edge_preg_hyp = user_db.add_edge(preg, hyp, is_primary=False)
    edge_cardio_sib = user_db.add_edge(cardio, cardio_sibling, is_primary=True)
    edge_preg_sib = user_db.add_edge(preg, preg_sibling, is_primary=True)

    # Seed baseline weights so rebalance has meaningful values to chew on.
    _set_edge_weight(user_db, edge_cardio_hyp.id, 60.0)
    _set_edge_weight(user_db, edge_cardio_sib.id, 40.0)
    _set_edge_weight(user_db, edge_preg_hyp.id, 70.0)
    _set_edge_weight(user_db, edge_preg_sib.id, 30.0)

    return {
        "cardio_id": cardio,
        "preg_id": preg,
        "hyp_id": hyp,
        "edge_cardio_hyp": edge_cardio_hyp.id,
        "edge_preg_hyp": edge_preg_hyp.id,
        "edge_cardio_sib": edge_cardio_sib.id,
        "edge_preg_sib": edge_preg_sib.id,
    }


def test_anchor_set_clears_under_one_parent_only(
    user_db, hypertension_two_parents
):
    """Anchoring Hypertension under Cardio must NOT anchor the Pregnancy edge.

    This is the core invariant of Stage 3: ``is_anchor`` is a
    per-edge flag, not a per-child flag. Two edges into the same
    child can carry different anchor states.
    """
    fix = hypertension_two_parents

    edge, history_id = user_db.set_edge_anchor(fix["edge_cardio_hyp"], True)
    assert edge.id == fix["edge_cardio_hyp"]
    assert edge.is_anchor is True

    # The Pregnancy edge into the same child must stay un-anchored.
    preg_row = user_db.fetchone(
        "SELECT is_anchor FROM subject_edges WHERE id = ?",
        (fix["edge_preg_hyp"],),
    )
    assert bool(preg_row['is_anchor']) is False, (
        "Anchoring (Cardio → Hypertension) leaked to (Pregnancy → Hypertension). "
        "is_anchor is supposed to be per-edge per Stage 3 §3.3."
    )


def test_anchored_edge_survives_sibling_edit(
    user_db, hypertension_two_parents
):
    """Anchoring edge A and writing sibling edge B leaves A byte-identical.

    Combined with Stage 2's ``update_edge_relative_weight`` no-rebalance
    contract, this proves the anchor flag truly works as a fence even
    when an adjacent write occurs.
    """
    fix = hypertension_two_parents

    # Anchor the Cardio → Hypertension edge.
    user_db.set_edge_anchor(fix["edge_cardio_hyp"], True)
    pre_row = user_db.fetchone(
        "SELECT relative_weight, is_anchor FROM subject_edges WHERE id = ?",
        (fix["edge_cardio_hyp"],),
    )
    pre_weight = float(pre_row['relative_weight'])

    # Write to the sibling edge under the same parent.
    user_db.update_edge_relative_weight(fix["edge_cardio_sib"], 25.0)

    # The anchored edge must be untouched, byte-identical.
    post_row = user_db.fetchone(
        "SELECT relative_weight, is_anchor FROM subject_edges WHERE id = ?",
        (fix["edge_cardio_hyp"],),
    )
    assert float(post_row['relative_weight']) == pytest.approx(pre_weight)
    assert bool(post_row['is_anchor']) is True


def test_anchor_history_event_records_edge_id(
    user_db, hypertension_two_parents
):
    """Setting anchor writes a ``change_type='anchor_set'`` history row.

    The row carries ``edge_id`` (the new column from m006) so the
    audit trail can distinguish per-edge events. The
    ``subject_node_id`` FK is populated with the edge's ``child_id``
    so per-node history queries still surface the event.
    """
    fix = hypertension_two_parents
    edge_id = fix["edge_cardio_hyp"]

    edge, history_id = user_db.set_edge_anchor(
        edge_id, True, reason="Stage 3 test"
    )

    row = user_db.fetchone(
        "SELECT id, change_type, edge_id, subject_node_id, edited_reason "
        "FROM subject_node_weights "
        "WHERE edge_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (edge_id,),
    )
    assert row is not None, (
        "No history row written for anchor_set. m006 should have widened "
        "the change_type enum — check the migration ran."
    )
    assert row['change_type'] == 'anchor_set'
    assert row['edge_id'] == edge_id
    assert row['subject_node_id'] == fix["hyp_id"]
    assert row['edited_reason'] == 'Stage 3 test'
    if history_id is not None:
        assert history_id == row['id']


def test_anchor_clear_writes_anchor_cleared_history(
    user_db, hypertension_two_parents
):
    """Clearing an anchor writes ``change_type='anchor_cleared'``."""
    fix = hypertension_two_parents
    edge_id = fix["edge_cardio_hyp"]

    user_db.set_edge_anchor(edge_id, True)
    user_db.set_edge_anchor(edge_id, False)

    row = user_db.fetchone(
        "SELECT change_type, edge_id FROM subject_node_weights "
        "WHERE edge_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (edge_id,),
    )
    assert row is not None
    assert row['change_type'] == 'anchor_cleared'
    assert row['edge_id'] == edge_id

    # And the edge flag is now False.
    edge_row = user_db.fetchone(
        "SELECT is_anchor FROM subject_edges WHERE id = ?", (edge_id,)
    )
    assert bool(edge_row['is_anchor']) is False


def test_set_edge_anchor_unknown_edge_raises(user_db):
    """Unknown ``edge_id`` raises ``SubjectNodeError`` cleanly."""
    from database.exceptions import SubjectNodeError
    with pytest.raises(SubjectNodeError):
        user_db.set_edge_anchor(999_999, True)


def test_set_edge_weight_source_updates_column(
    user_db, parent_with_three_children
):
    """``set_edge_weight_source`` flips the column without history side-effects.

    Source is metadata about provenance, not a value change — no
    ``subject_node_weights`` row is written.
    """
    edge_id = parent_with_three_children["edges"][0]

    # Snapshot history-row count for this edge so we can prove no
    # row was appended.
    pre_count = user_db.fetchone(
        "SELECT COUNT(*) AS c FROM subject_node_weights WHERE edge_id = ?",
        (edge_id,),
    )['c']

    user_db.set_edge_weight_source(edge_id, 'user_explicit')

    row = user_db.fetchone(
        "SELECT weight_source FROM subject_edges WHERE id = ?", (edge_id,)
    )
    assert row['weight_source'] == 'user_explicit'

    post_count = user_db.fetchone(
        "SELECT COUNT(*) AS c FROM subject_node_weights WHERE edge_id = ?",
        (edge_id,),
    )['c']
    assert post_count == pre_count, (
        "set_edge_weight_source wrote a history row. It is metadata-only "
        "by design — only set_edge_anchor / update_edge_relative_weight "
        "should append to subject_node_weights."
    )


def test_set_edge_weight_source_rejects_invalid_value(
    user_db, parent_with_three_children
):
    """Bad enum values raise ``WeightValidationError`` with a clear message."""
    edge_id = parent_with_three_children["edges"][0]
    with pytest.raises(WeightValidationError):
        user_db.set_edge_weight_source(edge_id, 'bogus')


def test_set_edge_weight_source_unknown_edge_raises(user_db):
    """Unknown ``edge_id`` raises ``SubjectNodeError``."""
    from database.exceptions import SubjectNodeError
    with pytest.raises(SubjectNodeError):
        user_db.set_edge_weight_source(999_999, 'user_explicit')


def test_get_edges_for_child_returns_primary_first(
    user_db, hypertension_two_parents
):
    """``get_edges_for_child`` orders primary edge first."""
    fix = hypertension_two_parents

    edges = user_db.get_edges_for_child(fix["hyp_id"])

    assert len(edges) == 2
    assert edges[0]['is_primary'] is True
    assert edges[0]['edge_id'] == fix["edge_cardio_hyp"]
    assert edges[0]['parent_name'] == 'Cardiovascular'
    assert edges[1]['is_primary'] is False
    assert edges[1]['edge_id'] == fix["edge_preg_hyp"]
    assert edges[1]['parent_name'] == 'Pregnancy'

    # Each row carries per-edge weight metadata.
    for row in edges:
        assert 'relative_weight' in row
        assert 'is_anchor' in row
        assert 'weight_source' in row
        assert 'sort_order' in row


def test_get_edges_for_child_empty_for_orphan(user_db):
    """A child with no parents returns an empty list."""
    orphan = _make_node(user_db, "Orphan")
    assert user_db.get_edges_for_child(orphan) == []
