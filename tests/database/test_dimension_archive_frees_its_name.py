"""Archiving a dimension frees its name, not only its order (#244).

`exam_dimensions` carries **two** unique table constraints, and SQLite checks
both against archived rows:

```sql
UNIQUE(exam_id, name),
UNIQUE(exam_id, display_order)
```

#210 parked `display_order = -id` on archive, for a reason it wrote down: *"a
kept slot would block a new dimension taking it"*. That argument applies word
for word to `name`, and the name was left occupied. So archiving "System" meant
no dimension in that exam could ever be called "System" again --
`DatabaseIntegrityError`, raised from `create_dimension` three frames below the
student, with **no way out**: restore is #37 and purge is #38, both open, so
the archived row can neither be revived nor removed.

**The shape these tests are built around.** The bug is not that a name is
reserved; it is that *one of two identical constraints was handled and the
other was missed*. So the order parking is asserted alongside the name parking
in the same test, as a negative control: a "fix" that freed the name by
dropping the order parking would trade this bug for #211's collision and pass
any test that only looked at names.

The parked spelling itself is deliberately **not** asserted anywhere except in
the one test that documents the mechanism. What callers are promised is that
the name is *free* and that the name the student chose is still *recoverable*
from the journal -- not how the row spells it meanwhile.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / 'src'))

from database import MasterDatabase, UserDatabase  # noqa: E402
from database.base_db import DatabaseIntegrityError  # noqa: E402


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=pathlib.Path(tmpdir))
        user = master.create_user(username='dim_name', display_name='Probe',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='dim_name')
        db._ensure_phase2_schema()
        db._ensure_phase4_schema()
        db._ensure_phase7_schema()
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context(exam_name='Issue 244')


def _dimension(user_db, exam, name, order):
    return user_db.create_dimension(exam_id=exam.id, name=name,
                                    display_order=order, is_required=True)


def _row(user_db, dimension_id):
    return dict(user_db.fetchone(
        'SELECT id, name, display_order, status, archived_batch_id '
        'FROM exam_dimensions WHERE id = ?', (dimension_id,)))


def test_the_name_can_be_used_again_after_archiving(user_db, exam):
    """The headline. This raised `DatabaseIntegrityError` before the fix."""
    first = _dimension(user_db, exam, 'System', 1)
    user_db.archive_dimension(first)

    second = _dimension(user_db, exam, 'System', 1)

    assert second != first
    active = user_db.get_exam_dimensions(exam.id)
    assert [d['name'] for d in active] == ['System']
    assert [d['id'] for d in active] == [second]


def test_both_unique_slots_are_freed_not_one(user_db, exam):
    """The negative control, and the reason this bug existed at all.

    Freeing the name by *dropping* the order parking would pass a
    name-only test and reintroduce #211's collision. Both are asserted
    here so neither can be traded for the other.
    """
    dimension_id = _dimension(user_db, exam, 'System', 3)
    user_db.archive_dimension(dimension_id)

    row = _row(user_db, dimension_id)
    assert row['display_order'] == -dimension_id, 'the order slot was not freed'
    assert row['name'] != 'System', 'the name slot was not freed'

    # Both slots are genuinely re-usable, which is the only claim that
    # matters -- taking them is what failed before.
    reused = _dimension(user_db, exam, 'System', 3)
    assert _row(user_db, reused)['display_order'] == 3


def test_the_journal_keeps_the_name_the_student_chose(user_db, exam):
    """#37 restores a name, so the name has to survive the parking write.

    `archive_dimension` inserts into `dimension_delete_batches` **before**
    the parking UPDATE. If those two were ever reordered, restore would put
    back the parked spelling and nothing else would notice.
    """
    dimension_id = _dimension(user_db, exam, 'Physician Task', 1)
    result = user_db.archive_dimension(dimension_id)

    journalled = user_db.fetchone(
        'SELECT dimension_name FROM dimension_delete_batches WHERE id = ?',
        (result['batch_id'],))

    assert journalled['dimension_name'] == 'Physician Task'


def test_the_parked_spelling_carries_the_id(user_db, exam):
    """The mechanism, documented once.

    Uniqueness has to come from something unique, and `id` is the only
    thing available -- exactly as it is for `display_order = -id`. A parked
    name built from anything else could collide with a second archive of
    the same name, which is the next test.
    """
    dimension_id = _dimension(user_db, exam, 'System', 1)
    user_db.archive_dimension(dimension_id)

    assert _row(user_db, dimension_id)['name'] == f'System (archived #{dimension_id})'


def test_archiving_the_same_name_twice_does_not_collide(user_db, exam):
    """Archive "System", recreate it, archive it again.

    Two archived rows that had the same name are the case a parked spelling
    without the id gets wrong, and it is reachable by any student who
    archives a dimension, thinks better of it, and archives it again.
    """
    first = _dimension(user_db, exam, 'System', 1)
    user_db.archive_dimension(first)
    second = _dimension(user_db, exam, 'System', 1)
    user_db.archive_dimension(second)

    names = {
        row['id']: row['name'] for row in user_db.fetchall(
            "SELECT id, name FROM exam_dimensions WHERE exam_id = ? "
            "AND status = 'archived'", (exam.id,))
    }
    assert len(names) == 2
    assert len(set(names.values())) == 2, f'two archived rows collided: {names}'

    # And the name is still free afterwards.
    third = _dimension(user_db, exam, 'System', 1)
    assert third not in names


def test_an_archived_dimension_is_absent_from_the_active_read(user_db, exam):
    """The parked name must never reach a student.

    Every read of `exam_dimensions` filters `status = 'active'` (#210), so
    the parked spelling is invisible. This is the test that fails loudly if
    that filter is ever dropped from `get_exam_dimensions`, because the
    parked name is far more conspicuous than a missing filter.
    """
    dimension_id = _dimension(user_db, exam, 'System', 1)
    user_db.archive_dimension(dimension_id)

    assert user_db.get_exam_dimensions(exam.id) == []
    assert user_db.get_dimension(dimension_id) is None


def test_the_preview_reports_the_real_name_for_an_archived_dimension(
        user_db, exam):
    """`get_dimension_delete_preview` deliberately ignores `status`.

    It is the one read that looks at an archived row, because it reports
    `already_archived` -- so it is the one read that would otherwise show
    the parked spelling as the dimension's name.
    """
    dimension_id = _dimension(user_db, exam, 'System', 1)
    user_db.archive_dimension(dimension_id)

    preview = user_db.get_dimension_delete_preview(dimension_id)

    assert preview['already_archived'] is True
    assert preview['dimension_name'] == 'System'


def test_archiving_returns_the_real_name(user_db, exam):
    """The caller's own result is read before the parking write, so it is
    already correct -- asserted because it is one `return` statement away
    from not being."""
    dimension_id = _dimension(user_db, exam, 'Site of Care', 1)

    result = user_db.archive_dimension(dimension_id)

    assert result['dimension_name'] == 'Site of Care'


def test_two_active_dimensions_still_cannot_share_a_name(user_db, exam):
    """Negative control: the constraint is not being weakened.

    The fix frees an *archived* row's name. Two live dimensions sharing one
    is still refused, and a fix that dropped `UNIQUE(exam_id, name)` to
    make the headline test pass would fail here.
    """
    _dimension(user_db, exam, 'System', 1)

    with pytest.raises(DatabaseIntegrityError):
        _dimension(user_db, exam, 'System', 2)
