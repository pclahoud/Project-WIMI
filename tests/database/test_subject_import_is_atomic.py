"""A subject import applies wholly or not at all (#239).

`apply_subject_import` used to wrap individual writes in four narrow
`self.transaction()` blocks with nothing spanning the operation, so a failure
midway left everything already run committed — some subjects renamed, some
created, the removal pass never reached.

Its docstring said so, and gave a reason that was **false by the time anyone
read it**:

> *"`BaseDatabase.transaction` commits rather than nesting a savepoint, so a
> failure midway leaves the work done so far committed … making it genuinely
> atomic is a change to `BaseDatabase`, not to import."*

`transaction()` has been re-entrant since **#95**, which landed five hours
after that sentence (`55a7fa4` 17:28, `2d64b5c` 22:48, both 2026-09-16) and
never updated it. Nesting works; the fix was always in import.

**Why the failure injection is at four different phases.** The apply has four
write phases plus removals, and they are ordered for correctness reasons #67
records — renames before adds, moves after adds, removals last. A single
injection point would prove one boundary rolls back and say nothing about the
others, and the phases each call different primitives (`create_subject_node`,
`add_edge`, `delete_subject_subtree`), which is exactly where a
savepoint-vs-commit mistake would hide.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase


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
def user_db(master_db):
    user = master_db.create_user(username='atomic_probe', display_name='Probe',
                                 user_types=['student'])
    db = UserDatabase(db_path=master_db.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    yield db
    db.close()


@pytest.fixture
def exam(user_db):
    user_db.create_exam_context(exam_name='Atomic Exam', exam_description='#239')
    return user_db.get_exam_context_by_name('Atomic Exam')


def _node(name, *, id=None, children=None):
    node = {'name': name}
    if id is not None:
        node['id'] = id
    if children:
        node['children'] = list(children)
    return node


def _snapshot(user_db, exam_name):
    """Every subject's name, status and parent — the whole observable tree."""
    return sorted(
        (row['name'], row['status'], row['import_id'])
        for row in user_db.fetchall(
            "SELECT name, status, import_id FROM subject_nodes "
            "WHERE exam_context = ?", (exam_name,))
    )


@pytest.fixture
def seeded(user_db, exam):
    """A tree the import will rename, add to, move and remove from."""
    user_db.apply_subject_import(exam.id, [
        _node('Alpha', id='a', children=[_node('Alpha Child', id='ac')]),
        _node('Beta', id='b'),
        _node('Doomed', id='d'),
    ])
    return exam


#: A file that exercises every phase against `seeded`: renames Alpha, adds
#: Gamma, moves Alpha Child under Beta, and drops Doomed.
def _busy_file():
    return [
        _node('Alpha Renamed', id='a'),
        _node('Beta', id='b', children=[_node('Alpha Child', id='ac')]),
        _node('Gamma', id='g'),
    ]


@pytest.mark.database
def test_the_busy_file_applies_when_nothing_fails(user_db, seeded):
    """Negative control, and it comes first deliberately.

    Every test below asserts that a failure changes nothing. If the apply
    silently did nothing at all they would all pass, so this pins that the
    file really does rename, add, move and remove.
    """
    before = _snapshot(user_db, seeded.exam_name)

    user_db.apply_subject_import(seeded.id, _busy_file())

    after = _snapshot(user_db, seeded.exam_name)
    assert after != before
    names = {name for name, status, _ in after if status == 'active'}
    assert 'Alpha Renamed' in names, 'the rename did not land'
    assert 'Gamma' in names, 'the add did not land'
    assert 'Doomed' not in names, 'the removal did not land'


@pytest.mark.database
@pytest.mark.parametrize('trip_on', [
    'UPDATE subject_nodes SET',      # phase 1, the rename
    'INSERT INTO subject_nodes',     # phase 2, the create
    'INSERT INTO subject_edges',     # phases 2/3, the parenting and the move
    'subject_delete_batches',        # removals, the journal
])
def test_a_failure_in_any_phase_leaves_the_tree_untouched(user_db, seeded, trip_on):
    """The guarantee, at four different phase boundaries.

    Each `trip_on` is SQL that only the named phase issues, so the injection
    lands inside that phase with earlier phases already written — which is
    precisely the state the old code committed.

    **Three of the four prove atomicity; the first does not, and that is
    correct.** Measured by reverting the spanning transaction: the
    `subject_nodes`, `subject_edges` and `subject_delete_batches` cases all
    fail against the old code, while `UPDATE subject_nodes SET` passes either
    way — it trips on phase 1, the very first write, so there is nothing
    earlier to leave behind. It is kept as the boundary case rather than
    dropped, and labelled so the parametrised list is not read as four
    independent proofs.
    """
    before = _snapshot(user_db, seeded.exam_name)
    real_execute = user_db.execute

    def failing_execute(sql, params=()):
        if trip_on in sql:
            raise sqlite3.OperationalError(f'injected failure at {trip_on!r}')
        return real_execute(sql, params)

    user_db.execute = failing_execute
    try:
        with pytest.raises(Exception):
            user_db.apply_subject_import(seeded.id, _busy_file())
    finally:
        user_db.execute = real_execute

    assert _snapshot(user_db, seeded.exam_name) == before, (
        f'a failure at {trip_on!r} left a partial import committed'
    )


@pytest.mark.database
def test_the_removal_journal_does_not_survive_a_rollback(user_db, seeded):
    """The journal is inside the transaction too.

    A `subject_delete_batches` row surviving a rolled-back import would leave
    #37 offering to restore a removal that never happened.
    """
    before = user_db.fetchone(
        'SELECT COUNT(*) AS n FROM subject_delete_batches')['n']
    real_execute = user_db.execute
    seen = {'batches': 0}

    def failing_execute(sql, params=()):
        # Removals run last, so nothing inside the transaction follows them --
        # an "after the removals" trigger never fires, which is how an earlier
        # version of this test passed by never raising at all. Failing on the
        # SECOND batch puts the injection *between* two removals, with the
        # first already archived and journalled.
        if 'INSERT INTO subject_delete_batches' in sql:
            seen['batches'] += 1
            if seen['batches'] == 2:
                raise sqlite3.OperationalError(
                    'injected failure between two removals')
        return real_execute(sql, params)

    user_db.execute = failing_execute
    try:
        # A file naming one new subject: everything seeded is absent from it,
        # so several removals run.
        with pytest.raises(Exception):
            user_db.apply_subject_import(seeded.id, [_node('Late', id='late')])
    finally:
        user_db.execute = real_execute

    assert seen['batches'] >= 2, (
        'the file did not produce two removals, so nothing was tested'
    )
    after = user_db.fetchone(
        'SELECT COUNT(*) AS n FROM subject_delete_batches')['n']
    assert after == before, 'a delete batch survived a rolled-back import'
    # And the first removal's archive is undone too, not just its journal row.
    assert all(status == 'active'
               for _, status, _ in _snapshot(user_db, seeded.exam_name)), (
        'a subject stayed archived after the import rolled back'
    )


@pytest.mark.database
def test_the_docstring_states_the_guarantee_it_now_has():
    """The false sentence is the thing that stopped this being fixed.

    A reader who trusted *"making it genuinely atomic is a change to
    `BaseDatabase`, not to import"* concluded the fix was out of reach.

    **This cannot be a pure absence check**, and an earlier version of this
    test wrongly tried to be one: the corrected docstring *quotes* the false
    sentence in order to retract it, so asserting the words are absent fails
    against the fix. Asserting the positive claim is the right shape — the
    retraction is allowed to name what it retracts.
    """
    import inspect

    from database.domains.subject_import import SubjectImportMixin

    doc = inspect.getdoc(SubjectImportMixin.apply_subject_import) or ''
    assert 'The whole apply is atomic' in doc, (
        'the docstring no longer states the guarantee'
    )
    assert 'Atomicity is best-effort' not in doc, (
        'the old claim is back as a claim, not as a quotation'
    )
    assert 're-entrant since #95' in doc, (
        'the reason the old claim was false should stay recorded'
    )
