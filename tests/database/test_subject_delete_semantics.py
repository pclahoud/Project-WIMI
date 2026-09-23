"""Tests for subject delete semantics — issue #15.

``_delete_node_recursive`` used to find a node's children through the
legacy ``subject_nodes.parent_id`` column. ``subject_edges`` has been the
source of truth since m004, so an edge-only child was never visited: the
parent was archived and the child was left behind, still ``active``, still
holding an edge from an archived parent. That makes it neither a root
(``get_subject_hierarchy`` defines roots as nodes with no incoming edge)
nor anybody's child (its parent is filtered out by status) — invisible,
not merely misplaced.

The issue records three casualties and the owner's five decisions. What
is asserted here, decision by decision:

1. Shared children are **detached, not deleted** — a child is archived
   only when the deleted parent held its last surviving parent edge.
2. Exclusive children: the caller chooses delete or promote, one global
   choice covering all of the target's *direct* children at once; a
   promoted child carries its own exclusive descendants with it.
3. An orphaned ``entry_subject_mappings.primary_parent_id`` is **nulled**,
   which drops those entries into §5.4's NULL branch instead of leaving
   them rolling up nowhere. m005 already declares the column
   ``ON DELETE SET NULL``; the FK never fires only because the delete is
   soft.
4. The delete is stamped with a **delete batch id** and journalled.
5. The **preview** must match what the delete actually does.

Plus casualty 2: ``get_parents`` had no status filter, so a child kept
reporting a deleted parent.

The shape most tests build:

::

        Pdel      Qkeep          Pdel is the one being deleted.
           \\      /              Shared is held by both parents;
          Shared  Exclusive      Exclusive only by Pdel.
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.exceptions import SubjectNodeError


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
def test_user(master_db):
    return master_db.create_user(
        username="delete_user",
        display_name="Delete Semantics User",
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


def _node(user_db, name: str) -> int:
    """Insert a bare subject_node. No legacy ``parent_id``, no edge.

    Deliberately raw: every parent link in these tests is an edge and only
    an edge, which is exactly the shape the old walk could not see.
    """
    cursor = user_db.execute(
        "INSERT INTO subject_nodes "
        "(exam_context, name, level_type, parent_id, sort_order, status) "
        "VALUES ('USMLE', ?, 'Topic', NULL, 0, 'active')",
        (name,),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _status(user_db, node_id: int) -> str:
    return user_db.fetchone(
        "SELECT status FROM subject_nodes WHERE id = ?", (node_id,)
    )['status']


def _edge_exists(user_db, parent_id: int, child_id: int) -> bool:
    return user_db.fetchone(
        "SELECT 1 FROM subject_edges WHERE parent_id = ? AND child_id = ?",
        (parent_id, child_id),
    ) is not None


def _roots(user_db) -> set:
    return {n.id for n in user_db.get_subject_hierarchy("USMLE")}


def _children_ids(user_db, parent_id: int) -> set:
    return {n.id for n in user_db.get_subject_hierarchy("USMLE", parent_id)}


def _session(user_db) -> int:
    row = user_db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = 'USMLE'"
    )
    if row is None:
        row_id = user_db.execute(
            "INSERT INTO exam_contexts (user_id, exam_name, exam_description) "
            "VALUES (?, 'USMLE', 'Test')",
            (user_db.user_id,),
        ).lastrowid
    else:
        row_id = row['id']
    cursor = user_db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) VALUES (?, 'S', ?, ?, 1, 1)",
        (user_db.user_id, date.today().isoformat(), row_id),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _entry(user_db, session_id, subject_id, primary_parent_id=None, order=1) -> int:
    cursor = user_db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, 'A', 'B')",
        (session_id, order),
    )
    entry_id = cursor.lastrowid
    user_db.execute(
        "INSERT INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type, primary_parent_id) "
        "VALUES (?, ?, 'primary', ?)",
        (entry_id, subject_id, primary_parent_id),
    )
    user_db.conn.commit()
    return entry_id


def _shared_and_exclusive(user_db):
    """Build the standard shape; returns (pdel, qkeep, shared, exclusive)."""
    pdel = _node(user_db, "Pdel")
    qkeep = _node(user_db, "Qkeep")
    shared = _node(user_db, "Shared")
    exclusive = _node(user_db, "Exclusive")
    user_db.add_edge(pdel, shared, is_primary=True)
    user_db.add_edge(qkeep, shared, is_primary=False)
    user_db.add_edge(pdel, exclusive, is_primary=True)
    return pdel, qkeep, shared, exclusive


# ------------------------------------------------- decision 1: detach, don't delete


def test_edge_only_child_is_reached_at_all(user_db):
    """The original defect: the walk read ``subject_nodes.parent_id``.

    Every link here is an edge and nothing else, so under the old walk
    ``Exclusive`` was simply never visited — it stayed active and became
    unreachable. Asserting it is archived is asserting the walk found it.
    """
    pdel, _qkeep, _shared, exclusive = _shared_and_exclusive(user_db)

    user_db.delete_subject_subtree(pdel)

    assert _status(user_db, exclusive) == 'archived'


def test_shared_child_survives_with_no_orphan_rows(user_db):
    """Decision 1, and the corollary in casualty 1.

    ``Shared`` keeps a parent, so it is not deleted — and the edge from
    the deleted parent has to *go*, because a surviving edge from an
    archived parent is precisely what made the old orphan invisible.
    """
    pdel, qkeep, shared, _exclusive = _shared_and_exclusive(user_db)

    user_db.delete_subject_subtree(pdel)

    assert _status(user_db, shared) == 'active'
    assert not _edge_exists(user_db, pdel, shared), (
        "the edge from the deleted parent survived — this is the row that "
        "makes a child invisible rather than merely relocated"
    )
    assert _edge_exists(user_db, qkeep, shared)
    # Visible where it should be, and only there.
    assert shared in _children_ids(user_db, qkeep)
    assert shared not in _roots(user_db)


def test_shared_child_keeps_the_target_out_of_its_parent_list(user_db):
    """Casualty 2 — ``get_parents`` had no status filter.

    Nothing at all should name the deleted subject as a parent: the edge
    is gone here, but the filter is what protects the cases where an edge
    legitimately survives (an archived node's own parents, kept for
    restore).
    """
    pdel, qkeep, shared, _exclusive = _shared_and_exclusive(user_db)
    assert {p.parent_id for p in user_db.get_parents(shared)} == {pdel, qkeep}

    user_db.delete_subject_subtree(pdel)

    assert {p.parent_id for p in user_db.get_parents(shared)} == {qkeep}


def test_get_parents_filters_an_archived_parent_even_with_a_live_edge(user_db):
    """The filter, isolated from the delete that motivated it."""
    parent = _node(user_db, "Parent")
    child = _node(user_db, "Child")
    user_db.add_edge(parent, child, is_primary=True)
    user_db.execute(
        "UPDATE subject_nodes SET status = 'archived' WHERE id = ?", (parent,)
    )
    user_db.conn.commit()

    assert _edge_exists(user_db, parent, child)
    assert user_db.get_parents(child) == []


# ------------------------------------------------- decision 2: delete or promote


def test_exclusive_child_is_deleted_when_not_promoted(user_db):
    pdel, _qkeep, _shared, exclusive = _shared_and_exclusive(user_db)

    result = user_db.delete_subject_subtree(pdel, promote_children=False)

    assert _status(user_db, exclusive) == 'archived'
    assert {item['id'] for item in result['archived']} == {pdel, exclusive}
    assert result['promoted'] == []


def test_exclusive_child_is_promoted_to_root_when_asked(user_db):
    pdel, _qkeep, _shared, exclusive = _shared_and_exclusive(user_db)

    result = user_db.delete_subject_subtree(pdel, promote_children=True)

    assert _status(user_db, exclusive) == 'active'
    assert exclusive in _roots(user_db), (
        "a promoted child must have no parent edge left, or it renders "
        "nowhere: not a root, and not under anything visible"
    )
    assert {item['id'] for item in result['promoted']} == {exclusive}
    assert {item['id'] for item in result['archived']} == {pdel}


def test_promoting_carries_the_child_s_own_exclusive_descendants(user_db):
    """Decision 2: the choice is only ever asked about *direct* children.

    A grandchild is not offered a choice — it follows its parent, because
    its parent survives and so its own parent edge survives.
    """
    pdel, _qkeep, _shared, exclusive = _shared_and_exclusive(user_db)
    grandchild = _node(user_db, "Grandchild")
    user_db.add_edge(exclusive, grandchild, is_primary=True)

    user_db.delete_subject_subtree(pdel, promote_children=True)

    assert _status(user_db, grandchild) == 'active'
    assert grandchild in _children_ids(user_db, exclusive)
    assert grandchild not in _roots(user_db)


def test_not_promoting_takes_the_whole_exclusive_subtree(user_db):
    pdel, _qkeep, _shared, exclusive = _shared_and_exclusive(user_db)
    grandchild = _node(user_db, "Grandchild")
    user_db.add_edge(exclusive, grandchild, is_primary=True)

    user_db.delete_subject_subtree(pdel, promote_children=False)

    assert _status(user_db, grandchild) == 'archived'


def test_a_node_reachable_by_two_paths_inside_the_subtree_is_archived(user_db):
    """Why the cascade is a fixpoint and not a recursive walk.

    ``Pdel → A → X`` and ``Pdel → B → X``. Archiving ``A`` does not orphan
    ``X`` — ``B`` still holds it — so a depth-first walk that archived
    ``X`` on the way through ``A`` would be deciding on stale information.
    ``X`` only becomes an orphan after *both* ``A`` and ``B`` are gone,
    which no single pass can know.
    """
    pdel = _node(user_db, "Pdel")
    a = _node(user_db, "A")
    b = _node(user_db, "B")
    x = _node(user_db, "X")
    user_db.add_edge(pdel, a, is_primary=True)
    user_db.add_edge(pdel, b, is_primary=True)
    user_db.add_edge(a, x, is_primary=True)
    user_db.add_edge(b, x, is_primary=False)

    result = user_db.delete_subject_subtree(pdel)

    assert {item['id'] for item in result['archived']} == {pdel, a, b, x}
    assert _status(user_db, x) == 'archived'


def test_a_deep_node_held_from_outside_the_subtree_survives(user_db):
    """Decision 1 applies at any depth, not just to direct children."""
    pdel = _node(user_db, "Pdel")
    outside = _node(user_db, "Outside")
    mid = _node(user_db, "Mid")
    deep = _node(user_db, "Deep")
    user_db.add_edge(pdel, mid, is_primary=True)
    user_db.add_edge(mid, deep, is_primary=True)
    user_db.add_edge(outside, deep, is_primary=False)

    user_db.delete_subject_subtree(pdel)

    assert _status(user_db, mid) == 'archived'
    assert _status(user_db, deep) == 'active'
    assert deep in _children_ids(user_db, outside)
    assert not _edge_exists(user_db, mid, deep)


# ------------------------------------------------- decision 3: null the orphaned context


def test_orphaned_primary_parent_id_is_nulled(user_db):
    pdel, _qkeep, shared, _exclusive = _shared_and_exclusive(user_db)
    session = _session(user_db)
    entry = _entry(user_db, session, shared, primary_parent_id=pdel)

    user_db.delete_subject_subtree(pdel)

    row = user_db.fetchone(
        "SELECT primary_parent_id FROM entry_subject_mappings "
        "WHERE question_entry_id = ?",
        (entry,),
    )
    assert row['primary_parent_id'] is None


def test_the_entry_that_used_to_leave_every_rollup_is_counted_again(user_db):
    """The casualty nobody had noticed, and the reason this is Priority/High.

    The entry is pinned to ``Pdel``. §5.4 says a pinned entry rolls up
    through *only* that parent's ancestors, so once ``Pdel`` is archived
    and in no scope set, the entry rolls up **nowhere**: it stays in the
    entry browser and silently leaves every analytics total.

    Nulling the pin (decision 3) drops it into §5.4's NULL branch, where
    it rolls up through every ancestor of its leaf — so it reappears under
    ``Qkeep``, the parent that survived. Totals tick *up*, which is
    visible and recoverable, instead of down and invisible.
    """
    pdel, qkeep, shared, _exclusive = _shared_and_exclusive(user_db)
    session = _session(user_db)
    entry = _entry(user_db, session, shared, primary_parent_id=pdel)

    # Before: correctly scoped away from Qkeep, because the student said
    # they meant Pdel.
    before = {e.id for e in user_db.get_entries_by_subject(qkeep)}
    assert entry not in before

    user_db.delete_subject_subtree(pdel)

    after = {e.id for e in user_db.get_entries_by_subject(qkeep)}
    assert entry in after, (
        "the entry left every rollup: its pinned parent is archived, so no "
        "scope set contains it and no surviving ancestor counts it"
    )


def test_an_unpinned_entry_on_a_shared_child_is_untouched(user_db):
    """Only the *orphaned* context is nulled; NULL rows stay NULL and
    pins at surviving parents stay put."""
    pdel, qkeep, shared, _exclusive = _shared_and_exclusive(user_db)
    session = _session(user_db)
    unpinned = _entry(user_db, session, shared, primary_parent_id=None, order=1)
    pinned_elsewhere = _entry(user_db, session, shared, primary_parent_id=qkeep, order=2)

    user_db.delete_subject_subtree(pdel)

    rows = {
        r['question_entry_id']: r['primary_parent_id']
        for r in user_db.fetchall(
            "SELECT question_entry_id, primary_parent_id FROM entry_subject_mappings"
        )
    }
    assert rows[unpinned] is None
    assert rows[pinned_elsewhere] == qkeep


# ------------------------------------------------- decision 4: the delete batch


def test_delete_is_stamped_with_a_batch_id_and_journalled(user_db):
    """Decision 4's schema half. Restore (#37) consumes this; nothing
    reads it yet, which is why only its presence is asserted."""
    pdel, _qkeep, shared, exclusive = _shared_and_exclusive(user_db)
    session = _session(user_db)
    _entry(user_db, session, shared, primary_parent_id=pdel)

    result = user_db.delete_subject_subtree(pdel)
    batch_id = result['batch_id']

    assert batch_id
    batch = user_db.fetchone(
        "SELECT * FROM subject_delete_batches WHERE id = ?", (batch_id,)
    )
    assert batch['root_node_id'] == pdel
    assert batch['root_node_name'] == 'Pdel'

    stamped = {
        r['id']
        for r in user_db.fetchall(
            "SELECT id FROM subject_nodes WHERE deleted_batch_id = ?", (batch_id,)
        )
    }
    assert stamped == {pdel, exclusive}

    kinds = [
        r['item_type']
        for r in user_db.fetchall(
            "SELECT item_type FROM subject_delete_batch_items WHERE batch_id = ?",
            (batch_id,),
        )
    ]
    assert kinds.count('node_archived') == 2
    assert kinds.count('edge_removed') == 1       # Pdel → Shared
    assert kinds.count('primary_parent_cleared') == 1


def test_the_journal_distinguishes_a_promoted_child_from_a_detached_one(user_db):
    """#37 re-attaches a shared child on restore but leaves a promoted one
    at the top level, and which of the two a node was is only knowable at
    delete time — so the journal has to record it, not re-derive it."""
    import json as _json

    pdel, _qkeep, shared, exclusive = _shared_and_exclusive(user_db)

    batch_id = user_db.delete_subject_subtree(pdel, promote_children=True)['batch_id']

    promoted_by_child = {
        row['subject_node_id']: _json.loads(row['payload'])['promoted']
        for row in user_db.fetchall(
            "SELECT subject_node_id, payload FROM subject_delete_batch_items "
            "WHERE batch_id = ? AND item_type = 'edge_removed'",
            (batch_id,),
        )
    }
    assert promoted_by_child == {exclusive: True, shared: False}


def test_the_journal_snapshots_the_edge_it_removed(user_db):
    """Restore must rebuild the edge as it was, not with defaults."""
    import json as _json

    pdel, _qkeep, shared, _exclusive = _shared_and_exclusive(user_db)
    edge = user_db.fetchone(
        "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
        (pdel, shared),
    )
    user_db.update_edge_relative_weight(edge['id'], 37.5, set_anchor=True)

    batch_id = user_db.delete_subject_subtree(pdel)['batch_id']

    payload = _json.loads(user_db.fetchone(
        "SELECT payload FROM subject_delete_batch_items "
        "WHERE batch_id = ? AND item_type = 'edge_removed'",
        (batch_id,),
    )['payload'])
    assert payload['is_primary'] is True
    assert payload['is_anchor'] is True
    assert payload['relative_weight'] == 37.5


def test_two_deletes_get_different_batch_ids(user_db):
    a = _node(user_db, "A")
    b = _node(user_db, "B")

    first = user_db.delete_subject_subtree(a)['batch_id']
    second = user_db.delete_subject_subtree(b)['batch_id']

    assert first != second


# ------------------------------------------------- decision 5: the preview


def test_preview_is_read_only(user_db):
    pdel, _qkeep, shared, exclusive = _shared_and_exclusive(user_db)

    user_db.get_subject_delete_preview(pdel)

    for node_id in (pdel, shared, exclusive):
        assert _status(user_db, node_id) == 'active'
    assert _edge_exists(user_db, pdel, shared)


def test_preview_classifies_direct_children(user_db):
    pdel, _qkeep, shared, exclusive = _shared_and_exclusive(user_db)

    preview = user_db.get_subject_delete_preview(pdel)

    assert preview['node_name'] == 'Pdel'
    assert [c['id'] for c in preview['exclusive_direct_children']] == [exclusive]
    assert [c['id'] for c in preview['shared_direct_children']] == [shared]


@pytest.mark.parametrize("promote", [False, True])
def test_preview_counts_match_what_the_delete_does(user_db, promote):
    """Acceptance: the modal must not promise a different set than the
    delete produces. Both come from the same planner; this is the test
    that keeps it that way."""
    pdel, _qkeep, shared, exclusive = _shared_and_exclusive(user_db)
    grandchild = _node(user_db, "Grandchild")
    user_db.add_edge(exclusive, grandchild, is_primary=True)
    session = _session(user_db)
    _entry(user_db, session, shared, primary_parent_id=pdel)

    preview = user_db.get_subject_delete_preview(pdel)
    predicted = preview['modes']['promote' if promote else 'delete']

    actual = user_db.delete_subject_subtree(pdel, promote_children=promote)

    for key in ('archived', 'detached', 'promoted', 'entries_unscoped'):
        assert predicted[key] == actual[key], f"preview drifted from reality on {key}"

    # And the prediction matches the database, not just the return value.
    archived_now = {
        r['id']
        for r in user_db.fetchall(
            "SELECT id FROM subject_nodes WHERE status = 'archived'"
        )
    }
    assert archived_now == {item['id'] for item in predicted['archived']}


def test_preview_of_a_leaf_promises_nothing_extra(user_db):
    leaf = _node(user_db, "Leaf")

    preview = user_db.get_subject_delete_preview(leaf)

    assert preview['direct_child_count'] == 0
    assert preview['exclusive_direct_children'] == []
    for mode in ('delete', 'promote'):
        plan = preview['modes'][mode]
        assert [item['id'] for item in plan['archived']] == [leaf]
        assert plan['detached'] == []
        assert plan['entries_unscoped'] == 0


def test_missing_node_raises(user_db):
    with pytest.raises(SubjectNodeError):
        user_db.plan_subject_delete(987654)
    with pytest.raises(SubjectNodeError):
        user_db.get_subject_delete_preview(987654)


# ------------------------------------- #57: re-deleting an archived node


def _batch_ids(user_db) -> set:
    return {
        r['id'] for r in user_db.fetchall("SELECT id FROM subject_delete_batches")
    }


def test_deleting_an_already_archived_node_creates_no_batch(user_db):
    """Issue #57, item 2. Hygiene, not a guard.

    A second delete of an already-archived node opened a batch and
    journalled an operation that archived nothing, so
    ``subject_delete_batches`` collected empty rows that restore (#37)
    would offer the user and then undo nothing with. No UI path reaches
    this — the tree renders only active nodes and the bridge's
    ``get_subject_node`` lookup is status-filtered — but
    ``src/web/js/import_export.js`` calls ``deleteSubjectNode`` in a loop
    over a list it built earlier, and a stale list gets here.

    What this deliberately is **not**: a guard against re-stamping
    ``deleted_batch_id``. The owner settled on 2026-09-14 that a second
    delete of an *active* node re-stamping it is correct — the later
    delete is the more recent statement of intent — and that the
    reporting belongs in #37's restore. The gate is the target's own
    ``status`` and nothing else.
    """
    leaf = _node(user_db, "Leaf")
    first = user_db.delete_subject_subtree(leaf)
    before = _batch_ids(user_db)
    assert before == {first['batch_id']}

    result = user_db.delete_subject_subtree(leaf)

    assert _batch_ids(user_db) == before, "a second delete littered a batch row"
    assert result['batch_id'] is None
    assert result['already_archived'] is True
    assert result['archived'] == []
    assert result['detached'] == []
    assert result['promoted'] == []
    assert result['entries_unscoped'] == 0


def test_the_no_op_journals_nothing_and_touches_nothing(user_db):
    """The no-op must not write batch *items* either, nor re-stamp.

    ``deleted_batch_id`` keeps pointing at the batch that really archived
    the node, which is the one #37 replays; a no-op that re-stamped would
    orphan the node from its own journal entry.
    """
    pdel, _qkeep, shared, exclusive = _shared_and_exclusive(user_db)
    session = _session(user_db)
    _entry(user_db, session, shared, primary_parent_id=pdel)
    batch_id = user_db.delete_subject_subtree(pdel)['batch_id']
    items_before = user_db.fetchone(
        "SELECT COUNT(*) AS n FROM subject_delete_batch_items"
    )['n']

    user_db.delete_subject_subtree(pdel)

    assert user_db.fetchone(
        "SELECT COUNT(*) AS n FROM subject_delete_batch_items"
    )['n'] == items_before
    assert user_db.fetchone(
        "SELECT deleted_batch_id FROM subject_nodes WHERE id = ?", (pdel,)
    )['deleted_batch_id'] == batch_id
    assert _status(user_db, shared) == 'active'
    assert _status(user_db, exclusive) == 'archived'


def test_a_second_delete_of_an_active_node_still_runs(user_db):
    """The counterweight. #57 must not turn into a re-delete guard.

    ``Shared`` survives ``Pdel``'s delete because ``Qkeep`` still holds
    it, so deleting ``Qkeep`` afterwards is a legitimate, still-active
    delete and must journal its own batch. If this test ever fails
    alongside the two above passing, the no-op gate has widened from
    "the target is archived" to something that swallows real work.
    """
    pdel, qkeep, shared, _exclusive = _shared_and_exclusive(user_db)
    first = user_db.delete_subject_subtree(pdel)['batch_id']

    second = user_db.delete_subject_subtree(qkeep)

    assert second['batch_id'] not in (None, first)
    assert _status(user_db, qkeep) == 'archived'
    assert _status(user_db, shared) == 'archived'  # lost its last parent
    assert len(_batch_ids(user_db)) == 2


def test_the_no_op_still_rejects_a_node_that_does_not_exist(user_db):
    """Skipping the plan must not skip the existence check."""
    with pytest.raises(SubjectNodeError):
        user_db.delete_subject_subtree(987654)
