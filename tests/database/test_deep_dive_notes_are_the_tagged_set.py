"""The deep dive collects notes TAGGED with the subject, and only those (#465).

The owner settled the direction on 2026-10-07 (*"notes should appear in a
subject deep dive"*) and the design on 2026-10-10. Of three candidate
meanings for "this subject's notes" the strict one was chosen: a note whose
own ``linked_subject_ids`` names this subject.

**Two of the three tests here are discriminators, and without them the
feature passes under the wrong rule.** A test that only checks "a tagged
note appears" is satisfied by every one of the three designs:

* ``test_a_note_on_a_tagged_entry_is_not_collected`` separates STRICT from
  PERMISSIVE. The permissive reading -- every note on any entry tagged with
  this subject -- is what the rest of this page does for *entries*, and it
  is the reading somebody will "fix" this to, because it would make the
  page internally consistent. It is deliberately not the rule.
* ``test_a_descendants_note_is_not_inherited`` separates it from the
  inheriting variant. Entries DO roll up through descendants on this page,
  so this is the other obvious thing to make consistent.

The asymmetry is intentional and is recorded at the call site: a note is
filed by hand at one subject, an entry's rollup is derived. Do not
consolidate these tests, and do not "fix" the page to agree with itself.
"""
from __future__ import annotations

import json
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
        username="notes_user",
        display_name="Notes User",
        user_types=["student"],
    )
    db = UserDatabase(
        db_path=master_db.ensure_user_database(user.id),
        user_id=user.id,
        username=user.username,
    )
    db._ensure_phase2_schema()
    yield db
    db.close()


def _exam(user_db):
    return user_db.create_exam_context(
        exam_name="Notes Exam",
        exam_description="#465 - notes tagged with this subject",
    )


def _subject(user_db, exam, name, parent=None):
    node = user_db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name=name, level_type="Topic",
        parent_id=parent, relative_weight=5, weight_source="user_defined")
    return node.id


def _entry_on(user_db, exam, subject_id):
    ec = user_db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = ?",
        (exam.exam_name,))["id"]
    session = user_db.execute(
        "INSERT INTO review_sessions (user_id, session_name, "
        "date_encountered, exam_context_id, total_questions, total_incorrect) "
        "VALUES (?, 'S', date('now'), ?, 1, 1)", (user_db.user_id, ec),
    ).lastrowid
    entry = user_db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer) VALUES (?, 1, 'A', 'B')", (session,),
    ).lastrowid
    user_db.execute(
        "INSERT INTO entry_subject_mappings (question_entry_id, "
        "subject_node_id, mapping_type) VALUES (?, ?, 'primary')",
        (entry, subject_id))
    user_db.conn.commit()
    return entry


def _note(user_db, entry_id, text, tagged_with=None):
    user_db.execute(
        "INSERT INTO entry_notes (question_entry_id, content_html, "
        "sort_order, linked_subject_ids) VALUES (?, ?, 0, ?)",
        (entry_id, f"<p>{text}</p>",
         json.dumps(tagged_with) if tagged_with else None),
    )
    user_db.conn.commit()


def _note_texts(dive):
    return [n["content_html"] for n in dive["notes"]]


def test_a_note_tagged_with_the_subject_is_collected(user_db):
    exam = _exam(user_db)
    subject = _subject(user_db, exam, "Hyperkalemia")
    entry = _entry_on(user_db, exam, subject)
    _note(user_db, entry, "peaked T waves", tagged_with=[subject])

    dive = user_db.get_subject_deep_dive(subject, exam_context_id=exam.id)

    assert dive is not None
    assert "notes" in dive, (
        "the payload carried no notes key at all before #465, and a class "
        "name on another list is what made everyone think otherwise")
    assert any("peaked T waves" in html for html in _note_texts(dive)), (
        f"a note tagged with this subject must be collected: {dive['notes']!r}")


def test_a_note_on_a_tagged_entry_is_not_collected(user_db):
    """STRICT vs PERMISSIVE. The discriminator that matters most.

    The entry is tagged with the subject, so the permissive reading would
    collect its note. The note itself carries no subject tags. Under the
    owner's decision it must NOT appear -- otherwise the list is "every
    note near this subject" rather than "the notes I filed here".
    """
    exam = _exam(user_db)
    subject = _subject(user_db, exam, "Hyperkalemia")
    entry = _entry_on(user_db, exam, subject)
    _note(user_db, entry, "untagged scribble", tagged_with=None)

    dive = user_db.get_subject_deep_dive(subject, exam_context_id=exam.id)

    assert dive["notes"] == [], (
        "an untagged note on a tagged entry is the PERMISSIVE set, which "
        f"this page uses for entries and must not use for notes: "
        f"{dive['notes']!r}")


def test_a_descendants_note_is_not_inherited(user_db):
    """No inheritance, although entries on this page DO roll up.

    A note tagged only with the child must not surface on the parent. The
    inheriting variant was offered and not taken: it would make a root
    subject's panel the whole exam.
    """
    exam = _exam(user_db)
    parent = _subject(user_db, exam, "Electrolytes")
    child = _subject(user_db, exam, "Hyperkalemia", parent=parent)
    entry = _entry_on(user_db, exam, child)
    _note(user_db, entry, "child note", tagged_with=[child])

    parent_dive = user_db.get_subject_deep_dive(
        parent, exam_context_id=exam.id)
    child_dive = user_db.get_subject_deep_dive(child, exam_context_id=exam.id)

    # The child's own panel is the positive control: without it, a bug that
    # collected nothing at all would pass this test.
    assert any("child note" in html for html in _note_texts(child_dive)), (
        "the child's own note is missing, so the absence below proves "
        f"nothing: {child_dive['notes']!r}")
    assert parent_dive["notes"] == [], (
        "a descendant's note must not be inherited, although entries are: "
        f"{parent_dive['notes']!r}")


def test_a_subject_with_no_tagged_notes_reports_an_empty_list(user_db):
    """Empty list, never absent -- the page branches on length."""
    exam = _exam(user_db)
    subject = _subject(user_db, exam, "Quiet Topic")

    dive = user_db.get_subject_deep_dive(subject, exam_context_id=exam.id)

    assert dive["notes"] == [], f"expected [], got {dive['notes']!r}"
