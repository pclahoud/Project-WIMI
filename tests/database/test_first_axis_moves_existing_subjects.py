"""Giving an exam its first axis asks about the subjects it already has (#605).

The owner's decision, 2026-10-09: *ask each time, defaulting to moving them
in*. Wave 1 builds the wizard's half. The student's answer travels in the same
``save_exam_edit`` call that creates the axes, and the move runs in the same
transaction, because a second call after the save would let the wizard report
success over half the work (#874, #240).

One rule per test. The ones worth not losing:

* the move is **per top-level subject** when several axes arrive at once
  (decision 1), and an unlisted subject takes the first axis;
* two top-level subjects that **share a descendant** go to one axis or the
  save is refused (decision 6) -- otherwise the shared subject sits in one
  axis under a parent in another, a cross-dimensional edge;
* **every refusal saves nothing**, the new axes included. That includes a
  refusal ``move_subjects_into_axis`` RETURNS rather than raises, which is
  the trap the plan names: unwrapped, it would commit the axis without the
  move;
* the preview's ``subject_count`` is **distinct**, and the test says how much
  larger the naive sum is so it cannot pass by coincidence.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.exceptions import ValidationError

EXAM = "Pre-Axis Exam"


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(username="first_axis", display_name="First Axis",
                                  user_types=["student"])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username=user.username)
        db._ensure_phase2_schema()
        yield db
        db.close()
        master.close()


def _subject(db, name, import_id=None, dimension_id=None):
    cur = db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, dimension_id,"
        " import_id, sort_order, status) VALUES (?, ?, 'System', ?, ?, 0, 'active')",
        (EXAM, name, dimension_id, import_id))
    db.conn.commit()
    return cur.lastrowid


@pytest.fixture
def plain(user_db):
    """A Simple exam: Cardio > Arrhythmia > AFib, and Renal > AKI. No axes."""
    exam = user_db.create_exam_context(exam_name=EXAM, exam_description="#605")
    ids = {n: _subject(user_db, n) for n in ("Cardio", "Arrhythmia", "AFib",
                                             "Renal", "AKI")}
    user_db.add_edge(ids["Cardio"], ids["Arrhythmia"], is_primary=True)
    user_db.add_edge(ids["Arrhythmia"], ids["AFib"], is_primary=True)
    user_db.add_edge(ids["Renal"], ids["AKI"], is_primary=True)
    user_db.conn.commit()
    return exam, ids


def _new_axes(*names):
    return [{"id": None, "name": n, "description": "", "is_required": True,
             "allow_multiple": False} for n in names]


def _axes(db, exam_id):
    return [(d["id"], d["name"]) for d in sorted(
        db.get_exam_dimensions(exam_id), key=lambda d: d["display_order"])]


def _dims(db):
    return {r["name"]: r["dimension_id"] for r in db.fetchall(
        "SELECT name, dimension_id FROM subject_nodes WHERE exam_context = ?",
        (EXAM,))}


def _snapshot(db, exam_id):
    row = db.fetchone("SELECT exam_name FROM exam_contexts WHERE id = ?", (exam_id,))
    return row["exam_name"], _axes(db, exam_id), _dims(db)


def _move(*pairs):
    return {"action": "move",
            "assignments": [{"subject_id": s, "axis": a} for s, a in pairs]}


# --- the move -------------------------------------------------------------


def test_each_top_level_subject_moves_with_its_tree_into_its_chosen_axis(user_db, plain):
    exam, ids = plain
    result = user_db.save_exam_edit(
        exam.id, {}, dimensions=_new_axes("System", "Discipline"),
        existing_subjects=_move((ids["Cardio"], 0), (ids["Renal"], 1)))

    system, discipline = result["dimension_ids"]
    dims = _dims(user_db)
    assert [dims[n] for n in ("Cardio", "Arrhythmia", "AFib")] == [system] * 3
    assert [dims[n] for n in ("Renal", "AKI")] == [discipline] * 2
    assert result["moved_existing"] == {
        "action": "move", "moved": 5,
        "by_axis": [{"axis_id": system, "name": "System", "moved": 3},
                    {"axis_id": discipline, "name": "Discipline", "moved": 2}]}


def test_an_unlisted_subject_takes_the_first_axis_and_a_listed_one_keeps_its_choice(
        user_db, plain):
    """Renal is not listed (made after the dialog was drawn); Cardio is the control."""
    exam, ids = plain
    result = user_db.save_exam_edit(
        exam.id, {}, dimensions=_new_axes("System", "Discipline"),
        existing_subjects=_move((ids["Cardio"], 1)))

    system, discipline = result["dimension_ids"]
    dims = _dims(user_db)
    assert dims["Renal"] == system, "an unlisted subject must take the first axis"
    assert dims["Cardio"] == discipline, "a listed subject must keep its choice"


def test_an_empty_assignment_list_moves_everything_into_the_first_axis(user_db, plain):
    """What the wizard sends when the preview read failed (#486's rule)."""
    exam, _ids = plain
    result = user_db.save_exam_edit(
        exam.id, {}, dimensions=_new_axes("System"),
        existing_subjects={"action": "move", "assignments": []})
    assert set(_dims(user_db).values()) == {result["dimension_ids"][0]}


def test_a_rename_in_the_same_save_does_not_strand_the_move(user_db, plain):
    """Subjects are keyed by exam NAME; the rename runs first in the transaction."""
    exam, _ids = plain
    result = user_db.save_exam_edit(
        exam.id, {"exam_name": "Renamed Exam"}, dimensions=_new_axes("System"),
        existing_subjects={"action": "move", "assignments": []})
    assert result["moved_existing"]["moved"] == 5
    rows = user_db.fetchall("SELECT dimension_id FROM subject_nodes"
                            " WHERE exam_context = 'Renamed Exam'")
    assert {r["dimension_id"] for r in rows} == {result["dimension_ids"][0]}


def test_keep_them_aside_moves_nothing_and_still_creates_the_axis(user_db, plain):
    exam, _ids = plain
    result = user_db.save_exam_edit(
        exam.id, {}, dimensions=_new_axes("System"),
        existing_subjects={"action": "aside"})
    assert _axes(user_db, exam.id) == [(result["dimension_ids"][0], "System")]
    assert set(_dims(user_db).values()) == {None}
    assert result["moved_existing"] == {"action": "aside", "moved": 0, "by_axis": []}
    assert len(user_db.get_subjects_outside_any_axis(exam.id)) == 2, (
        "kept aside, the subjects must be what the tree editor's panel lists")


def test_no_question_asked_leaves_the_subjects_and_reports_nothing(user_db, plain):
    exam, _ids = plain
    result = user_db.save_exam_edit(exam.id, {}, dimensions=_new_axes("System"))
    assert result["moved_existing"] is None
    assert set(_dims(user_db).values()) == {None}


# --- refusals: each saves nothing -----------------------------------------


def _refused(db, exam, match, **kwargs):
    before = _snapshot(db, exam.id)
    with pytest.raises(ValidationError) as err:
        db.save_exam_edit(exam.id, {"exam_name": "Renamed"},
                          dimensions=kwargs.pop("dimensions",
                                                _new_axes("System", "Discipline")),
                          **kwargs)
    assert str(err.value).startswith("Nothing was saved."), str(err.value)
    assert match in str(err.value), str(err.value)
    assert _snapshot(db, exam.id) == before, "a refusal still saved something"
    return str(err.value)


def test_a_stale_subject_is_refused(user_db, plain):
    exam, ids = plain
    user_db.execute("UPDATE subject_nodes SET status = 'archived' WHERE id = ?",
                    (ids["Renal"],))
    user_db.conn.commit()
    _refused(user_db, exam, "no longer a top-level subject",
             existing_subjects=_move((ids["Renal"], 0)))


def test_a_child_listed_as_top_level_is_refused(user_db, plain):
    exam, ids = plain
    _refused(user_db, exam, "no longer a top-level subject",
             existing_subjects=_move((ids["Arrhythmia"], 0)))


def test_a_subject_listed_twice_is_refused(user_db, plain):
    exam, ids = plain
    _refused(user_db, exam, "listed twice",
             existing_subjects=_move((ids["Cardio"], 0), (ids["Cardio"], 1)))


@pytest.mark.parametrize("axis", [2, -1, "0", None, True])
def test_an_axis_index_outside_the_new_axes_is_refused(user_db, plain, axis):
    exam, ids = plain
    _refused(user_db, exam, "not in this exam",
             existing_subjects=_move((ids["Cardio"], axis)))


def test_an_unreadable_choice_is_refused(user_db, plain):
    exam, _ids = plain
    _refused(user_db, exam, "could not be read",
             existing_subjects={"action": "everything"})


def test_shared_subjects_split_across_axes_are_refused_naming_both(user_db, plain):
    """Decision 6. Renal also parents AFib, so Cardio and Renal are one group."""
    exam, ids = plain
    user_db.add_edge(ids["Renal"], ids["AFib"])
    user_db.conn.commit()
    sentence = _refused(user_db, exam, "must go into the same axis",
                        existing_subjects=_move((ids["Cardio"], 0), (ids["Renal"], 1)))
    assert '"Cardio"' in sentence and '"Renal"' in sentence, sentence


def test_shared_subjects_in_one_axis_move_together(user_db, plain):
    """The control for the refusal above: the same tree, one axis, saves."""
    exam, ids = plain
    user_db.add_edge(ids["Renal"], ids["AFib"])
    user_db.conn.commit()
    result = user_db.save_exam_edit(
        exam.id, {}, dimensions=_new_axes("System", "Discipline"),
        existing_subjects=_move((ids["Cardio"], 1), (ids["Renal"], 1)))
    assert set(_dims(user_db).values()) == {result["dimension_ids"][1]}
    assert result["moved_existing"]["moved"] == 5, "AFib must be counted once"


def test_an_exam_that_gained_an_axis_since_is_refused(user_db, plain):
    exam, ids = plain
    user_db.create_dimension(exam_id=exam.id, name="Elsewhere", display_order=1)
    user_db.conn.commit()
    _refused(user_db, exam, "gained an axis since",
             existing_subjects=_move((ids["Cardio"], 0)))


def test_first_axis_alone_refuses_an_exam_that_gained_an_axis(user_db, plain):
    """No subjects means no question, but the axes list is still stale."""
    exam, _ids = plain
    user_db.create_dimension(exam_id=exam.id, name="Elsewhere", display_order=1)
    user_db.conn.commit()
    _refused(user_db, exam, "gained an axis since", first_axis=True)


def test_without_the_first_axis_claim_the_axis_list_wins(user_db, plain):
    """The control: the same save without the claim archives the unseen axis.

    That is #874's contract for a listed set of axes, and it is exactly the
    damage ``first_axis`` exists to refuse.
    """
    exam, _ids = plain
    elsewhere = user_db.create_dimension(exam_id=exam.id, name="Elsewhere",
                                         display_order=1)
    user_db.conn.commit()
    user_db.save_exam_edit(exam.id, {}, dimensions=_new_axes("System"))
    row = user_db.fetchone("SELECT status FROM exam_dimensions WHERE id = ?",
                           (elsewhere,))
    assert row["status"] == "archived"


def test_a_refused_move_saves_nothing_not_even_the_new_axis(user_db, plain, monkeypatch):
    """``move_subjects_into_axis`` RETURNS ``success=False``; it must not commit.

    Mirrors ``test_exam_edit_is_one_transaction.py``'s part failure. Without
    the wrap the axis would be created and the subjects left outside it, with
    the wizard reporting success.
    """
    exam, ids = plain
    monkeypatch.setattr(user_db, "move_subjects_into_axis",
                        lambda subject_ids, dimension_id: {
                            "success": False, "error": "That axis no longer exists."})
    _refused(user_db, exam, "That axis no longer exists.",
             existing_subjects=_move((ids["Cardio"], 0)))


def test_an_import_id_collision_is_a_sentence_not_an_integrity_error(user_db, plain):
    """m020's index, met through the shared helper (the wizard's axes are new,
    so this is the import's case; #904 is the panel's)."""
    exam, ids = plain
    axis = user_db.create_dimension(exam_id=exam.id, name="System", display_order=1)
    user_db.execute("UPDATE subject_nodes SET import_id = 'afib' WHERE id = ?",
                    (ids["AFib"],))
    _subject(user_db, "Atrial fibrillation", import_id="afib", dimension_id=axis)
    user_db.conn.commit()
    before = _dims(user_db)

    with pytest.raises(ValidationError) as err:
        with user_db.transaction():
            user_db._move_existing_into_new_axes(exam.id, [], axis)
    assert str(err.value).startswith("Nothing was saved."), str(err.value)
    assert '"AFib"' in str(err.value) and '"System"' in str(err.value), str(err.value)
    assert _dims(user_db) == before


def test_without_a_collision_the_same_helper_moves(user_db, plain):
    """The control: a different import id in the axis does not block the move."""
    exam, ids = plain
    axis = user_db.create_dimension(exam_id=exam.id, name="System", display_order=1)
    user_db.execute("UPDATE subject_nodes SET import_id = 'afib' WHERE id = ?",
                    (ids["AFib"],))
    _subject(user_db, "Something else", import_id="other", dimension_id=axis)
    user_db.conn.commit()
    with user_db.transaction():
        result = user_db._move_existing_into_new_axes(exam.id, [], axis)
    assert result["moved"] == 5


# --- the preview ----------------------------------------------------------


def test_the_preview_answers_on_an_exam_with_no_axes(user_db, plain):
    exam, ids = plain
    preview = user_db.get_existing_subjects_for_first_axis(exam.id)
    assert preview["has_active_axis"] is False
    assert preview["subject_count"] == 5
    assert [(r["name"], r["subtree_count"]) for r in preview["roots"]] == [
        ("Cardio", 3), ("Renal", 2)]
    assert preview["roots"][0]["group"] != preview["roots"][1]["group"]


def test_the_preview_counts_a_shared_subject_once(user_db, plain):
    """The negative control is the naive sum, which counts AFib twice."""
    exam, ids = plain
    user_db.add_edge(ids["Renal"], ids["AFib"])
    user_db.conn.commit()
    preview = user_db.get_existing_subjects_for_first_axis(exam.id)
    summed = sum(r["subtree_count"] for r in preview["roots"])
    assert summed == 6, "the fixture no longer shares AFib, so this proves nothing"
    assert preview["subject_count"] == 5


def test_the_preview_links_roots_that_share_a_subject(user_db, plain):
    exam, ids = plain
    lone = _subject(user_db, "Derm")
    user_db.add_edge(ids["Renal"], ids["AFib"])
    user_db.conn.commit()
    groups = {r["subject_id"]: r["group"] for r in
              user_db.get_existing_subjects_for_first_axis(exam.id)["roots"]}
    assert groups[ids["Cardio"]] == groups[ids["Renal"]]
    assert groups[lone] not in (groups[ids["Cardio"]],)


def test_the_preview_reports_import_clashes_per_axis(user_db, plain):
    """Wave 2's inputs, computed by Wave 1's read."""
    exam, ids = plain
    user_db.execute("UPDATE subject_nodes SET import_id = 'afib' WHERE id = ?",
                    (ids["AFib"],))
    user_db.conn.commit()
    roots = {r["name"]: r for r in user_db.get_existing_subjects_for_first_axis(
        exam.id, incoming_import_ids_by_axis={0: ["afib"], 1: ["x"]},
        incoming_names_by_axis={0: [], 1: ["renal "]})["roots"]}
    assert roots["Cardio"]["import_id_clash_axes"] == [0]
    assert roots["Renal"]["import_id_clash_axes"] == []
    assert roots["Renal"]["name_clash_axes"] == [1]
    assert roots["Cardio"]["name_clash_axes"] == []


def test_the_panels_read_still_returns_nothing_on_a_plain_exam(user_db, plain):
    exam, _ids = plain
    assert user_db.get_subjects_outside_any_axis(exam.id) == []
