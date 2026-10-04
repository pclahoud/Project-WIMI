"""Reordering dimensions applies wholly or not at all (#211).

Two defects lived in the same six lines of ``DimensionsBridgeMixin.reorderDimensions``,
and the first hid the second.

1. **A bare ``conn.commit()`` ran inside the bridge's transaction.**
   ``update_dimension`` ended with ``self.conn.commit()``, so the first
   iteration of the reorder loop committed the transaction the bridge had
   opened, and every later iteration ran in autocommit. This is the one
   failure ``BaseDatabase.transaction``'s docstring says it cannot defend
   against.

2. **Any real reorder raised ``IntegrityError`` on the first move.**
   ``exam_dimensions`` carries ``UNIQUE(exam_id, display_order)`` and SQLite
   checks a UNIQUE index **per row, as the statement runs** -- it has no
   deferred constraints. Assigning 1, 2, 3 one row at a time collides the
   moment a dimension moves into a slot another dimension still holds.

Because (1) had already committed whatever succeeded, a failure part-way
through was not rolled back: brute-forcing three-dimension layouts with gaps
in ``display_order`` found 72 half-write cases. The gaps are not hypothetical
-- ``delete_dimension`` is a hard DELETE and leaves one behind, and
``syncDimensions`` deletes removed dimensions in the loop immediately above
the reorder, in the same Save.

These tests drive the real ``reorder_dimensions`` against a real database
rather than asserting on source text, because the question is whether the
constraint is actually satisfied -- and the old code read perfectly.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from database import MasterDatabase, UserDatabase  # noqa: E402


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
    user = master_db.create_user(
        username='test_student', display_name='Test Student',
        user_types=['student'],
    )
    db = UserDatabase(
        db_path=master_db.ensure_user_database(user.id),
        user_id=user.id,
        username=user.username,
    )
    db._ensure_phase2_schema()
    db._ensure_phase7_schema()
    yield db
    db.close()


_EXAMS = iter(range(1, 10_000))


def _make_exam_with_dimensions(user_db, orders):
    """An exam whose dimensions sit at exactly ``orders``.

    Returns ``(exam_id, [dimension_id, ...])`` in the same sequence as
    ``orders``. The orders are passed straight through, so a test can build
    the gapped layouts a hard ``delete_dimension`` leaves behind.
    """
    exam = user_db.create_exam_context(exam_name=f'Exam {next(_EXAMS)}')
    dimension_ids = []
    for i, order in enumerate(orders):
        dimension_ids.append(user_db.create_dimension(
            exam_id=exam.id,
            name=f'Dimension {i + 1}',
            display_order=order,
        ))
    return exam.id, dimension_ids


def _orders(user_db, exam_id):
    """``{dimension_id: display_order}`` straight from the table."""
    return {
        row['id']: row['display_order']
        for row in user_db.fetchall(
            'SELECT id, display_order FROM exam_dimensions WHERE exam_id = ?',
            (exam_id,),
        )
    }


@pytest.mark.database
def test_moving_the_last_dimension_to_the_top(user_db):
    """The headline repro: three dimensions at 1, 2, 3, reordered to [3, 1, 2].

    This raised `UNIQUE constraint failed: exam_dimensions.exam_id,
    exam_dimensions.display_order` on the very first write.
    """
    exam_id, (d1, d2, d3) = _make_exam_with_dimensions(user_db, [1, 2, 3])

    user_db.reorder_dimensions(exam_id, [d3, d1, d2])

    assert _orders(user_db, exam_id) == {d3: 1, d1: 2, d2: 3}


@pytest.mark.database
def test_a_gapped_layout_reorders_without_a_half_write(user_db):
    """Orders (2, 3, 4) reordered to [2, 3, 1] -- the first of the 72 cases.

    The old code committed one write and then failed, leaving the table in a
    state that was neither the old order nor the new one.
    """
    exam_id, (d1, d2, d3) = _make_exam_with_dimensions(user_db, [2, 3, 4])

    user_db.reorder_dimensions(exam_id, [d2, d3, d1])

    assert _orders(user_db, exam_id) == {d2: 1, d3: 2, d1: 3}


@pytest.mark.database
@pytest.mark.parametrize('start', [[1, 2, 3], [2, 3, 4], [1, 5, 9], [3, 1, 2]])
@pytest.mark.parametrize('permutation', [(0, 1, 2), (2, 0, 1), (1, 2, 0),
                                         (2, 1, 0), (0, 2, 1), (1, 0, 2)])
def test_every_permutation_of_every_layout(user_db, start, permutation):
    """All 24 combinations, because the defect was permutation-dependent.

    Moving the third dimension up failed while leaving it where it was
    succeeded, so a single happy-path test would have passed against the
    broken code. The identity permutation is in here on purpose: it is the
    case the old loop handled, and it must keep working.
    """
    exam_id, dims = _make_exam_with_dimensions(user_db, start)
    new_order = [dims[i] for i in permutation]

    user_db.reorder_dimensions(exam_id, new_order)

    assert _orders(user_db, exam_id) == {
        dim: position for position, dim in enumerate(new_order, start=1)
    }


@pytest.mark.database
def test_a_negative_order_left_by_an_earlier_crash_still_reorders(user_db):
    """The offset is derived from the data, not assumed to be positive.

    A fixed offset would collide with the very rows it is moving out of the
    way. This is defensive rather than observed -- no crash is known to have
    left this state -- but the whole bug was a constraint nobody expected to
    fire, so the arithmetic should not have an untested branch.
    """
    exam_id, (d1, d2, d3) = _make_exam_with_dimensions(user_db, [1, 2, 3])
    with user_db.transaction():
        user_db.execute(
            'UPDATE exam_dimensions SET display_order = -7 WHERE id = ?', (d1,))

    user_db.reorder_dimensions(exam_id, [d2, d1, d3])

    assert _orders(user_db, exam_id) == {d2: 1, d1: 2, d3: 3}


@pytest.mark.database
def test_a_partial_list_is_refused_by_name(user_db):
    """Listing only some dimensions would collide again, by another route.

    The unlisted rows stay in the 1..N range being assigned into. Refusing
    with a message naming what is missing beats an IntegrityError from three
    frames down -- that was the original failure's whole problem.
    """
    exam_id, (d1, d2, d3) = _make_exam_with_dimensions(user_db, [1, 2, 3])

    with pytest.raises(ValueError) as caught:
        user_db.reorder_dimensions(exam_id, [d2, d1])

    message = str(caught.value)
    assert str(d3) in message, f'the refusal does not name the missing dimension: {message}'
    assert _orders(user_db, exam_id) == {d1: 1, d2: 2, d3: 3}, 'a refused reorder wrote something'


@pytest.mark.database
def test_a_foreign_dimension_is_refused(user_db):
    """A dimension from another exam must not be reordered into this one."""
    exam_a, (a1, a2) = _make_exam_with_dimensions(user_db, [1, 2])
    _, (b1,) = _make_exam_with_dimensions(user_db, [1])

    with pytest.raises(ValueError) as caught:
        user_db.reorder_dimensions(exam_a, [a1, a2, b1])

    assert str(b1) in str(caught.value)


@pytest.mark.database
def test_a_duplicate_in_the_list_is_refused(user_db):
    """Two slots for one dimension is a caller bug, not a reorder."""
    exam_id, (d1, d2, d3) = _make_exam_with_dimensions(user_db, [1, 2, 3])

    with pytest.raises(ValueError):
        user_db.reorder_dimensions(exam_id, [d1, d1, d2])


@pytest.mark.database
def test_the_reorder_rolls_back_as_one(user_db):
    """A failure inside the reorder leaves the original order intact.

    This is the half-write, tested directly. The reorder is forced to fail on
    its last write by making that dimension's row unreachable mid-flight; what
    matters is that the rows moved before it are not left committed.
    """
    exam_id, (d1, d2, d3) = _make_exam_with_dimensions(user_db, [1, 2, 3])
    before = _orders(user_db, exam_id)

    original_execute = user_db.execute
    calls = {'n': 0}

    def failing_execute(sql, params=()):
        if 'SET display_order = ? WHERE id = ?' in sql:
            calls['n'] += 1
            if calls['n'] == 3:
                raise sqlite3.OperationalError('injected failure on the last write')
        return original_execute(sql, params)

    user_db.execute = failing_execute
    try:
        with pytest.raises(sqlite3.OperationalError):
            user_db.reorder_dimensions(exam_id, [d3, d1, d2])
    finally:
        user_db.execute = original_execute

    assert _orders(user_db, exam_id) == before, (
        'a failed reorder left a partial write -- the parked orders or the '
        'first two moves survived'
    )


@pytest.mark.database
def test_update_dimension_no_longer_commits_its_caller(user_db):
    """The #211 half that is enforced by an absence.

    ``update_dimension`` used to end in a bare ``conn.commit()``. Called from
    inside an enclosing transaction it ended that transaction, so a later
    failure could not roll back the earlier work. A rollback here proves the
    commit is gone; a surviving row proves it is back.
    """
    exam_id, (d1, d2) = _make_exam_with_dimensions(user_db, [1, 2])

    with pytest.raises(RuntimeError):
        with user_db.transaction():
            user_db.update_dimension(dimension_id=d1, name='Renamed inside')
            raise RuntimeError('abandon the enclosing transaction')

    name = user_db.fetchall(
        'SELECT name FROM exam_dimensions WHERE id = ?', (d1,))[0]['name']
    assert name != 'Renamed inside', (
        'update_dimension committed from inside an enclosing transaction, so '
        'the rollback had nothing left to undo (#211)'
    )


@pytest.mark.database
def test_the_dimensions_domain_has_no_bare_commits(user_db):
    """No write in this module may commit on its own again.

    CLAUDE.md's transaction section names this module as the known exception;
    #210's archive cascade and #66's import apply both need it gone. A source
    check is the right shape here because the guarantee is "nowhere", and a
    behavioural test can only cover the paths someone thought to write.
    """
    import inspect

    import database.domains.dimensions as module

    source = inspect.getsource(module)
    offenders = [
        line.strip() for line in source.splitlines()
        if 'conn.commit()' in line and not line.strip().startswith('#')
    ]
    assert offenders == [], (
        f'bare commits are back in dimensions.py: {offenders}. Use '
        'self.transaction() -- it is re-entrant, so a method that opens one '
        'may freely be called from inside another.'
    )
