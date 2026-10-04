"""Restoring a dimension archive brings its trees back with it (#37 Wave 2).

A dimension archive is **one event and N subject batches** (m024): the
dimension row is parked and each root in it goes through
`delete_subject_subtree`. So restore has to unpark the row *and* replay
exactly the set `dimension_delete_batch_subjects` names -- #37 comment #2826's
*"restore the right set, not each one independently"*, which is why that table
is an explicit relation rather than a timestamp correlation.

Three things are specific to this level, and all three come from m024's own
parking scheme rather than from anything #37 anticipated:

* **The name is recovered from the journal, never from the parked row.**
  Archiving rewrites `name` to `name || ' (archived #' || id || ')'` because
  `UNIQUE(exam_id, name)` is checked against archived rows (#244). The journal
  INSERT runs before that UPDATE, so it holds the name the student chose.
  Stripping the suffix back off would be parsing our own formatting -- and
  would give the wrong answer for a dimension genuinely named that way, which
  is the negative control below.
* **No slot is reserved**, so restore appends a fresh `display_order` rather
  than reclaiming `-id`'s old position, which #211's reorder may have filled.
* **A new dimension may hold the name**, which is a plan error with a
  sentence rather than an `IntegrityError` from inside the UPDATE (#66 2.2).

One test per decision, not consolidated.
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
        user = master.create_user(username='dimrestore', display_name='Probe',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='dimrestore')
        db._ensure_phase2_schema()
        db._ensure_phase4_schema()
        db._ensure_phase7_schema()
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context(exam_name='Issue 37 Wave 2')


def _dim(user_db, exam, name, order):
    d = user_db.create_dimension(exam_id=exam.id, name=name,
                                 display_order=order, is_required=True)
    return d.id if hasattr(d, 'id') else d


def _node(user_db, exam, name, parent_id=None, dimension_id=None):
    n = user_db.create_subject_node(
        exam_context=exam.exam_name, name=name, parent_id=parent_id,
        level_type='System', dimension_id=dimension_id)
    return n.id if hasattr(n, 'id') else n


def _dim_row(user_db, dimension_id):
    return dict(user_db.fetchone(
        'SELECT id, name, display_order, status, archived_batch_id '
        'FROM exam_dimensions WHERE id = ?', (dimension_id,)))


def _status(user_db, node_id):
    row = user_db.fetchone(
        'SELECT status FROM subject_nodes WHERE id = ?', (node_id,))
    return row['status'] if row else None


# ---------------------------------------------------------------------------
# The core promise
# ---------------------------------------------------------------------------


def test_restoring_a_dimension_brings_back_its_trees(user_db, exam):
    """The whole event undone: the axis, its roots and their descendants."""
    dim = _dim(user_db, exam, 'System', 1)
    cardio = _node(user_db, exam, 'Cardiovascular', dimension_id=dim)
    valve = _node(user_db, exam, 'Valvular', parent_id=cardio, dimension_id=dim)
    renal = _node(user_db, exam, 'Renal', dimension_id=dim)

    batch = user_db.archive_dimension(dim)['batch_id']
    assert _dim_row(user_db, dim)['status'] == 'archived'
    assert all(_status(user_db, n) == 'archived' for n in (cardio, valve, renal))

    result = user_db.restore_dimension_delete_batch(batch)

    assert result['restored'] is True
    assert _dim_row(user_db, dim)['status'] == 'active'
    assert all(_status(user_db, n) == 'active' for n in (cardio, valve, renal))
    assert result['counts']['subject_batches_to_restore'] == 2  # two roots
    assert result['counts']['nodes_to_restore'] == 3


def test_restoring_a_dimension_recovers_the_name_the_student_chose(user_db, exam):
    """Not the parked spelling, and not by stripping a suffix off it."""
    dim = _dim(user_db, exam, 'System', 1)
    _node(user_db, exam, 'Cardiovascular', dimension_id=dim)

    batch = user_db.archive_dimension(dim)['batch_id']
    parked = _dim_row(user_db, dim)['name']
    assert parked != 'System', 'precondition: #244 parks the name'

    user_db.restore_dimension_delete_batch(batch)
    assert _dim_row(user_db, dim)['name'] == 'System'


def test_a_dimension_genuinely_named_like_a_parked_row_survives_a_round_trip(
    user_db, exam,
):
    """The negative control for reading the name from the journal.

    A restore that recovered the name by stripping `' (archived #N)'` off the
    parked spelling would pass the test above and corrupt this one -- the
    student's own name ends with the very suffix the parking scheme appends.
    """
    awkward = 'System (archived #1)'
    dim = _dim(user_db, exam, awkward, 1)
    _node(user_db, exam, 'Root', dimension_id=dim)

    batch = user_db.archive_dimension(dim)['batch_id']
    user_db.restore_dimension_delete_batch(batch)

    assert _dim_row(user_db, dim)['name'] == awkward


def test_a_restored_dimension_gets_a_fresh_order_not_its_old_slot(user_db, exam):
    """m024 reserves no slot, and #211's reorder owns 1..N over the active set.

    The archived row sits at `-id`. Another dimension may have taken position
    1 since, so restore appends instead of reclaiming, and the result must be
    a positive order that collides with nothing.
    """
    first = _dim(user_db, exam, 'System', 1)
    _node(user_db, exam, 'Root', dimension_id=first)
    batch = user_db.archive_dimension(first)['batch_id']
    assert _dim_row(user_db, first)['display_order'] == -first

    # Somebody else takes position 1 while it is away.
    second = _dim(user_db, exam, 'Task', 1)

    user_db.restore_dimension_delete_batch(batch)
    restored = _dim_row(user_db, first)
    assert restored['display_order'] > 0
    assert restored['display_order'] != _dim_row(user_db, second)['display_order']


def test_the_archived_batch_stamp_is_cleared_so_the_event_stops_being_listed(
    user_db, exam,
):
    """Same derivation as the subject side: no claimant, no listing entry."""
    dim = _dim(user_db, exam, 'System', 1)
    _node(user_db, exam, 'Root', dimension_id=dim)
    batch = user_db.archive_dimension(dim)['batch_id']

    listed = user_db.list_archived_batches(exam_context_id=exam.id)
    assert [b['batch_id'] for b in listed] == [batch]

    user_db.restore_dimension_delete_batch(batch)
    assert _dim_row(user_db, dim)['archived_batch_id'] is None
    assert user_db.list_archived_batches(exam_context_id=exam.id) == []


def test_restoring_a_dimension_makes_the_exam_multi_dimensional_again(
    user_db, exam,
):
    """`exam_uses_dimensions` is derived from a COUNT of active rows.

    Archiving the last dimension flips it false, which is what makes the tree
    editor fall back to its plain path (#210). Restore must flip it back, and
    it does so for free precisely because nothing caches it -- asserted so a
    future "optimisation" that stores the flag has to keep this true.
    """
    dim = _dim(user_db, exam, 'System', 1)
    _node(user_db, exam, 'Root', dimension_id=dim)
    assert user_db.exam_uses_dimensions(exam.id) is True

    batch = user_db.archive_dimension(dim)['batch_id']
    assert user_db.exam_uses_dimensions(exam.id) is False

    user_db.restore_dimension_delete_batch(batch)
    assert user_db.exam_uses_dimensions(exam.id) is True


# ---------------------------------------------------------------------------
# Refusals, each with a sentence
# ---------------------------------------------------------------------------


def test_a_name_taken_since_is_refused_with_a_sentence(user_db, exam):
    """`UNIQUE(exam_id, name)` -- a plan error, never an IntegrityError."""
    dim = _dim(user_db, exam, 'System', 1)
    _node(user_db, exam, 'Root', dimension_id=dim)
    batch = user_db.archive_dimension(dim)['batch_id']

    # The student creates a new axis under the freed name -- which #244 made
    # possible on purpose.
    _dim(user_db, exam, 'System', 2)

    plan = user_db.plan_dimension_batch_restore(batch)
    assert plan['restorable'] is False
    assert [b['code'] for b in plan['blocked']] == ['name_taken']
    assert 'System' in plan['blocked'][0]['message']

    with pytest.raises(SubjectRestoreError) as excinfo:
        user_db.restore_dimension_delete_batch(batch)
    assert 'System' in str(excinfo.value)
    assert _dim_row(user_db, dim)['status'] == 'archived', (
        'a refused restore changes nothing'
    )


def test_a_name_held_by_a_pre_244_archived_row_is_refused(user_db, exam):
    """The collision check has to see archived rows, and this is why.

    Added because a mutation survived: narrowing the check to
    `status = 'active'` passed every other test here, because an archived row
    normally holds a *parked* name (`X (archived #id)`) and so cannot collide
    with a plain one.

    **Rows archived before #244 are the exception.** #210 parked only
    `display_order` and left `name` untouched, which was the bug #244 fixed --
    so any database archived in that window holds archived rows carrying their
    original names. `UNIQUE(exam_id, name)` is enforced against archived rows,
    so restoring a dimension onto one of those names is an `IntegrityError`
    waiting in the UPDATE. That is what the `includes-archived` marker on the
    query is for.

    The legacy row is written directly, because the code that produced it no
    longer exists -- which is the only honest way to test against data a
    previous version wrote.
    """
    dim = _dim(user_db, exam, 'System', 1)
    _node(user_db, exam, 'Root', dimension_id=dim)
    batch = user_db.archive_dimension(dim)['batch_id']

    # A dimension archived under #210-but-pre-#244: order parked, name not.
    legacy = _dim(user_db, exam, 'System-legacy', 5)
    user_db.execute(
        "UPDATE exam_dimensions "
        "SET status = 'archived', display_order = -id, name = 'System' "
        "WHERE id = ?", (legacy,))
    user_db.conn.commit()

    plan = user_db.plan_dimension_batch_restore(batch)
    assert plan['restorable'] is False, (
        'an archived row holding the un-parked name still occupies it'
    )
    assert [b['code'] for b in plan['blocked']] == ['name_taken']
    assert plan['blocked'][0]['conflicting_dimension_id'] == legacy

    with pytest.raises(SubjectRestoreError):
        user_db.restore_dimension_delete_batch(batch)
    assert _dim_row(user_db, dim)['status'] == 'archived'


def test_restoring_twice_is_refused(user_db, exam):
    dim = _dim(user_db, exam, 'System', 1)
    _node(user_db, exam, 'Root', dimension_id=dim)
    batch = user_db.archive_dimension(dim)['batch_id']
    user_db.restore_dimension_delete_batch(batch)

    plan = user_db.plan_dimension_batch_restore(batch)
    assert plan['restorable'] is False
    assert plan['blocked'][0]['code'] == 'not_archived'
    with pytest.raises(SubjectRestoreError):
        user_db.restore_dimension_delete_batch(batch)


def test_an_unknown_dimension_batch_is_refused(user_db):
    plan = user_db.plan_dimension_batch_restore('nosuch')
    assert plan['exists'] is False
    assert plan['blocked'][0]['code'] == 'unknown_batch'
    with pytest.raises(SubjectRestoreError):
        user_db.restore_dimension_delete_batch('nosuch')


# ---------------------------------------------------------------------------
# The relation to Wave 1's ownership guard
# ---------------------------------------------------------------------------


def test_the_ownership_guard_is_released_only_for_the_owning_event(user_db, exam):
    """Hazard 4's guard must not be a boolean anyone can pass by accident.

    A subject batch owned by a dimension archive is refused on its own. The
    dimension restore releases that guard by *naming* the event it is acting
    for, so passing some other batch id leaves the refusal in place.
    """
    dim = _dim(user_db, exam, 'System', 1)
    _node(user_db, exam, 'Root', dimension_id=dim)
    result = user_db.archive_dimension(dim)
    dim_batch = result['batch_id']
    sub = result['subject_batch_ids'][0]
    sub_batch = sub[0] if isinstance(sub, (tuple, list)) else sub

    # Unqualified: refused.
    assert user_db.plan_batch_restore(sub_batch)['restorable'] is False

    # Named with an unrelated event: still refused.
    other = user_db.plan_batch_restore(
        sub_batch, as_part_of_dimension_batch='some-other-batch')
    assert other['restorable'] is False
    assert 'owned_by_dimension_batch' in [b['code'] for b in other['blocked']]

    # Named with its own event: allowed.
    mine = user_db.plan_batch_restore(
        sub_batch, as_part_of_dimension_batch=dim_batch)
    assert mine['restorable'] is True, mine['blocked']


def test_a_tree_re_deleted_since_is_skipped_and_the_dimension_still_restores(
    user_db, exam,
):
    """A sub-batch that cannot run must not strand the whole dimension.

    Refusing the event outright would leave the axis archived forever because
    one of its trees had been touched since -- strictly worse than restoring
    the rest and saying which one stayed behind. The skipped tree's subjects
    remain archived, and archived subjects inside an active dimension are an
    ordinary state.
    """
    dim = _dim(user_db, exam, 'System', 1)
    keep = _node(user_db, exam, 'Cardiovascular', dimension_id=dim)
    gone = _node(user_db, exam, 'Renal', dimension_id=dim)

    result = user_db.archive_dimension(dim)
    batch = result['batch_id']

    # Re-stamp one root's batch so its members look re-deleted, the same shape
    # Wave 1's `deleted_again` covers.
    user_db.execute(
        "UPDATE subject_nodes SET deleted_batch_id = 'a-later-batch' "
        "WHERE id = ?", (gone,))

    plan = user_db.plan_dimension_batch_restore(batch)
    assert plan['restorable'] is True, plan['blocked']
    assert plan['counts']['subject_batches_skipped'] == 1

    outcome = user_db.restore_dimension_delete_batch(batch)
    assert _dim_row(user_db, dim)['status'] == 'active'
    assert _status(user_db, keep) == 'active'
    assert _status(user_db, gone) == 'archived'
    assert 'could not be restored' in outcome['summary']
    assert 'Renal' in outcome['summary']


def test_a_refused_dimension_restore_rolls_back_the_whole_thing(user_db, exam):
    """One transaction: the dimension and its trees, or neither.

    A dimension active while its trees were still archived is reachable only
    by a part-way failure, and it is the state #210's cascade exists to
    prevent in the other direction.
    """
    dim = _dim(user_db, exam, 'System', 1)
    root = _node(user_db, exam, 'Root', dimension_id=dim)
    batch = user_db.archive_dimension(dim)['batch_id']
    _dim(user_db, exam, 'System', 2)  # steal the name

    with pytest.raises(SubjectRestoreError):
        user_db.restore_dimension_delete_batch(batch)

    assert _dim_row(user_db, dim)['status'] == 'archived'
    assert _status(user_db, root) == 'archived'
