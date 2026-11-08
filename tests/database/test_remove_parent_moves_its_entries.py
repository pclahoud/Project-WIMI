"""Removing a parent re-files the entries filed under it (#738).

An entry's parent context (``entry_subject_mappings.primary_parent_id``)
could name a parent the subject no longer had: ``remove_edge`` was a bare
DELETE. The owner's decision on #738 is *ask each time*, so the caller names
one of the subject's remaining parents. With no name given the entries go to
the primary, so no caller can orphan them, and they are cleared only when no
parent remains.
"""
from __future__ import annotations

from datetime import date

import pytest

from database.exceptions import ValidationError
from database.user_db import UserDatabase


@pytest.fixture
def world(tmp_path):
    db = UserDatabase(str(tmp_path / "edges738.db"), user_id=1, username="e738")
    exam = db.create_exam_context(exam_name="E738", exam_description="")
    mk = lambda name: db.create_subject_node(exam_context=exam.exam_name, name=name,
                                             level_type="System")
    a, b, c, child = mk("Cardiology"), mk("Pharmacology"), mk("Emergencies"), mk("Beta blockers")
    edge_a = db.add_edge(a.id, child.id, is_primary=True).id
    edge_b = db.add_edge(b.id, child.id).id
    edge_c = db.add_edge(c.id, child.id).id
    session = db.create_review_session(exam_context_id=exam.id, session_name="S",
                                       date_encountered=date.today(),
                                       total_questions=5, total_incorrect=3)
    entries = [db.create_question_entry(review_session_id=session.id, user_answer="x",
                                        correct_answer="y",
                                        primary_subject_ids=[child.id]).id for _ in range(3)]
    # Two filed under B, one under A.
    for eid, parent in zip(entries, (b.id, b.id, a.id)):
        db.execute("UPDATE entry_subject_mappings SET primary_parent_id = ?"
                   " WHERE question_entry_id = ?", (parent, eid))
    db.conn.commit()
    yield dict(db=db, a=a.id, b=b.id, c=c.id, child=child.id, entries=entries,
               edge_a=edge_a, edge_b=edge_b, edge_c=edge_c)
    db.close()


def _contexts(w):
    return [w["db"].fetchone("SELECT primary_parent_id FROM entry_subject_mappings"
                             " WHERE question_entry_id = ?", (e,))["primary_parent_id"]
            for e in w["entries"]]


def _edge_exists(w, edge_id):
    return w["db"].fetchone("SELECT 1 FROM subject_edges WHERE id = ?", (edge_id,)) is not None


def test_the_impact_counts_the_entries_and_lists_the_other_parents(world):
    impact = world["db"].get_remove_parent_impact(world["edge_b"])
    assert impact["pinned_entries"] == 2
    assert [r["parent_id"] for r in impact["remaining_parents"]] == [world["a"], world["c"]]
    assert impact["remaining_parents"][0]["is_primary"] is True
    assert world["db"].get_remove_parent_impact(999999) is None


def test_the_entries_go_where_the_student_chose(world):
    moved = world["db"].remove_edge(world["edge_b"], repin_to_parent_id=world["c"])
    assert moved == 2
    assert _contexts(world) == [world["c"], world["c"], world["a"]]
    assert not _edge_exists(world, world["edge_b"])


def test_with_no_choice_they_go_to_the_primary(world):
    """The old removeParent slot passes no target; it must still not orphan."""
    world["db"].remove_edge(world["edge_b"])
    assert _contexts(world) == [world["a"], world["a"], world["a"]]


def test_a_target_that_is_not_a_remaining_parent_removes_nothing(world):
    for bad in (world["b"], world["child"], 999999):
        with pytest.raises(ValidationError, match="other parents"):
            world["db"].remove_edge(world["edge_b"], repin_to_parent_id=bad)
    assert _edge_exists(world, world["edge_b"]), "a refused removal must leave the edge"
    assert _contexts(world) == [world["b"], world["b"], world["a"]]


def test_an_edge_nothing_is_filed_under_moves_nothing(world):
    assert world["db"].remove_edge(world["edge_c"]) == 0
    assert _contexts(world) == [world["b"], world["b"], world["a"]]


def test_removing_the_last_parent_clears_the_context(world):
    db = world["db"]
    db.remove_edge(world["edge_b"], repin_to_parent_id=world["a"])
    db.remove_edge(world["edge_c"])
    db.execute("UPDATE subject_edges SET is_primary = 0 WHERE id = ?", (world["edge_a"],))
    db.conn.commit()
    db.remove_edge(world["edge_a"])
    assert _contexts(world) == [None, None, None]
