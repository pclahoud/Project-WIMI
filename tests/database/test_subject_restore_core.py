"""Restoring a delete batch undoes the operation, and says what it skipped (#37).

One test per decision, deliberately not consolidated -- the same discipline
`test_draft_policy_by_surface.py` uses, and for the same reason: each of these
is a separate promise, and a merged test that exercised three of them would go
green on a change that broke one.

The decisions under test, and where they come from:

* **Membership is read from `subject_delete_batch_items`, not from
  `subject_nodes.deleted_batch_id`** (owner, 2026-09-14). A node deleted,
  restored and deleted again has a *current* stamp naming the later batch while
  the journal still lists it under the first, and restoring the first must not
  resurrect it.
* **A partial restore must not read as a complete one** (same decision). The
  skipped count and its reason travel in the same sentence as the restored
  count.
* **A promoted child is not re-parented** (#37). Promotion was a choice; undoing
  it behind the student's back would surprise.
* **An edge rebuilds from its snapshot, not from defaults** (m018's payload
  exists for exactly this).
* **Restore refuses rather than producing an invisible node** (#260, hazard 1 in
  #37 comment #3520). This is the one with a real bug behind it, so it carries
  the longest test.
* **A newer `primary_parent_id` is not clobbered** (hazard 3).
* **An edge re-created by hand is not overwritten** (hazard 2,
  `UNIQUE(parent_id, child_id)`).
* **A batch owned by a dimension archive is not independently restorable**
  (hazard 4).

The listing is asserted separately: a batch drops out of it once restored, which
is what makes "already restored" derivable with no migration.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / 'src'))

from database import MasterDatabase, UserDatabase  # noqa: E402
from database.exceptions import SubjectRestoreError  # noqa: E402


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=pathlib.Path(tmpdir))
        user = master.create_user(username='restore', display_name='Probe',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='restore')
        db._ensure_phase2_schema()
        db._ensure_phase4_schema()
        db._ensure_phase7_schema()
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context(exam_name='Issue 37')


def _node(user_db, exam, name, parent_id=None, dimension_id=None):
    """Create a subject and return its **id**.

    ``create_subject_node`` returns a ``SubjectNode``; every API under test
    takes an id, so unwrapping here keeps the tests reading about ids.
    """
    # ``exam_context`` takes the exam **name**, which is what every
    # production caller passes. These fixtures stored the id until the
    # bridge tests built a row the production way and found that
    # `list_archived_batches`' exam scope matched nothing -- the parameter is
    # an id and the column holds a name. An unrepresentative fixture hid a
    # real scoping bug by agreeing with it.
    node = user_db.create_subject_node(
        exam_context=exam.exam_name, name=name, parent_id=parent_id,
        level_type='System', dimension_id=dimension_id,
    )
    return node.id if hasattr(node, 'id') else node


def _status(user_db, node_id):
    row = user_db.fetchone(
        'SELECT status, deleted_batch_id FROM subject_nodes WHERE id = ?',
        (node_id,))
    return (row['status'], row['deleted_batch_id']) if row else (None, None)


def _edge(user_db, parent_id, child_id):
    return user_db.fetchone(
        'SELECT * FROM subject_edges WHERE parent_id = ? AND child_id = ?',
        (parent_id, child_id))


def _entry_on(user_db, exam, subject_node_id, primary_parent_id):
    """An entry tagged on ``subject_node_id`` with a chosen parent context.

    Written with raw SQL, as the other analytics tests in this directory do:
    the entry form's route to this state goes through the bridge and TinyMCE,
    and what these tests need is the row.
    """
    session = user_db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) "
        "VALUES (?, ?, date('now'), ?, 1, 1)",
        (user_db.user_id, 'Restore probe', exam.id),
    ).lastrowid
    entry = user_db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, 1, 'A', 'B')",
        (session,),
    ).lastrowid
    mapping = user_db.execute(
        "INSERT INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type, primary_parent_id) "
        "VALUES (?, ?, 'primary', ?)",
        (entry, subject_node_id, primary_parent_id),
    ).lastrowid
    user_db.conn.commit()
    return mapping


def _primary_parent(user_db, mapping_id):
    row = user_db.fetchone(
        'SELECT primary_parent_id FROM entry_subject_mappings WHERE id = ?',
        (mapping_id,))
    return row['primary_parent_id'] if row else None


# ---------------------------------------------------------------------------
# The core promise
# ---------------------------------------------------------------------------


def test_restoring_a_batch_brings_back_every_node_it_archived(user_db, exam):
    """A parent and its exclusive child come back together."""
    parent = _node(user_db, exam, 'Cardiovascular System')
    child = _node(user_db, exam, 'Valvular Disease', parent_id=parent)

    batch = user_db.delete_subject_subtree(parent)['batch_id']
    assert _status(user_db, parent)[0] == 'archived'
    assert _status(user_db, child)[0] == 'archived'

    result = user_db.restore_subject_delete_batch(batch)

    assert result['restored'] is True
    assert _status(user_db, parent) == ('active', None)
    assert _status(user_db, child) == ('active', None)
    assert result['counts']['nodes_to_restore'] == 2
    assert result['summary'] == 'Restored 2 subjects.'


def test_a_restored_edge_keeps_the_weight_and_provenance_it_had(user_db, exam):
    """The journal snapshot exists so an edge rebuilds byte-identical.

    A restore that re-created the edge with schema defaults would silently
    reset the student's weight to NULL and its provenance to 'derived' --
    which is why m018 records the whole row rather than just the endpoints.
    """
    parent = _node(user_db, exam, 'Anatomy')
    shared = _node(user_db, exam, 'Histology', parent_id=parent)
    other = _node(user_db, exam, 'Pathology')
    user_db.add_edge(parent_id=other, child_id=shared)

    edge = _edge(user_db, parent, shared)
    user_db.update_edge_relative_weight(
        edge['id'], 17.5, set_anchor=True, source='user_explicit',
        reason='test',
    )
    before = dict(_edge(user_db, parent, shared))

    # `shared` has another parent, so deleting `parent` detaches rather than
    # archives it -- this is the edge_removed journal path.
    batch = user_db.delete_subject_subtree(parent)['batch_id']
    assert _edge(user_db, parent, shared) is None

    user_db.restore_subject_delete_batch(batch)
    after = dict(_edge(user_db, parent, shared))

    for field in ('is_primary', 'display_order', 'is_anchor',
                  'relative_weight', 'weight_source'):
        assert after[field] == before[field], f'{field} was not restored'


# ---------------------------------------------------------------------------
# The owner's decision: report what was skipped
# ---------------------------------------------------------------------------


def test_a_batch_whose_members_were_all_re_deleted_is_refused(user_db, exam):
    """What the owner's re-stamping decision actually reduces to today.

    The decision (2026-09-14) is that restoring an older batch must not
    resurrect a node deleted again afterwards, and must say so. **Measured on
    `master` at `eaa1db2`, the "some members re-deleted" state is
    unreachable**, because two later changes close it between them:

    * #57 made deleting an already-archived node a **no-op** returning
      `batch_id=None`, so the decision's "deleted a second time directly"
      cannot happen while the node is archived. Verified: the delete below
      reports `already_archived=True` and opens no batch.
    * Restore clears `deleted_batch_id` on **every** member at once, so after
      a restore the whole batch has zero claimants -- never a subset.

    So the reachable outcome is this one: the older batch has nothing left to
    restore and is refused with a sentence, rather than silently succeeding
    at nothing. Reported to the owner on the issue; `deleted_again` stays in
    the planner as defensive coverage and is exercised by the test below.
    """
    root = _node(user_db, exam, 'Root')
    a = _node(user_db, exam, 'A', parent_id=root)
    _node(user_db, exam, 'B', parent_id=root)

    first = user_db.delete_subject_subtree(root)['batch_id']

    # #57: re-deleting an archived node opens no batch at all.
    again = user_db.delete_subject_subtree(a)
    assert again['batch_id'] is None
    assert again['already_archived'] is True

    user_db.restore_subject_delete_batch(first)
    second = user_db.delete_subject_subtree(a)['batch_id']
    assert second != first

    # `first` now has no claimants: root and B are active, A names `second`.
    plan = user_db.plan_batch_restore(first)
    assert plan['restorable'] is False
    assert [b['code'] for b in plan['blocked']] == ['nothing_to_restore']


def test_a_node_re_stamped_into_a_later_batch_is_skipped_and_reported(
    user_db, exam,
):
    """The owner's decision, against a state built directly.

    The previous test measures that no public sequence produces a *partly*
    re-stamped batch, so this one writes the stamp itself. That is deliberate
    and it is not a test of nothing: `plan_batch_restore` reads membership
    from `subject_delete_batch_items` and the stamp from `subject_nodes`, and
    this is the only assertion that those two disagreeing is handled the way
    the owner asked -- restore the rest, report this one, name the reason.

    If a future change reopens the path (#38's purge, or making hazard 1 a
    per-node skip rather than a refusal), this is the test that already
    covers it.
    """
    root = _node(user_db, exam, 'Root')
    a = _node(user_db, exam, 'A', parent_id=root)
    b = _node(user_db, exam, 'B', parent_id=root)

    batch = user_db.delete_subject_subtree(root)['batch_id']
    # Re-stamp A alone, as a later delete would have done before #57.
    user_db.execute(
        "UPDATE subject_nodes SET deleted_batch_id = 'a-later-batch' "
        "WHERE id = ?", (a,))

    plan = user_db.plan_batch_restore(batch)
    a_entry = next(n for n in plan['nodes'] if n['id'] == a)
    b_entry = next(n for n in plan['nodes'] if n['id'] == b)
    assert a_entry['restore'] is False
    assert a_entry['skip_reason'] == 'deleted_again'
    assert b_entry['restore'] is True

    result = user_db.restore_subject_delete_batch(batch)
    assert _status(user_db, b)[0] == 'active'
    assert _status(user_db, a)[0] == 'archived'
    assert result['summary'].startswith('Restored 2 of 3 subjects.')
    assert 'deleted again later' in result['summary']


def test_membership_comes_from_the_journal_not_the_current_stamp(user_db, exam):
    """The negative control for the test above.

    If the planner read `subject_nodes.deleted_batch_id` instead of the
    journal, a node re-stamped into a later batch would be simply *absent*
    from the plan rather than present-and-skipped -- and the student would be
    told nothing about it. Absence and refusal look identical in a count and
    opposite in a report.
    """
    root = _node(user_db, exam, 'Root')
    a = _node(user_db, exam, 'A', parent_id=root)

    batch = user_db.delete_subject_subtree(root)['batch_id']
    user_db.execute(
        "UPDATE subject_nodes SET deleted_batch_id = 'elsewhere' WHERE id = ?",
        (a,))

    plan = user_db.plan_batch_restore(batch)
    assert a in [n['id'] for n in plan['nodes']], (
        'the re-stamped node must appear in the plan so it can be reported'
    )


# ---------------------------------------------------------------------------
# Promotion is a choice restore does not undo (#37)
# ---------------------------------------------------------------------------


def test_a_promoted_child_is_not_re_parented(user_db, exam):
    """Promotion created a fact the user chose."""
    parent = _node(user_db, exam, 'Parent')
    child = _node(user_db, exam, 'Child', parent_id=parent)

    batch = user_db.delete_subject_subtree(parent, promote_children=True)['batch_id']
    assert _status(user_db, child)[0] == 'active', 'promotion keeps it active'
    assert _edge(user_db, parent, child) is None

    plan = user_db.plan_batch_restore(batch)
    edge_entry = next(e for e in plan['edges'] if e['child_id'] == child)
    assert edge_entry['restore'] is False
    assert edge_entry['skip_reason'] == 'promoted'

    user_db.restore_subject_delete_batch(batch)
    assert _status(user_db, parent)[0] == 'active'
    assert _edge(user_db, parent, child) is None, (
        'restore must not silently re-parent a promoted child'
    )


# ---------------------------------------------------------------------------
# Hazard 1 (#260): never restore into invisibility
# ---------------------------------------------------------------------------


def test_a_node_whose_only_parent_is_archived_comes_back_visible(user_db, exam):
    """#260: the predicate was fixed, so this is no longer a refusal.

    The chain that reaches it:

    1. `C` under `P`, both active.
    2. Delete `C` -- the edge survives, because #15 removes
       archived-parent-to-*surviving*-child edges and `P` is still active.
    3. Delete `P` -- the edge survives again, because `C` is not surviving.
    4. Restore `C`'s batch -> `C` active, incoming edge, archived parent.

    Under the old "no incoming edge at all" root predicate that node rendered
    nowhere, so this module refused the restore. #260 aligned all three
    root-finding queries on "no incoming edge *from an active parent*", so it
    renders at the top level instead and the restore is allowed -- with a note
    saying where it went.
    """
    p = _node(user_db, exam, 'Parent')
    c = _node(user_db, exam, 'Child', parent_id=p)

    c_batch = user_db.delete_subject_subtree(c)['batch_id']
    assert _edge(user_db, p, c) is not None, (
        'precondition: the edge survives a child-only delete'
    )
    user_db.delete_subject_subtree(p)
    assert _edge(user_db, p, c) is not None, (
        'precondition: it survives the parent delete too, because the child '
        'was not surviving'
    )

    plan = user_db.plan_batch_restore(c_batch)
    assert plan['restorable'] is True, plan['blocked']
    codes = [n['code'] for n in plan['notes']]
    assert 'will_appear_at_top_level' in codes
    message = next(n['message'] for n in plan['notes']
                   if n['code'] == 'will_appear_at_top_level')
    assert 'Parent' in message, 'the note must name the archived parent'

    user_db.restore_subject_delete_batch(c_batch)
    assert _status(user_db, c)[0] == 'active'

    # The load-bearing half: it is actually reachable in the tree now.
    roots = [n.name for n in user_db.get_subject_hierarchy(exam.exam_name)]
    assert 'Child' in roots, (
        'a node whose only parent is archived must render at the top level, '
        'not vanish (#260)'
    )


def test_restoring_the_parent_afterwards_re_attaches_the_child(user_db, exam):
    """The payoff of #260's option 1, and the reason the edge is left alone.

    Because restore never deleted the dangling edge, bringing the parent back
    puts the child underneath it again **with no journal replay at all** --
    the edge was there the whole time. The alternative design (delete the
    edge on restore, mirroring #15) would have made this impossible.
    """
    p = _node(user_db, exam, 'Parent')
    c = _node(user_db, exam, 'Child', parent_id=p)

    c_batch = user_db.delete_subject_subtree(c)['batch_id']
    p_batch = user_db.delete_subject_subtree(p)['batch_id']

    user_db.restore_subject_delete_batch(c_batch)
    assert 'Child' in [n.name for n in user_db.get_subject_hierarchy(exam.exam_name)]

    user_db.restore_subject_delete_batch(p_batch)

    roots = [n.name for n in user_db.get_subject_hierarchy(exam.exam_name)]
    assert roots == ['Parent'], f'Child should be under Parent again, got {roots}'
    children = [
        n.name for n in user_db.get_subject_hierarchy(exam.exam_name, parent_id=p)
    ]
    assert children == ['Child']
    assert _edge(user_db, p, c) is not None


def test_a_node_with_no_incoming_edge_is_a_legitimate_root(user_db, exam):
    """A top-level subject restores with no note and no fuss."""
    root = _node(user_db, exam, 'Standalone')
    batch = user_db.delete_subject_subtree(root)['batch_id']

    plan = user_db.plan_batch_restore(batch)
    assert plan['restorable'] is True, plan['blocked']
    assert plan['notes'] == [], 'nothing to warn about for a plain root'
    user_db.restore_subject_delete_batch(batch)
    assert _status(user_db, root)[0] == 'active'


# ---------------------------------------------------------------------------
# Hazard 2: the student's own edge wins
# ---------------------------------------------------------------------------


def test_an_edge_that_already_exists_again_is_skipped_not_re_inserted(user_db, exam):
    """`UNIQUE(parent_id, child_id)` -- report it, never raise from an INSERT.

    The delete removed the edge from the archived parent to its surviving
    shared child. If that row exists again by the time the batch is restored,
    re-inserting it violates the unique constraint. Per #66 2.2's rule a
    collision the planner cannot resolve is a plan error with a sentence, not
    an `IntegrityError` from three frames down -- and here it resolves to
    "keep whatever is there now".

    `add_edge` is used to re-create it because that is the API an import or a
    plugin reaches for and it does not filter on parent status. The tree
    editor cannot offer this (it renders no archived parent), which is exactly
    why the guard is worth having: the reachable paths are the ones nobody is
    looking at.
    """
    parent = _node(user_db, exam, 'Parent')
    shared = _node(user_db, exam, 'Shared', parent_id=parent)
    other = _node(user_db, exam, 'Other')
    user_db.add_edge(parent_id=other, child_id=shared)

    batch = user_db.delete_subject_subtree(parent)['batch_id']
    assert _edge(user_db, parent, shared) is None, (
        'precondition: the archived-parent to surviving-child edge is removed'
    )

    # Re-create it while the parent is still archived.
    user_db.add_edge(parent_id=parent, child_id=shared)
    mine = dict(_edge(user_db, parent, shared))

    plan = user_db.plan_batch_restore(batch)
    edge_entry = next(e for e in plan['edges'] if e['child_id'] == shared)
    assert edge_entry['restore'] is False
    assert edge_entry['skip_reason'] == 'edge_exists'

    # No IntegrityError, and the row that was already there is untouched.
    result = user_db.restore_subject_delete_batch(batch)
    assert result['restored'] is True
    assert dict(_edge(user_db, parent, shared))['id'] == mine['id']
    assert _status(user_db, parent)[0] == 'active'


# ---------------------------------------------------------------------------
# Hazard 3: a newer parent context is a deliberate choice
# ---------------------------------------------------------------------------


def test_a_cleared_parent_context_is_restored(user_db, exam):
    """#15 nulls `primary_parent_id` when its parent is archived; restore puts it back.

    Without this the entry stays in the NULL branch of the deep dive's filter
    forever -- rolling up through every ancestor again rather than the chain
    the student pinned it to.
    """
    p1 = _node(user_db, exam, 'Chain A')
    shared = _node(user_db, exam, 'Shared', parent_id=p1)
    p2 = _node(user_db, exam, 'Chain B')
    user_db.add_edge(parent_id=p2, child_id=shared)

    mapping = _entry_on(user_db, exam, shared, primary_parent_id=p1)

    batch = user_db.delete_subject_subtree(p1)['batch_id']
    assert _primary_parent(user_db, mapping) is None, (
        'precondition: #15 clears the context when its parent is archived'
    )

    user_db.restore_subject_delete_batch(batch)
    assert _primary_parent(user_db, mapping) == p1


def test_a_parent_context_chosen_since_is_not_overwritten(user_db, exam):
    """Hazard 3. A re-tag after the delete is the student's newer intent.

    The journal holds the value that was nulled, so an unconditional restore
    would silently replace a context the student picked afterwards -- the same
    shape as the owner's re-stamping decision, one table over. Skipped, and
    reported.
    """
    p1 = _node(user_db, exam, 'Chain A')
    shared = _node(user_db, exam, 'Shared', parent_id=p1)
    p2 = _node(user_db, exam, 'Chain B')
    user_db.add_edge(parent_id=p2, child_id=shared)

    mapping = _entry_on(user_db, exam, shared, primary_parent_id=p1)
    batch = user_db.delete_subject_subtree(p1)['batch_id']

    # The student re-pins the entry to the surviving chain.
    user_db.execute(
        'UPDATE entry_subject_mappings SET primary_parent_id = ? WHERE id = ?',
        (p2, mapping))
    user_db.conn.commit()

    plan = user_db.plan_batch_restore(batch)
    entry = next(m for m in plan['entry_mappings'] if m['mapping_id'] == mapping)
    assert entry['restore'] is False
    assert entry['skip_reason'] == 'mapping_reassigned'

    user_db.restore_subject_delete_batch(batch)
    assert _primary_parent(user_db, mapping) == p2, (
        'the newer choice must survive the restore'
    )


# ---------------------------------------------------------------------------
# Hazard 4: a dimension-owned batch is not independently restorable
# ---------------------------------------------------------------------------


def test_a_batch_owned_by_a_dimension_archive_is_refused(user_db, exam):
    """Restoring one tree of a multi-axis archive would re-create hazard 1.

    One dimension archive produces N subject batches (m024). Restoring one
    alone leaves active subjects inside an archived dimension, which nothing
    can reach -- so the refusal points at the dimension instead.
    """
    dimension = user_db.create_dimension(
        exam_id=exam.id, name='System', display_order=1, is_required=True)
    root = _node(user_db, exam, 'Cardiovascular',
                 dimension_id=dimension.id if hasattr(dimension, 'id') else dimension)

    result = user_db.archive_dimension(
        dimension.id if hasattr(dimension, 'id') else dimension)
    subject_batches = [b for b in result['subject_batch_ids']]
    assert subject_batches, 'the archive must have produced a subject batch'
    batch_id = subject_batches[0]
    if isinstance(batch_id, (tuple, list)):
        batch_id = batch_id[0]

    plan = user_db.plan_batch_restore(batch_id)
    assert plan['restorable'] is False
    assert plan['owned_by_dimension_batch'] == result['batch_id']
    codes = [b['code'] for b in plan['blocked']]
    assert 'owned_by_dimension_batch' in codes
    message = next(b['message'] for b in plan['blocked']
                   if b['code'] == 'owned_by_dimension_batch')
    assert 'System' in message

    with pytest.raises(SubjectRestoreError):
        user_db.restore_subject_delete_batch(batch_id)
    assert _status(user_db, root)[0] == 'archived'


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------


def test_a_restored_batch_drops_out_of_the_listing(user_db, exam):
    """This is what makes "already restored" derivable with no migration.

    Restore clears `deleted_batch_id`, so a fully-resolved batch has no
    claimants left. A `restored_at` column would be a second source of truth
    for a fact the data already carries.
    """
    root = _node(user_db, exam, 'Gone')
    batch = user_db.delete_subject_subtree(root)['batch_id']

    listed = user_db.list_archived_batches(exam_context_id=exam.id)
    assert [b['batch_id'] for b in listed] == [batch]
    assert listed[0]['node_count'] == 1
    assert listed[0]['root_node_name'] == 'Gone'

    user_db.restore_subject_delete_batch(batch)
    assert user_db.list_archived_batches(exam_context_id=exam.id) == []


def test_a_batch_whose_nodes_moved_to_a_later_batch_is_not_listed(user_db, exam):
    """The listing must key on the stamp, not on the journal plus a status filter.

    Added because a mutation survived: swapping the join to
    `subject_delete_batch_items` while keeping `n.status = 'archived'` passed
    every other test in this file, so the stamp was doing work nothing
    asserted. The two readings differ exactly here.

    After the sequence below, batch1's journal still lists A -- and A is still
    archived, just under a *later* batch. A journal-driven listing would
    therefore offer batch1 in the panel, and restoring it would be refused as
    `nothing_to_restore`: an entry a student can click and get nowhere with.
    Keying on `deleted_batch_id` makes it absent, which is the truth.
    """
    root = _node(user_db, exam, 'Root')
    a = _node(user_db, exam, 'A', parent_id=root)
    _node(user_db, exam, 'B', parent_id=root)

    first = user_db.delete_subject_subtree(root)['batch_id']
    user_db.restore_subject_delete_batch(first)
    second = user_db.delete_subject_subtree(a)['batch_id']

    listed = {b['batch_id'] for b in user_db.list_archived_batches(
        exam_context_id=exam.id)}
    assert second in listed, 'the later batch is the restorable one'
    assert first not in listed, (
        'the older batch has no archived node still naming it and must not '
        'be offered'
    )


def test_the_listing_is_scoped_to_one_exam(user_db, exam):
    """The exam scope has to actually scope, and it needs a name not an id.

    `subject_nodes.exam_context` holds the exam **name** while
    `dimension_delete_batches.exam_id` holds the id, so the two halves of the
    listing need different values for one scope and `list_archived_batches`
    resolves the id to a name for the subject half. Comparing the id straight
    against the column matched nothing -- a bug that survived Wave 1 because
    its fixtures stored the id in that column and so agreed with it.

    Two exams with a deletion each is the only shape that catches both
    failure modes: returning nothing (the original bug) and returning
    everything (a scope dropped altogether).
    """
    mine = _node(user_db, exam, 'Mine')
    my_batch = user_db.delete_subject_subtree(mine)['batch_id']

    other_exam = user_db.create_exam_context(exam_name='Some Other Exam')
    theirs = user_db.create_subject_node(
        exam_context=other_exam.exam_name, name='Theirs', level_type='System')
    other_batch = user_db.delete_subject_subtree(
        theirs.id if hasattr(theirs, 'id') else theirs)['batch_id']

    assert [b['batch_id'] for b in user_db.list_archived_batches(
        exam_context_id=exam.id)] == [my_batch]
    assert [b['batch_id'] for b in user_db.list_archived_batches(
        exam_context_id=other_exam.id)] == [other_batch]
    both = {b['batch_id'] for b in user_db.list_archived_batches()}
    assert both == {my_batch, other_batch}, 'unscoped must return both'


def test_the_listing_says_what_the_deleted_root_was_under(user_db, exam):
    """#37 asks the panel to read "was under Cardiovascular System"."""
    parent = _node(user_db, exam, 'Cardiovascular System')
    child = _node(user_db, exam, 'Valvular Disease', parent_id=parent)

    user_db.delete_subject_subtree(child)
    listed = user_db.list_archived_batches(exam_context_id=exam.id)

    assert len(listed) == 1
    assert [p['name'] for p in listed[0]['parents']] == ['Cardiovascular System']


def test_a_dimension_owned_batch_is_hidden_from_the_default_listing(user_db, exam):
    """One archive event must not read as several entries in the panel."""
    dimension = user_db.create_dimension(
        exam_id=exam.id, name='Task', display_order=1, is_required=True)
    dim_id = dimension.id if hasattr(dimension, 'id') else dimension
    _node(user_db, exam, 'Diagnosis', dimension_id=dim_id)
    result = user_db.archive_dimension(dim_id)

    # One archive event, one entry -- the dimension, not its subject batch.
    listed = user_db.list_archived_batches(exam_context_id=exam.id)
    assert len(listed) == 1
    assert listed[0]['kind'] == 'dimension'
    assert listed[0]['batch_id'] == result['batch_id']
    assert listed[0]['dimension_name'] == 'Task'
    assert listed[0]['tree_count'] == 1

    # The owned subject batch is reachable only when explicitly asked for.
    owned = [
        b for b in user_db.list_archived_batches(
            exam_context_id=exam.id, include_dimension_owned=True)
        if b['kind'] == 'subject'
    ]
    assert len(owned) == 1
    assert owned[0]['owned_by_dimension_batch'] == result['batch_id']


# ---------------------------------------------------------------------------
# Refusals that are not hazards
# ---------------------------------------------------------------------------


def test_an_unknown_batch_is_refused_with_a_sentence(user_db):
    plan = user_db.plan_batch_restore('nosuchbatch')
    assert plan['exists'] is False
    assert plan['restorable'] is False
    assert plan['blocked'][0]['code'] == 'unknown_batch'
    with pytest.raises(SubjectRestoreError):
        user_db.restore_subject_delete_batch('nosuchbatch')


def test_restoring_twice_is_refused_rather_than_silently_doing_nothing(
    user_db, exam,
):
    """A second restore has nothing to do, and must not report success.

    The #240 lesson: a call that reports `0 restored` alongside `success` is
    indistinguishable from one that worked.
    """
    root = _node(user_db, exam, 'Once')
    batch = user_db.delete_subject_subtree(root)['batch_id']
    user_db.restore_subject_delete_batch(batch)

    plan = user_db.plan_batch_restore(batch)
    assert plan['restorable'] is False
    assert plan['blocked'][0]['code'] == 'nothing_to_restore'
    with pytest.raises(SubjectRestoreError):
        user_db.restore_subject_delete_batch(batch)
