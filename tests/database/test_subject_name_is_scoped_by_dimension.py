"""A subject's name is unique within its dimension, not within the exam (#246).

`create_subject_node` hand-rolls a duplicate check, and it was scoped to **exam
context + name + parent** with no `dimension_id`. So two dimensions of one exam
could not both contain a root subject of the same name:

    created in System -> 1
    FAILED in Discipline -> SubjectNodeError Subject node already exists: E/Renal

The axes of a real blueprint are **overlapping partitions of the same item
pool** -- USMLE publishes Behavioral Health as both a System and a Discipline,
and #64 records that overlap as the reason weights legitimately total 84-153%.
A name shared across axes is therefore ordinary data, and this refused it from
the tree editor as well as from an import.

**Two things these tests are built around.**

*The table constraint is not what was refusing it.* `subject_nodes` carries
`UNIQUE(exam_context, name, parent_id)`, and for two roots `parent_id` is NULL
in both rows -- SQLite treats NULLs as distinct in an index, so it never fired.
The hand-rolled query was the only check. A test asserts the constraint still
does its own job, so the fix cannot be mistaken for weakening it.

*The scope is the dimension, not "anything goes".* Every test that widens the
scope is paired with one that shows a genuine duplicate is still refused. The
bug was a missing predicate; over-correcting it would let a real duplicate
through and nothing else in the codebase would catch that.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / 'src'))

from database import MasterDatabase, UserDatabase  # noqa: E402
from database.exceptions import SubjectNodeError  # noqa: E402


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=pathlib.Path(tmpdir))
        user = master.create_user(username='dim_names', display_name='Probe',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='dim_names')
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    user_db.create_exam_context(exam_name='Scoped', exam_description='#246')
    return user_db.get_exam_context_by_name('Scoped')


@pytest.fixture
def axes(user_db, exam):
    return (
        user_db.create_dimension(exam_id=exam.id, name='System', display_order=1),
        user_db.create_dimension(exam_id=exam.id, name='Discipline',
                                 display_order=2),
    )


def _subject(user_db, exam, name, dimension_id=None, parent_id=None):
    return user_db.create_subject_node(
        exam_context=exam.exam_name, name=name, level_type='System',
        parent_id=parent_id, dimension_id=dimension_id)


def test_two_axes_can_both_hold_a_root_of_the_same_name(user_db, exam, axes):
    """The headline. This raised `SubjectNodeError` before the fix."""
    system, discipline = axes

    first = _subject(user_db, exam, 'Behavioral Health', system)
    second = _subject(user_db, exam, 'Behavioral Health', discipline)

    assert first.id != second.id
    rows = {
        row['dimension_id']: row['id'] for row in user_db.fetchall(
            "SELECT id, dimension_id FROM subject_nodes "
            "WHERE exam_context = ? AND name = 'Behavioral Health' "
            "AND status = 'active'", (exam.exam_name,))
    }
    assert rows == {system: first.id, discipline: second.id}


def test_a_duplicate_root_within_one_axis_is_still_refused(user_db, exam, axes):
    """The paired negative control. The scope narrowed; it did not vanish."""
    system, _ = axes
    _subject(user_db, exam, 'Renal', system)

    with pytest.raises(SubjectNodeError, match='already exists'):
        _subject(user_db, exam, 'Renal', system)


def test_an_axis_and_the_dimensionless_tree_do_not_collide(user_db, exam, axes):
    """`dimension_id IS NULL` is its own partition.

    A legacy tree from before the exam used dimensions shares the exam
    context with every axis, so an exam-wide check made the legacy names
    unusable in every new axis.
    """
    system, _ = axes

    legacy = _subject(user_db, exam, 'Renal', None)
    in_axis = _subject(user_db, exam, 'Renal', system)

    assert legacy.id != in_axis.id


def test_a_duplicate_in_the_dimensionless_tree_is_still_refused(user_db, exam):
    """`IS ?` has to be NULL-safe, or this passes when it should not.

    Written with `= ?` the predicate is NULL against NULL, which is never
    true, and every dimensionless duplicate would be allowed through. That
    is the failure mode of fixing this with the wrong operator, and it is
    silent.
    """
    _subject(user_db, exam, 'Renal', None)

    with pytest.raises(SubjectNodeError, match='already exists'):
        _subject(user_db, exam, 'Renal', None)


def test_two_children_of_one_parent_are_still_refused(user_db, exam, axes):
    """A parent lives in one dimension, so its children sharing a name are a
    genuine duplicate however the check is scoped."""
    system, _ = axes
    parent = _subject(user_db, exam, 'Cardiovascular', system)
    _subject(user_db, exam, 'Heart Failure', system, parent.id)

    with pytest.raises(SubjectNodeError, match='already exists'):
        _subject(user_db, exam, 'Heart Failure', system, parent.id)


def test_children_of_different_parents_may_share_a_name(user_db, exam, axes):
    """Unchanged by this fix, asserted so the change is visibly scoped to the
    dimension rather than to parenthood."""
    system, _ = axes
    first = _subject(user_db, exam, 'Cardiovascular', system)
    second = _subject(user_db, exam, 'Renal', system)

    a = _subject(user_db, exam, 'Hypertension', system, first.id)
    b = _subject(user_db, exam, 'Hypertension', system, second.id)

    assert a.id != b.id


def test_the_table_constraint_still_refuses_a_same_parent_duplicate(
        user_db, exam, axes):
    """`UNIQUE(exam_context, name, parent_id)` is not being relaxed.

    The fix loosened a hand-rolled query, not the schema. Inserting past the
    Python check directly has to still hit the constraint, or a future
    refactor could delete the query believing the table had it covered --
    which is true for children and false for roots.
    """
    from database.base_db import DatabaseIntegrityError

    system, _ = axes
    parent = _subject(user_db, exam, 'Cardiovascular', system)
    child = _subject(user_db, exam, 'Heart Failure', system, parent.id)

    with pytest.raises(DatabaseIntegrityError):
        with user_db.transaction():
            user_db.execute(
                "INSERT INTO subject_nodes "
                "(exam_context, name, parent_id, level_type, dimension_id) "
                "VALUES (?, 'Heart Failure', ?, 'System', ?)",
                (exam.exam_name, parent.id, system))
    assert child.id


def test_an_archived_subject_does_not_block_its_name(user_db, exam, axes):
    """Unchanged, and worth pinning next to #244.

    This check filters `status = 'active'`, so archiving a subject frees its
    name -- the opposite of what `exam_dimensions` did before #244, where an
    archived row held its name forever.
    """
    system, _ = axes
    first = _subject(user_db, exam, 'Renal', system)
    user_db.delete_subject_subtree(first.id)

    second = _subject(user_db, exam, 'Renal', system)

    assert second.id != first.id


def test_three_axes_sharing_one_name_all_import(user_db, exam):
    """The shape #241 needs: a name common to every axis of a real blueprint."""
    created = []
    for order, axis_name in enumerate(
            ('System', 'Discipline', 'Physician Task'), start=1):
        dimension_id = user_db.create_dimension(
            exam_id=exam.id, name=axis_name, display_order=order)
        created.append(_subject(user_db, exam, 'Immune System', dimension_id).id)

    assert len(set(created)) == 3
