"""The reorder slot applies the whole new order, or none of it (#211).

``tests/database/test_dimension_reorder_is_atomic.py`` covers the write. This
file covers the **slot**, because the defect lived in the bridge and the
database layer could be perfect while the slot still looped:

```python
with self.user_db.transaction():
    for new_order, dim_id in enumerate(dimension_ids, start=1):
        self.user_db.update_dimension(dimension_id=dim_id, display_order=new_order)
```

That loop committed on its first iteration (``update_dimension`` ended in a
bare ``conn.commit()``, which ends the transaction opened above it) and then
collided with ``UNIQUE(exam_id, display_order)`` as soon as a dimension moved
into an occupied slot — leaving the earlier writes committed and beyond the
reach of the rollback.

The slot reported that failure honestly; ``exam_wizard.js`` swallowed it into
a ``console.error``, so a student saw a normal Save and the old order back on
the next load.
"""
import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except Exception:
        pass


@pytest.fixture
def temp_master_db_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def user_db(temp_db_path: Path) -> Generator[UserDatabase, None, None]:
    db = UserDatabase(db_path=temp_db_path, user_id=1, username='test_user')
    db._ensure_phase7_schema()
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    master_db.bootstrap_first_user(username='test_admin', display_name='Test Admin')
    return DatabaseBridge(master_db=master_db, user_db=user_db)


@pytest.fixture
def exam_with_three_dimensions(user_db: UserDatabase):
    """Three dimensions at display_order 1, 2, 3."""
    exam = user_db.create_exam_context(exam_name='Issue 211 Reorder')
    ids = [
        user_db.create_dimension(exam_id=exam.id, name=f'Dimension {i}',
                                 display_order=i)
        for i in (1, 2, 3)
    ]
    return exam.id, ids


def _orders(user_db, exam_id):
    return {
        row['id']: row['display_order']
        for row in user_db.fetchall(
            'SELECT id, display_order FROM exam_dimensions WHERE exam_id = ?',
            (exam_id,),
        )
    }


def test_the_slot_moves_the_last_dimension_to_the_top(bridge, user_db,
                                                      exam_with_three_dimensions):
    """The exact reproduction from #211: reorder [3, 1, 2].

    Through the slot, not the database method, because the slot is what the
    exam wizard's Save calls.
    """
    exam_id, (d1, d2, d3) = exam_with_three_dimensions

    response = json.loads(bridge.reorderDimensions(exam_id, json.dumps([d3, d1, d2])))

    assert response['success'] is True, response.get('error')
    assert _orders(user_db, exam_id) == {d3: 1, d1: 2, d2: 3}


def test_the_slot_reorders_a_gapped_layout(bridge, user_db):
    """Orders (2, 3, 4) — what a hard ``delete_dimension`` leaves behind.

    ``syncDimensions`` deletes removed dimensions in the loop immediately
    above the reorder, in the same Save, so this layout is the normal one
    after any edit that drops a dimension — not an exotic case.
    """
    exam = user_db.create_exam_context(exam_name='Gapped')
    d1, d2, d3 = [
        user_db.create_dimension(exam_id=exam.id, name=f'D{i}', display_order=i)
        for i in (2, 3, 4)
    ]

    response = json.loads(bridge.reorderDimensions(exam.id, json.dumps([d2, d3, d1])))

    assert response['success'] is True, response.get('error')
    assert _orders(user_db, exam.id) == {d2: 1, d3: 2, d1: 3}


def test_a_failed_reorder_changes_nothing_and_says_so(bridge, user_db,
                                                      exam_with_three_dimensions):
    """The half-write, at the slot boundary.

    A partial list is the reachable way to make the slot refuse. What matters
    is both halves: ``success`` is false *and* the table is untouched. The old
    code could fail while having already committed part of the new order.
    """
    exam_id, (d1, d2, d3) = exam_with_three_dimensions
    before = _orders(user_db, exam_id)

    response = json.loads(bridge.reorderDimensions(exam_id, json.dumps([d2, d1])))

    assert response['success'] is False
    assert _orders(user_db, exam_id) == before, 'a refused reorder still wrote'


def test_the_error_reaches_the_caller_with_something_to_act_on(
        bridge, exam_with_three_dimensions):
    """`exam_wizard.js` now shows this string to the student.

    It used to go to `console.error` alone, so the message's content did not
    matter. It does now.
    """
    exam_id, (d1, d2, d3) = exam_with_three_dimensions

    response = json.loads(bridge.reorderDimensions(exam_id, json.dumps([d2, d1])))

    assert response['success'] is False
    assert str(d3) in response['error'], (
        f'the error does not name the dimension that was left out: {response["error"]}'
    )


def test_the_slot_no_longer_loops_update_dimension(bridge, user_db,
                                                   exam_with_three_dimensions):
    """Wiring: one atomic call, not N calls that each commit.

    Asserted by behaviour rather than by reading the source — if the slot goes
    back to calling ``update_dimension`` per dimension, this counts the calls
    and fails, whatever the loop is spelled like.
    """
    exam_id, (d1, d2, d3) = exam_with_three_dimensions
    calls = {'update': 0, 'reorder': 0}

    real_update = user_db.update_dimension
    real_reorder = user_db.reorder_dimensions

    def counting_update(*args, **kwargs):
        calls['update'] += 1
        return real_update(*args, **kwargs)

    def counting_reorder(*args, **kwargs):
        calls['reorder'] += 1
        return real_reorder(*args, **kwargs)

    user_db.update_dimension = counting_update
    user_db.reorder_dimensions = counting_reorder
    try:
        response = json.loads(
            bridge.reorderDimensions(exam_id, json.dumps([d3, d1, d2])))
    finally:
        user_db.update_dimension = real_update
        user_db.reorder_dimensions = real_reorder

    assert response['success'] is True, response.get('error')
    assert calls['reorder'] == 1, 'the slot did not use the atomic reorder'
    assert calls['update'] == 0, (
        f'the slot called update_dimension {calls["update"]} times. That is '
        'the #211 loop: each call used to commit, so the enclosing '
        'transaction could not roll the set back.'
    )
