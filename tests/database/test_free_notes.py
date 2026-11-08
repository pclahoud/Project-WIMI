"""A note on no entry, and what an entry's deletion does to its notes (#848 Wave 0).

The owner's four decisions (2026-11-04), one group of tests each:

1. ``add_free_note`` writes a row with a NULL origin and no junction row;
   ``get_entry_note`` and ``list_free_notes`` read it back.
2. Deleting an entry frees a note that another entry still holds and deletes
   a note held nowhere else -- on ``delete_question_entry``,
   ``delete_review_session`` and ``hard_delete_exam_context``.
3. A subject tag is optional; a tagged free note is offered by the picker
   while ``exclude_entry_id`` is set (the ``IS NULL`` clause's test).
4. Detaching a note from its originating entry clears the origin, and
   detaching the last attachment leaves a free note -- whichever entry the
   origin names (PR #864 round 2: a pre-m036 profile can hold a note whose
   origin is an entry it was detached from by the old Detach).

Fixtures follow ``tests/database/test_entry_notes.py``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from database.user_db import UserDatabase


@pytest.fixture
def world(tmp_path):
    """Two sessions in one exam, three entries, a second exam with one entry."""
    db = UserDatabase(str(tmp_path / "free_notes.db"), user_id=1, username="notes")

    exam = db.create_exam_context(
        exam_name="Notes Exam", exam_description="Free notes",
        hierarchy_levels=["System", "Topic"])
    subj1 = db.create_subject_node(exam_context=exam.exam_name, name="Cardiology",
                                   level_type="System")
    subj2 = db.create_subject_node(exam_context=exam.exam_name, name="Pulmonology",
                                   level_type="System")
    source = db.create_question_source(source_name="Src", source_type="textbook")

    def session(exam_id, name):
        return db.create_review_session(
            exam_context_id=exam_id, session_name=name,
            date_encountered=date.today(), total_questions=5, total_incorrect=2,
            question_source_id=source.id)

    def entry(sess):
        return db.create_question_entry(
            review_session_id=sess.id, user_answer="A", correct_answer="B",
            primary_subject_ids=[subj1.id])

    s1 = session(exam.id, "Session 1")
    s2 = session(exam.id, "Session 2")
    e1, e2 = entry(s1), entry(s1)
    e3 = entry(s2)

    other_exam = db.create_exam_context(
        exam_name="Other Exam", exam_description="Elsewhere",
        hierarchy_levels=["System"])
    s_other = session(other_exam.id, "Other session")
    e_other = db.create_question_entry(
        review_session_id=s_other.id, user_answer="A", correct_answer="B")

    yield {
        'db': db, 'exam': exam, 'other_exam': other_exam,
        'subj1': subj1, 'subj2': subj2,
        's1': s1, 's2': s2, 'e1': e1, 'e2': e2, 'e3': e3, 'e_other': e_other,
    }
    db.close()


def _junction(db, note_id):
    return {r['question_entry_id'] for r in db.fetchall(
        "SELECT question_entry_id FROM entry_note_attachments WHERE note_id = ?",
        (note_id,))}


def _origin(db, note_id):
    """The note's origin, ``None`` for a free note. A missing row RAISES:
    returning ``None`` for it too would let ``_origin(...) is None`` pass
    against a regression that deletes the shared note, which is the loss
    #848 exists to end (#862 item 1)."""
    row = db.fetchone("SELECT question_entry_id FROM entry_notes WHERE id = ?", (note_id,))
    assert row is not None, f"note {note_id} no longer exists"
    return row['question_entry_id']


def _exists(db, note_id):
    return db.fetchone("SELECT 1 FROM entry_notes WHERE id = ?", (note_id,)) is not None


# ---------------------------------------------------------------- decision 1


class TestAddFreeNote:
    def test_origin_is_none_and_no_junction_row_is_written(self, world):
        db = world['db']
        note = db.add_free_note(content_html="<p>free</p>",
                                linked_subject_ids=[world['subj1'].id])
        assert note.question_entry_id is None
        assert note.attachment_count == 0
        assert note.linked_subject_ids == [world['subj1'].id]
        assert _junction(db, note.id) == set()
        assert _origin(db, note.id) is None

    def test_a_tag_is_optional(self, world):
        note = world['db'].add_free_note(content_html="<p>untagged</p>")
        assert note.question_entry_id is None
        assert note.is_general

    def test_get_entry_note_reads_free_and_entry_notes(self, world):
        db = world['db']
        free = db.add_free_note(content_html="<p>free</p>")
        on_entry = db.add_entry_note(world['e1'].id, content_html="<p>on e1</p>")

        got_free = db.get_entry_note(free.id)
        assert got_free.id == free.id
        assert got_free.question_entry_id is None
        assert got_free.attachment_count == 0

        got_entry = db.get_entry_note(on_entry.id)
        assert got_entry.question_entry_id == world['e1'].id
        assert got_entry.attachment_count == 1

        assert db.get_entry_note(999_999) is None

    def test_list_free_notes_is_newest_first_by_updated_at_and_excludes_entry_notes(self, world):
        """The first-created note carries the later ``updated_at``, so the
        order is pinned to ``updated_at DESC`` and not to ``id DESC`` (the two
        agreed until PR #863's review noticed)."""
        db = world['db']
        first = db.add_free_note(content_html="<p>first, edited later</p>")
        second = db.add_free_note(content_html="<p>second</p>")
        db.add_entry_note(world['e1'].id, content_html="<p>entry note</p>")
        db.execute("UPDATE entry_notes SET updated_at = '2026-02-01 00:00:00' WHERE id = ?",
                   (first.id,))
        db.execute("UPDATE entry_notes SET updated_at = '2026-01-01 00:00:00' WHERE id = ?",
                   (second.id,))
        db.conn.commit()

        listed = db.list_free_notes()
        assert [n.id for n in listed] == [first.id, second.id]
        assert all(n.question_entry_id is None for n in listed)
        assert [n.attachment_count for n in listed] == [0, 0]

    def test_list_free_notes_honours_the_limit(self, world):
        db = world['db']
        for i in range(3):
            db.add_free_note(content_html=f"<p>{i}</p>")
        assert len(db.list_free_notes(limit=2)) == 2

    def test_update_clear_and_attach_work_on_a_free_note(self, world):
        """The existing writers reach a note by id, not through its origin."""
        db = world['db']
        note = db.add_free_note(content_html="<p>v1</p>")

        updated = db.update_entry_note(note.id, content_html="<p>v2</p>",
                                       linked_subject_ids=[world['subj2'].id])
        assert updated.content_html == "<p>v2</p>"
        assert updated.linked_subject_ids == [world['subj2'].id]
        assert updated.question_entry_id is None

        assert db.attach_existing_note_to_entry(note.id, world['e2'].id) is True
        assert [n.id for n in db.get_entry_notes_list(world['e2'].id)] == [note.id]
        assert _origin(db, note.id) is None
        assert db.get_entry_note(note.id).attachment_count == 1

        cleared = db.clear_entry_note(note.id)
        assert cleared.content_html == ''
        assert cleared.question_entry_id is None

        assert db.delete_entry_note(note.id) is True
        assert not _exists(db, note.id)


# ---------------------------------------------------------------- decision 3


class TestThePickerOffersAFreeNote:
    def test_a_tagged_free_note_is_returned_while_an_entry_is_excluded(self, world):
        """The ``IS NULL`` clause. Without it ``NULL != x`` is NULL and every
        free note vanishes from the picker on every entry; the mutant that
        deletes the clause fails exactly here."""
        db = world['db']
        free = db.add_free_note(content_html="<p>free</p>",
                                linked_subject_ids=[world['subj1'].id])
        own = db.add_entry_note(world['e1'].id, content_html="<p>own</p>",
                                linked_subject_ids=[world['subj1'].id])
        elsewhere = db.add_entry_note(world['e2'].id, content_html="<p>e2</p>",
                                      linked_subject_ids=[world['subj1'].id])

        offered = {n.id for n in db.get_notes_by_subjects(
            [world['subj1'].id], exclude_entry_id=world['e1'].id)}

        assert free.id in offered, "a free note must be offered on any entry"
        assert elsewhere.id in offered
        assert own.id not in offered, "the current entry's own note is still excluded"

    def test_the_deep_dive_call_without_exclusion_still_returns_it(self, world):
        db = world['db']
        free = db.add_free_note(content_html="<p>free</p>",
                                linked_subject_ids=[world['subj1'].id])
        assert free.id in {n.id for n in db.get_notes_by_subjects([world['subj1'].id])}

    def test_each_offered_note_carries_its_attachment_count(self, world):
        """#848 Wave 2a: the picker's row labels read the count, so the read
        attaches it the way ``list_free_notes`` does. Before this the
        serializer's ``getattr(note, 'attachment_count', 1)`` stood in for
        every picker row, and a free note on no entry read as being on one."""
        db = world['db']
        sid = world['subj1'].id
        free = db.add_free_note(content_html="<p>free</p>", linked_subject_ids=[sid])
        shared = db.add_entry_note(world['e2'].id, content_html="<p>shared</p>",
                                   linked_subject_ids=[sid])
        db.attach_existing_note_to_entry(shared.id, world['e3'].id)
        alone = db.add_entry_note(world['e3'].id, content_html="<p>alone</p>",
                                  linked_subject_ids=[sid])

        by_id = {n.id: n for n in db.get_notes_by_subjects(
            [sid], exclude_entry_id=world['e1'].id)}

        assert by_id[free.id].attachment_count == 0
        assert by_id[shared.id].attachment_count == 2
        assert by_id[alone.id].attachment_count == 1


# ---------------------------------------------------------------- decision 2


class TestDeletingTheOriginatingEntry:
    def test_a_note_held_elsewhere_is_freed_and_stays_there(self, world):
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>shared</p>")
        db.attach_existing_note_to_entry(note.id, world['e3'].id)

        assert db.delete_question_entry(world['e1'].id) is True

        assert _exists(db, note.id)
        assert _origin(db, note.id) is None
        assert _junction(db, note.id) == {world['e3'].id}
        assert [n.id for n in db.get_entry_notes_list(world['e3'].id)] == [note.id]
        assert db.get_entry_note(note.id).attachment_count == 1
        assert note.id in {n.id for n in db.list_free_notes()}

    def test_a_note_held_only_there_is_deleted(self, world):
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>only here</p>")

        db.delete_question_entry(world['e1'].id)

        assert not _exists(db, note.id)
        assert _junction(db, note.id) == set()
        assert db.list_free_notes() == []

    def test_a_note_on_another_entry_but_born_elsewhere_is_untouched(self, world):
        """Deleting an entry a note was merely attached to is the junction's
        cascade, not this rule: the note keeps its origin."""
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>born on e1</p>")
        db.attach_existing_note_to_entry(note.id, world['e2'].id)

        db.delete_question_entry(world['e2'].id)

        assert _origin(db, note.id) == world['e1'].id
        assert _junction(db, note.id) == {world['e1'].id}

    def test_the_helper_frees_and_deletes_in_one_call(self, world):
        db = world['db']
        kept = db.add_entry_note(world['e1'].id, content_html="<p>kept</p>")
        db.attach_existing_note_to_entry(kept.id, world['e3'].id)
        gone = db.add_entry_note(world['e2'].id, content_html="<p>gone</p>")

        with db.transaction():
            result = db.release_notes_from_entries([world['e1'].id, world['e2'].id])

        assert result == {'deleted_note_ids': [gone.id], 'freed_note_ids': [kept.id]}
        assert db.release_notes_from_entries([]) == {'deleted_note_ids': [], 'freed_note_ids': []}


class TestDeletingASession:
    def test_a_note_held_only_by_the_sessions_entries_is_deleted(self, world):
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>s1 only</p>")
        db.attach_existing_note_to_entry(note.id, world['e2'].id)

        assert db.delete_review_session(world['s1'].id) is True

        assert not _exists(db, note.id)
        assert db.list_free_notes() == []

    def test_a_note_also_on_another_sessions_entry_survives_freed(self, world):
        db = world['db']
        note = db.add_entry_note(world['e2'].id, content_html="<p>shared across</p>")
        db.attach_existing_note_to_entry(note.id, world['e3'].id)

        db.delete_review_session(world['s1'].id)

        assert _exists(db, note.id)
        assert _origin(db, note.id) is None
        assert _junction(db, note.id) == {world['e3'].id}
        assert [n.id for n in db.get_entry_notes_list(world['e3'].id)] == [note.id]


class TestHardDeletingAnExam:
    def _suspend(self, db, exam_id):
        db.execute("UPDATE exam_contexts SET is_active = 0 WHERE id = ?", (exam_id,))
        db.conn.commit()

    def test_a_note_held_only_in_the_exam_is_deleted(self, world):
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>exam only</p>")
        db.attach_existing_note_to_entry(note.id, world['e3'].id)
        self._suspend(db, world['exam'].id)

        db.hard_delete_exam_context(world['exam'].id)

        assert not _exists(db, note.id)

    def test_an_exam_past_one_chunk_releases_every_entrys_notes(self, world):
        """``release_notes_from_entries`` reads origins 500 ids at a time, and
        only an exam with more than 500 entries reaches a second chunk. Every
        entry carries a note born on it alone, so an off-by-one anywhere in
        the chunking leaves at least one behind as a stray free note (#862
        item 2). One more, born in the exam and also on the other exam's
        entry, must come out freed, not deleted."""
        db = world['db']
        for i in range(510):
            db.execute(
                "INSERT INTO question_entries (review_session_id, entry_order, "
                "user_answer, correct_answer) VALUES (?, ?, 'A', 'B')",
                (world['s1'].id, 100 + i))
        entry_ids = [r['id'] for r in db.fetchall(
            "SELECT qe.id FROM question_entries qe JOIN review_sessions rs "
            "ON rs.id = qe.review_session_id WHERE rs.exam_context_id = ?",
            (world['exam'].id,))]
        assert len(entry_ids) > 500, "the premise: more than one chunk"
        for eid in entry_ids:
            db.execute(
                "INSERT INTO entry_notes (question_entry_id, content_html) VALUES (?, 'n')",
                (eid,))
            nid = db.fetchone("SELECT last_insert_rowid() AS id")['id']
            db.execute(
                "INSERT INTO entry_note_attachments (question_entry_id, note_id) VALUES (?, ?)",
                (eid, nid))
        db.conn.commit()
        shared = db.add_entry_note(entry_ids[-1], content_html="<p>cross exam, last</p>")
        db.attach_existing_note_to_entry(shared.id, world['e_other'].id)
        self._suspend(db, world['exam'].id)

        db.hard_delete_exam_context(world['exam'].id)

        left = db.fetchall("SELECT id, question_entry_id FROM entry_notes")
        assert [r['id'] for r in left] == [shared.id], (
            f"{len(left) - 1} notes born in the deleted exam survived: {[dict(r) for r in left][:5]}")
        assert _origin(db, shared.id) is None
        assert _junction(db, shared.id) == {world['e_other'].id}

    def test_a_note_also_on_another_exams_entry_survives_freed(self, world):
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>cross exam</p>")
        db.attach_existing_note_to_entry(note.id, world['e_other'].id)
        self._suspend(db, world['exam'].id)

        db.hard_delete_exam_context(world['exam'].id)

        assert _origin(db, note.id) is None
        assert _junction(db, note.id) == {world['e_other'].id}


# ---------------------------------------------------------------- decision 4


class TestAFreeNoteOutlivesTheEntriesItSitsOn:
    def test_deleting_the_last_entry_a_free_note_sits_on_leaves_it_unattached(self, world):
        """Decision 2 deletes a note only with its ORIGIN, never with an entry
        it merely sits on. A free note's origin is NULL, so deleting the last
        entry holding it leaves it with no attachment at all, still listed
        under Your notes. That is the design; it was recorded nowhere until
        #862 item 5."""
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>untagged</p>")
        db.attach_existing_note_to_entry(note.id, world['e3'].id)
        db.detach_note_from_entry(note.id, world['e1'].id)
        assert _origin(db, note.id) is None and _junction(db, note.id) == {world['e3'].id}

        db.delete_question_entry(world['e3'].id)

        assert _exists(db, note.id), "a free note was deleted with an entry it only sat on"
        assert _junction(db, note.id) == set()
        assert [n.id for n in db.list_free_notes()] == [note.id]


class TestDetach:
    def test_detaching_from_the_origin_clears_it_and_keeps_the_other(self, world):
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>two homes</p>")
        db.attach_existing_note_to_entry(note.id, world['e3'].id)

        assert db.detach_note_from_entry(note.id, world['e1'].id) is True

        assert _origin(db, note.id) is None
        assert _junction(db, note.id) == {world['e3'].id}
        assert db.get_entry_notes_list(world['e1'].id) == []
        assert [n.id for n in db.get_entry_notes_list(world['e3'].id)] == [note.id]

    def test_detaching_from_a_non_origin_entry_keeps_the_origin(self, world):
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>born on e1</p>")
        db.attach_existing_note_to_entry(note.id, world['e3'].id)

        assert db.detach_note_from_entry(note.id, world['e3'].id) is True

        assert _origin(db, note.id) == world['e1'].id
        assert _junction(db, note.id) == {world['e1'].id}

    def test_detaching_the_last_attachment_leaves_a_free_note(self, world):
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>keep me</p>",
                                 linked_subject_ids=[world['subj1'].id])

        assert db.detach_note_from_entry(note.id, world['e1'].id) is True

        assert _exists(db, note.id)
        assert _origin(db, note.id) is None
        assert _junction(db, note.id) == set()
        assert db.get_entry_notes_list(world['e1'].id) == []
        assert [n.id for n in db.list_free_notes()] == [note.id]
        # And the entry's later deletion no longer reaches it.
        db.delete_question_entry(world['e1'].id)
        assert _exists(db, note.id)

    def test_detaching_a_note_that_was_never_attached_is_false(self, world):
        db = world['db']
        note = db.add_free_note(content_html="<p>free</p>")
        assert db.detach_note_from_entry(note.id, world['e1'].id) is False

    def test_the_last_attachment_frees_a_note_whose_origin_is_another_entry(self, world):
        """The pre-m036 shape PR #864 round 2 found: born on e1, attached to e3
        through + Add existing, detached from e1 by the OLD Detach, which
        removed only the junction row and left the origin at e1. m036 leaves
        that origin alone because e1 still exists. Keep as a note on its own
        on e3 removes the note's last attachment, so it must become a free
        note: under Your notes, and NOT back on e1 through the legacy
        fallback (origin matches, no junction row) -- the entry the student
        had deliberately taken it off."""
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>born on e1, kept on e3</p>",
                                 linked_subject_ids=[world['subj1'].id])
        db.attach_existing_note_to_entry(note.id, world['e3'].id)
        with db.transaction():
            db.execute(
                "DELETE FROM entry_note_attachments WHERE note_id = ? AND question_entry_id = ?",
                (note.id, world['e1'].id))
        assert _origin(db, note.id) == world['e1'].id, "arrange: the old Detach left the origin"
        assert _junction(db, note.id) == {world['e3'].id}, "arrange: only e3 holds it"
        assert db.get_entry_notes_list(world['e1'].id) == [], "arrange: e3's row keeps it off e1"

        assert db.detach_note_from_entry(note.id, world['e3'].id) is True

        assert _exists(db, note.id), "Keep deleted the note"
        assert _origin(db, note.id) is None, "the origin still names e1 after the last attachment went"
        assert _junction(db, note.id) == set()
        assert [n.id for n in db.list_free_notes()] == [note.id], (
            "the note is not under Your notes, which is where the page's toast sends the student")
        assert db.get_entry_notes_list(world['e1'].id) == [], (
            "the note is back on e1 through the legacy fallback, the entry it was detached from")
        assert db.get_entry_notes_list(world['e3'].id) == []
        row = db.fetchone("SELECT linked_subject_ids FROM entry_notes WHERE id = ?", (note.id,))
        assert json.loads(row['linked_subject_ids']) == [world['subj1'].id], "Keep lost the tags"
        # And neither entry's deletion reaches it any more.
        db.delete_question_entry(world['e1'].id)
        db.delete_question_entry(world['e3'].id)
        assert _exists(db, note.id)

    def test_a_detach_that_removed_nothing_leaves_a_foreign_origin_alone(self, world):
        """The negative control for the clause above: the origin goes only
        when THIS call removed the note's last attachment. A row with origin
        e1 and no junction row at all (the legacy fallback's own shape, which
        still shows on e1) is not freed by a detach from e3 that removed
        nothing -- that call is a no-op and says so."""
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html="<p>legacy row</p>")
        with db.transaction():
            db.execute("DELETE FROM entry_note_attachments WHERE note_id = ?", (note.id,))
        assert [n.id for n in db.get_entry_notes_list(world['e1'].id)] == [note.id], (
            "arrange: the legacy fallback shows an origin-only row on its entry")

        assert db.detach_note_from_entry(note.id, world['e3'].id) is False

        assert _origin(db, note.id) == world['e1'].id
        assert [n.id for n in db.get_entry_notes_list(world['e1'].id)] == [note.id]
        assert db.list_free_notes() == []


# ---------------------------------------------------------------- logger


def test_every_new_write_path_survives_a_real_logger(tmp_path):
    """Every fixture here builds the database with ``error_logger=None``, so
    the ``if self.error_logger:`` branches on these paths never run above.
    ``ErrorLogger.log`` takes ``level`` first, which is how
    ``log(message, level=...)`` once shipped as a TypeError under passing
    tests (``test_relation_confirmation.py`` records it). Attach a real one
    and call each new path once."""
    from app_logging import ErrorLogger
    from database import MasterDatabase

    logger = ErrorLogger(app_name='FreeNoteWriteTest',
                         log_dir=tmp_path / 'logs', flush_interval=60.0)
    master = MasterDatabase(data_dir=tmp_path / 'app_data', error_logger=logger)
    user = master.create_user(username='logged', display_name='L',
                              user_types=['student'])
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username,
                      error_logger=logger)
    try:
        assert db.error_logger is not None, 'the premise of this test'
        exam = db.create_exam_context('Logged Exam')
        source = db.create_question_source(source_name='Src', source_type='textbook')
        s1 = db.create_review_session(exam_context_id=exam.id, total_questions=3,
                                      total_incorrect=1, question_source_id=source.id,
                                      date_encountered=date.today())
        s2 = db.create_review_session(exam_context_id=exam.id, total_questions=3,
                                      total_incorrect=1, question_source_id=source.id,
                                      date_encountered=date.today())
        e1 = db.create_question_entry(review_session_id=s1.id, user_answer='A',
                                      correct_answer='B')
        e2 = db.create_question_entry(review_session_id=s1.id, user_answer='A',
                                      correct_answer='B')
        e3 = db.create_question_entry(review_session_id=s2.id, user_answer='A',
                                      correct_answer='B')

        free = db.add_free_note(content_html='<p>free</p>')
        assert free.question_entry_id is None

        shared = db.add_entry_note(e1.id, content_html='<p>shared</p>')
        db.attach_existing_note_to_entry(shared.id, e3.id)
        db.detach_note_from_entry(shared.id, e1.id)
        assert _origin(db, shared.id) is None

        alone = db.add_entry_note(e2.id, content_html='<p>alone</p>')
        db.delete_question_entry(e2.id)
        assert not _exists(db, alone.id)

        db.add_entry_note(e1.id, content_html='<p>session note</p>')
        db.delete_review_session(s1.id)
        assert _exists(db, shared.id)
    finally:
        db.close()
        master.close()
        logger.cleanup()
