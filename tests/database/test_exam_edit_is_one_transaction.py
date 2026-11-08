"""#874: the exam wizard's edit mode saves whole, or not at all.

The wizard used to save an edit in three independent calls: the settings,
then the length, then a dimension sync of one call per axis. Only the first
could fail the save. The length and every axis caught their own errors and
logged them to the console, so the student was told "updated successfully"
over a part that had not been saved (#240's *reads-like-success*).

``save_exam_edit`` writes every part inside one transaction. These tests pin
three things:

* a failure in ANY part leaves EVERY part as it was;
* the sentence names the part that failed;
* the dimension sync runs in an order that cannot collide on
  ``exam_dimensions``' two UNIQUE constraints. The old sync created and
  renamed axes before archiving the removed ones and wrote orders row by row,
  so a new axis in a removed axis's slot, or two axes swapping names, failed.
  The failure was swallowed.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.exceptions import ValidationError

FIXED_280 = {"kind": "fixed", "min": 280, "max": 280, "typical": 280, "note": None}
BAD_RANGE = {"kind": "range", "min": 300, "max": 100, "typical": 200, "note": None}


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(username="edit_user", display_name="Edit User",
                                  user_types=["student"])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username=user.username)
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    """An exam with a known length and three axes, System / Task / Discipline."""
    exam = user_db.create_exam_context(exam_name="Step 2 CK", exam_description="before")
    user_db.update_exam_length(exam.id, "range", 100, 300, 200)
    axes = [user_db.create_dimension(exam_id=exam.id, name=n, display_order=i)
            for i, n in enumerate(("System", "Task", "Discipline"), start=1)]
    user_db.conn.commit()
    return exam, axes


def _axes(db, exam_id):
    return [(d["id"], d["name"], d["display_order"])
            for d in sorted(db.get_exam_dimensions(exam_id),
                            key=lambda d: d["display_order"])]


def _snapshot(db, exam_id):
    row = db.fetchone("SELECT exam_name, exam_description, length_kind, length_min,"
                      " length_max FROM exam_contexts WHERE id = ?", (exam_id,))
    return dict(row), _axes(db, exam_id)


def _wanted(axes_in_order):
    return [{"id": i, "name": n, "description": "", "is_required": True,
             "allow_multiple": False} for i, n in axes_in_order]


def test_a_whole_edit_saves_every_part(user_db, exam):
    ex, (system, task, discipline) = exam
    result = user_db.save_exam_edit(
        ex.id, {"exam_name": "USMLE Step 2 CK", "exam_description": "after"},
        length=FIXED_280,
        dimensions=_wanted([(discipline, "Discipline"), (system, "Organ System"),
                            (None, "Setting")]))

    row, axes = _snapshot(user_db, ex.id)
    assert (row["exam_name"], row["exam_description"]) == ("USMLE Step 2 CK", "after")
    assert (row["length_kind"], row["length_min"]) == ("fixed", 280)
    new = result["dimension_ids"][2]
    assert axes == [(discipline, "Discipline", 1), (system, "Organ System", 2),
                    (new, "Setting", 3)]
    assert result["dimension_ids"] == [discipline, system, new]
    archived = user_db.fetchone("SELECT status FROM exam_dimensions WHERE id = ?", (task,))
    assert archived["status"] == "archived", "the removed axis must be archived (#210)"


@pytest.mark.parametrize("failing", ["length", "dimension"])
def test_a_failure_in_any_part_saves_nothing(user_db, exam, failing):
    ex, (system, task, discipline) = exam
    before = _snapshot(user_db, ex.id)
    if failing == "length":
        length, dims, said = BAD_RANGE, None, "The exam's length could not be saved"
    else:
        # Rename System into a name a KEPT, unrenamed axis holds: a real clash.
        length = FIXED_280
        dims = _wanted([(system, "Task"), (task, "Task"), (discipline, "Discipline")])
        said = 'The dimension "Task" could not be saved'

    with pytest.raises(ValidationError) as err:
        user_db.save_exam_edit(ex.id, {"exam_name": "Renamed", "exam_description": "after"},
                               length=length, dimensions=dims)

    assert str(err.value).startswith("Nothing was saved."), str(err.value)
    assert said in str(err.value), str(err.value)
    assert _snapshot(user_db, ex.id) == before, (
        f"#874: a refused {failing} still let other parts of the edit through")


def test_a_new_axis_can_take_a_removed_axis_slot_and_name(user_db, exam):
    """The old sync created before it archived, so this collided on both UNIQUEs."""
    ex, (system, task, discipline) = exam
    result = user_db.save_exam_edit(
        ex.id, {}, dimensions=_wanted([(system, "System"), (None, "Task"),
                                       (discipline, "Discipline")]))
    new = result["dimension_ids"][1]
    assert new != task
    assert _axes(user_db, ex.id) == [(system, "System", 1), (new, "Task", 2),
                                     (discipline, "Discipline", 3)]


def test_two_axes_can_swap_names(user_db, exam):
    ex, (system, task, discipline) = exam
    user_db.save_exam_edit(ex.id, {}, dimensions=_wanted(
        [(system, "Task"), (task, "System"), (discipline, "Discipline")]))
    assert _axes(user_db, ex.id) == [(system, "Task", 1), (task, "System", 2),
                                     (discipline, "Discipline", 3)]


def test_omitted_parts_are_left_alone(user_db, exam):
    ex, _ = exam
    _, axes_before = _snapshot(user_db, ex.id)
    user_db.save_exam_edit(ex.id, {"exam_description": "only this"})
    row, axes = _snapshot(user_db, ex.id)
    assert row["exam_description"] == "only this"
    assert (row["length_kind"], row["length_min"], row["length_max"]) == ("range", 100, 300)
    assert axes == axes_before


def test_an_axis_that_no_longer_exists_is_refused(user_db, exam):
    ex, (system, task, discipline) = exam
    user_db.archive_dimension(task)
    before = _snapshot(user_db, ex.id)
    with pytest.raises(ValidationError, match="no longer exists"):
        user_db.save_exam_edit(ex.id, {"exam_description": "x"}, dimensions=_wanted(
            [(system, "System"), (task, "Task"), (discipline, "Discipline")]))
    assert _snapshot(user_db, ex.id) == before


# --- #900: what `dimensions` means when the wizard sends Simple --------------
#
# The owner chose option C: an exam with axes cannot be switched back to
# Simple, and the wizard refuses before it saves. These pin what the two
# possible payloads do, so the refusal's reason is written down where the
# contract lives: ``null`` changes nothing (so a Simple save on an exam with
# axes would report a success that did not happen, the #240 shape), and ``[]``
# archives every axis and every tree (so the wizard must never send it: on
# loadExistingExam's fallback it would archive an exam the wizard could not
# read).


def _with_subjects(db, exam_id, axes):
    """One subject per axis, so the archive's cascade has something to take."""
    name = db.fetchone("SELECT exam_name FROM exam_contexts WHERE id = ?",
                       (exam_id,))["exam_name"]
    ids = [db.create_subject_node(name, f"Subject {i}", "System", dimension_id=a).id
           for i, a in enumerate(axes)]
    db.conn.commit()
    return ids


def _statuses(db, table, ids):
    marks = ", ".join("?" for _ in ids)
    return {r["status"] for r in db.fetchall(
        f"SELECT status FROM {table} WHERE id IN ({marks})", tuple(ids))}


def test_null_dimensions_leaves_every_axis_and_its_subjects_active(user_db, exam):
    ex, axes = exam
    subjects = _with_subjects(user_db, ex.id, axes)
    user_db.save_exam_edit(ex.id, {"exam_description": "saved as Simple"},
                           dimensions=None)
    assert _statuses(user_db, "exam_dimensions", axes) == {"active"}
    assert _statuses(user_db, "subject_nodes", subjects) == {"active"}
    assert user_db.exam_uses_dimensions(ex.id)


def test_an_empty_dimension_list_archives_every_axis_and_its_trees(user_db, exam):
    ex, axes = exam
    subjects = _with_subjects(user_db, ex.id, axes)
    user_db.save_exam_edit(ex.id, {}, dimensions=[])
    assert _statuses(user_db, "exam_dimensions", axes) == {"archived"}
    assert _statuses(user_db, "subject_nodes", subjects) == {"archived"}
    assert not user_db.exam_uses_dimensions(ex.id)
