"""Subjects stranded outside every axis can be found and moved in (#605).

Adding the first axis to an exam that already has subjects leaves every
one of them at ``dimension_id NULL``. The dimensioned tree filters on
``dimension_id`` and the plain tree is never drawn once an exam has an
axis, so the student's whole tree vanishes with no warning and nothing to
click. The flag is derived -- one active dimension flips the exam
immediately -- so there is no migration and no moment to hook.

The owner's design, 2026-10-10: a collapsed panel on the Archived-subjects
pattern, and it can move them in. These are the two reads and the one
write behind it.

The assertions worth not losing:

* a **dimensionless** exam reports nothing. Every subject there is drawn
  by the plain path, and a panel that appeared on a healthy exam would be
  noise;
* the listing is **roots only**, because moving a root moves its subtree
  and a flat list would offer the same operation dozens of times;
* a move takes **the whole subtree**, because cross-dimensional edges are
  a Non-Goal and leaving the children behind manufactures exactly that;
* the walk **stops at a subject already in an axis**, which is not
  tidiness: continuing would drag a subject back out of the axis somebody
  deliberately put it in.
"""
from __future__ import annotations

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
    user = master_db.create_user(
        username="axis_mover", display_name="Mover", user_types=["student"])
    db = UserDatabase(
        db_path=master_db.ensure_user_database(user.id),
        user_id=user.id, username=user.username)
    db._ensure_phase2_schema()
    yield db
    db.close()


def _exam(user_db):
    return user_db.create_exam_context(
        exam_name="Pre-Axis Exam", exam_description="#605")


def _subject(user_db, exam, name, dimension_id=None):
    cur = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, "
        "dimension_id, sort_order, status) VALUES (?, ?, 'System', ?, 0, 'active')",
        (exam.exam_name, name, dimension_id))
    user_db.conn.commit()
    return cur.lastrowid


def _tree(user_db, exam):
    """Root -> child -> grandchild, all outside every axis."""
    root = _subject(user_db, exam, "Cardiovascular System")
    child = _subject(user_db, exam, "Arrhythmias")
    grandchild = _subject(user_db, exam, "Atrial fibrillation")
    user_db.add_edge(root, child, is_primary=True)
    user_db.add_edge(child, grandchild, is_primary=True)
    return root, child, grandchild


def test_a_dimensionless_exam_reports_nothing(user_db):
    """No axes means nothing is outside one. The panel must stay off."""
    exam = _exam(user_db)
    _tree(user_db, exam)

    assert user_db.get_subjects_outside_any_axis(exam.id) == [], (
        "an exam with no dimensions draws every subject on the plain path; "
        "reporting them would turn the panel on for a healthy exam")


def test_adding_the_first_axis_strands_the_existing_tree(user_db):
    """The defect itself, and the listing that ends it.

    One root is reported, not three subjects -- moving the root moves the
    subtree, so listing each descendant would offer the same operation
    three times.
    """
    exam = _exam(user_db)
    root, child, grandchild = _tree(user_db, exam)
    user_db.create_dimension(exam_id=exam.id, name="Discipline", display_order=1)

    stranded = user_db.get_subjects_outside_any_axis(exam.id)

    assert len(stranded) == 1, (
        f"expected the one root, got {[s['name'] for s in stranded]}")
    assert stranded[0]['subject_id'] == root
    assert stranded[0]['subtree_count'] == 3, (
        "the row must say how many subjects travel with it: the name alone "
        f"does not tell a student what is stranded. Got {stranded[0]!r}")


def test_moving_a_root_takes_its_whole_subtree(user_db):
    exam = _exam(user_db)
    root, child, grandchild = _tree(user_db, exam)
    axis = user_db.create_dimension(
        exam_id=exam.id, name="Discipline", display_order=1)

    result = user_db.move_subjects_into_axis([root], axis)

    assert result['success'] is True, result
    assert result['moved'] == 3, (
        "cross-dimensional edges are a Non-Goal, so the children must move "
        f"with the parent: {result!r}")
    for node_id in (root, child, grandchild):
        row = user_db.fetchone(
            "SELECT dimension_id FROM subject_nodes WHERE id = ?", (node_id,))
        assert row['dimension_id'] == axis, f"{node_id} was left behind"

    assert user_db.get_subjects_outside_any_axis(exam.id) == [], (
        "nothing should be stranded once the only tree has moved")


def test_the_move_stops_at_a_subject_already_in_an_axis(user_db):
    """Not tidiness: continuing would pull a subject back OUT of its axis."""
    exam = _exam(user_db)
    root, child, grandchild = _tree(user_db, exam)
    first = user_db.create_dimension(
        exam_id=exam.id, name="Discipline", display_order=1)
    second = user_db.create_dimension(
        exam_id=exam.id, name="System", display_order=2)

    # Somebody has already filed the grandchild under `second`.
    user_db.execute(
        "UPDATE subject_nodes SET dimension_id = ? WHERE id = ?",
        (second, grandchild))
    user_db.conn.commit()

    result = user_db.move_subjects_into_axis([root], first)

    assert result['moved'] == 2, (
        f"the walk must stop at the subject already in an axis: {result!r}")
    row = user_db.fetchone(
        "SELECT dimension_id FROM subject_nodes WHERE id = ?", (grandchild,))
    assert row['dimension_id'] == second, (
        "a subject deliberately filed under one axis was dragged into "
        "another by a move it was not part of")


def test_an_archived_axis_is_refused_with_a_sentence(user_db):
    exam = _exam(user_db)
    root, _, _ = _tree(user_db, exam)
    axis = user_db.create_dimension(
        exam_id=exam.id, name="Retired", display_order=1)
    user_db.execute(
        "UPDATE exam_dimensions SET status = 'archived' WHERE id = ?", (axis,))
    user_db.conn.commit()

    result = user_db.move_subjects_into_axis([root], axis)

    assert result['success'] is False
    assert "Retired" in result['error'] and "archived" in result['error'], (
        f"the refusal must name the axis and say why: {result!r}")


def test_an_axis_from_another_exam_is_refused_with_a_sentence(user_db):
    """Reachable: a page can have two exams in play across a navigation."""
    exam = _exam(user_db)
    root, _, _ = _tree(user_db, exam)
    other = user_db.create_exam_context(
        exam_name="Other Exam", exam_description="#605")
    foreign = user_db.create_dimension(
        exam_id=other.id, name="Elsewhere", display_order=1)

    result = user_db.move_subjects_into_axis([root], foreign)

    assert result['success'] is False
    assert "different exam" in result['error'], (
        f"expected a sentence, not an IntegrityError: {result!r}")
    row = user_db.fetchone(
        "SELECT dimension_id FROM subject_nodes WHERE id = ?", (root,))
    assert row['dimension_id'] is None, "the refused move still wrote"


def test_a_subject_whose_parent_already_moved_is_still_listed(user_db):
    """The half-moved state, which "no parent at all" would skip.

    Mirror of ``_dimension_root_node_ids``' reasoning: a root here is one
    with no active parent *that is also outside every axis*. Anchoring on
    "no incoming edge" would hide this child forever.
    """
    exam = _exam(user_db)
    root, child, grandchild = _tree(user_db, exam)
    axis = user_db.create_dimension(
        exam_id=exam.id, name="Discipline", display_order=1)
    user_db.execute(
        "UPDATE subject_nodes SET dimension_id = ? WHERE id = ?", (axis, root))
    user_db.conn.commit()

    stranded = user_db.get_subjects_outside_any_axis(exam.id)

    assert [s['subject_id'] for s in stranded] == [child], (
        "the child has a parent, but that parent is in an axis now, so the "
        f"child is a root of what remains stranded: {stranded!r}")
    assert stranded[0]['subtree_count'] == 2
