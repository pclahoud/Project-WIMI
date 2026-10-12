"""A rejected proposal is remembered, and its KIND decides its scope (#60, m027).

#14's decision 8 proposed `strength = -1` on `subject_relations` for
"checked: not related". m027 records the measurement that makes that the wrong
mechanism for #60: of 45 rejections in that issue's adjudication, **25 meant
"you misread my sentence"**, not "these two are unrelated".

The two kinds have different scopes, and that difference is the entire reason
this is a table:

* `misread` is about one piece of text. The same pair may extract perfectly
  from a different explanation tomorrow, so suppressing it anywhere else would
  throw away a true relation because one sentence was parsed badly.
* `not_related` is about the two subjects. Suppressing it only for one entry
  would re-ask a question the student has already answered.

So the scope pair of tests below is the file's centre. A sentinel would have
globally suppressed 25 of those 45 pairs; `test_a_misread_does_not_suppress...`
is what notices if this ever regresses to that behaviour.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from database.base_db import DatabaseIntegrityError
from database.exceptions import ValidationError
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=Path(tmpdir))
        user = master.create_user(
            username='reject_user', display_name='Reject',
            user_types=['student'])
        db = UserDatabase(
            db_path=master.ensure_user_database(user.id),
            user_id=user.id, username=user.username)
        try:
            yield db
        finally:
            db.close()
            master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context('USMLE').id


def _node(user_db, name: str) -> int:
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, "
        "sort_order, status) VALUES ('USMLE', ?, 'Topic', NULL, 0, 'active')",
        (name,))
    user_db.conn.commit()
    return cursor.lastrowid


def _type_id(user_db, exam_id: int, label: str) -> int:
    for t in user_db.get_relation_types(exam_id, include_retired=True):
        if t['label'] == label:
            return t['id']
    raise AssertionError(f'no seeded type {label!r}')


def _entry(user_db, exam_id: int, order: int = 1) -> int:
    """A minimal real entry, because m027's source_entry_id is a real FK.

    My first version of this file invented ids like 41 and 7, and five tests
    failed with FOREIGN KEY constraint failed -- the constraint doing its job
    on a fixture that was wrong. A misread names the text it is about, so an
    entry that does not exist is exactly what should be refused.
    """
    session = user_db.execute(
        "INSERT INTO review_sessions (user_id, exam_context_id, "
        "total_questions, total_incorrect) VALUES (1, ?, 1, 1)",
        (exam_id,)).lastrowid
    cursor = user_db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer) VALUES (?, ?, 'a', 'b')",
        (session, order))
    user_db.conn.commit()
    return cursor.lastrowid


@pytest.fixture
def entries(user_db, exam):
    """Two distinct entries, for the scope tests."""
    return _entry(user_db, exam, 1), _entry(user_db, exam, 2)


@pytest.fixture
def pair(user_db, exam):
    return _node(user_db, 'Chronic hypertension'), _node(user_db, 'Stroke')


# --------------------------------------------------------------------------
# The scope rule. This is the point of the table.
# --------------------------------------------------------------------------

def test_a_misread_suppresses_its_own_entry(user_db, exam, pair, entries):
    a, b = pair
    mine, _other = entries
    kind_id = _type_id(user_db, exam, 'causes')
    user_db.record_relation_rejection(
        a, b, kind='misread', relation_type_id=kind_id,
        source_entry_id=mine, passage='...hypertension and stroke...')

    assert user_db.is_relation_rejected(
        a, b, relation_type_id=kind_id, source_entry_id=mine)


def test_a_misread_does_not_suppress_a_different_entry(user_db, exam, pair, entries):
    """The 25-of-45 case, and the one a sentinel got wrong.

    "You misread my sentence" is a statement about one piece of text. The same
    pair may extract perfectly from tomorrow's explanation, and suppressing it
    there would discard a true relation on the strength of one bad parse.
    """
    a, b = pair
    mine, other = entries
    kind_id = _type_id(user_db, exam, 'causes')
    user_db.record_relation_rejection(
        a, b, kind='misread', relation_type_id=kind_id, source_entry_id=mine)

    assert not user_db.is_relation_rejected(
        a, b, relation_type_id=kind_id, source_entry_id=other)
    assert not user_db.is_relation_rejected(
        a, b, relation_type_id=kind_id, source_entry_id=None)


def test_not_related_suppresses_everywhere(user_db, exam, pair, entries):
    """A claim about the two subjects, true whatever any explanation says.

    Including for an entry it was never recorded against, and when no entry is
    in play at all -- otherwise the student is re-asked a question they have
    answered, every time they write about either subject.
    """
    a, b = pair
    mine, other = entries
    kind_id = _type_id(user_db, exam, 'causes')
    user_db.record_relation_rejection(
        a, b, kind='not_related', relation_type_id=kind_id, source_entry_id=mine)

    for entry in (mine, other, None):
        assert user_db.is_relation_rejected(
            a, b, relation_type_id=kind_id, source_entry_id=entry), entry


def test_a_rejection_is_specific_to_the_type(user_db, exam, pair):
    """The seed list makes two types on one pair ordinary.

    *A causes B* being wrong says nothing about *A confused with B*, which is
    why m026 widened the uniqueness to include the type.
    """
    a, b = pair
    causes = _type_id(user_db, exam, 'causes')
    confused = _type_id(user_db, exam, 'confused with')
    user_db.record_relation_rejection(
        a, b, kind='not_related', relation_type_id=causes)

    assert user_db.is_relation_rejected(a, b, relation_type_id=causes)
    assert not user_db.is_relation_rejected(a, b, relation_type_id=confused)


# --------------------------------------------------------------------------
# Symmetry
# --------------------------------------------------------------------------

def test_a_symmetric_rejection_suppresses_both_directions(user_db, exam, pair):
    """Rejecting *A confused with B* must also suppress *B confused with A*.

    They are the same relation. Without canonicalisation the student is asked
    the identical question again from the other end, which is the thing most
    likely to make the feature feel broken.
    """
    a, b = pair
    confused = _type_id(user_db, exam, 'confused with')
    assert any(t['label'] == 'confused with' and t['is_symmetric']
               for t in user_db.get_relation_types(exam)), (
        'this test is meaningless unless "confused with" is symmetric')

    user_db.record_relation_rejection(
        b, a, kind='not_related', relation_type_id=confused)

    assert user_db.is_relation_rejected(a, b, relation_type_id=confused)
    assert user_db.is_relation_rejected(b, a, relation_type_id=confused)


def test_an_asymmetric_rejection_leaves_the_other_direction_alone(
        user_db, exam, pair):
    """Decision 7: A->B and B->A are different claims and both may be true.

    The negative control for the symmetric test above. Without it a
    canonicalise-everything implementation would pass.
    """
    a, b = pair
    causes = _type_id(user_db, exam, 'causes')
    user_db.record_relation_rejection(
        a, b, kind='not_related', relation_type_id=causes)

    assert user_db.is_relation_rejected(a, b, relation_type_id=causes)
    assert not user_db.is_relation_rejected(b, a, relation_type_id=causes)


def test_canonicalising_in_python_is_what_keeps_the_trigger_quiet(
        user_db, exam, pair):
    """The control proving the canonicalisation is load-bearing, not tidy.

    m027 repeats m026's symmetric triggers. Inserting the non-canonical
    spelling directly, bypassing the domain method, must raise -- so the
    method ordering the pair first is the only reason a caller gets a
    sentence instead of `RAISE(ABORT)` surfacing as an opaque integrity
    error (#66 2.2).
    """
    a, b = pair
    confused = _type_id(user_db, exam, 'confused with')
    high, low = max(a, b), min(a, b)

    with pytest.raises(Exception) as exc:
        user_db.execute(
            "INSERT INTO subject_relation_rejections "
            "(from_subject_id, to_subject_id, relation_type_id, kind) "
            "VALUES (?, ?, ?, 'not_related')",
            (high, low, confused),
        )
    assert 'symmetric' in str(exc.value).lower()


# --------------------------------------------------------------------------
# The kind is mandatory, and refusals are sentences
# --------------------------------------------------------------------------

def test_the_kind_has_no_default(user_db, exam, pair):
    """A rejection whose kind nobody recorded cannot be scoped.

    Guessing is precisely how the sentinel behaved, so `kind` is
    keyword-only with no default: omitting it is a TypeError at the call
    site rather than a row that suppresses the wrong thing.
    """
    a, b = pair
    with pytest.raises(TypeError):
        user_db.record_relation_rejection(a, b)


def test_an_unknown_kind_is_refused_with_both_kinds_explained(
        user_db, exam, pair):
    a, b = pair
    with pytest.raises(ValidationError) as exc:
        user_db.record_relation_rejection(a, b, kind='wrong_type')
    message = str(exc.value)
    assert 'misread' in message and 'not_related' in message
    assert 'no safe default' in message


def test_a_misread_without_an_entry_is_refused_as_a_sentence(
        user_db, exam, pair):
    """The schema's CHECK re-checked in Python, for #66 2.2's reason.

    `CHECK (kind <> 'misread' OR source_entry_id IS NOT NULL)` would catch
    it, but as a `DatabaseIntegrityError` from three frames down. A misread
    with no entry could never be matched by the suppression query and would
    sit there suppressing nothing, silently -- so the message says what to
    use instead.
    """
    a, b = pair
    with pytest.raises(ValidationError) as exc:
        user_db.record_relation_rejection(a, b, kind='misread')
    assert 'not_related' in str(exc.value)

    # And it really is a ValidationError rather than the schema's refusal.
    assert not isinstance(exc.value, DatabaseIntegrityError)


def test_a_self_loop_is_refused(user_db, exam, pair):
    a, _ = pair
    with pytest.raises(ValidationError):
        user_db.record_relation_rejection(a, a, kind='not_related')


def test_an_unknown_type_is_refused(user_db, exam, pair):
    a, b = pair
    with pytest.raises(ValidationError):
        user_db.record_relation_rejection(
            a, b, kind='not_related', relation_type_id=99999)


# --------------------------------------------------------------------------
# Untyped, archived, and undo
# --------------------------------------------------------------------------

def test_an_untyped_rejection_is_matched_with_is_not_equals(user_db, exam, pair):
    """`relation_type_id = ?` never matches NULL in SQLite.

    An untyped proposal is legitimate -- #14's relations predate types and
    stay untyped until edited -- so the suppression query uses `IS`. Written
    with `=` this test fails while every typed test still passes, which is
    the kind of gap worth a test of its own.
    """
    a, b = pair
    user_db.record_relation_rejection(a, b, kind='not_related')

    assert user_db.is_relation_rejected(a, b, relation_type_id=None)
    assert (a, b, None) in user_db.rejected_pairs_for_entry(None)


def test_an_archived_endpoint_is_allowed(user_db, exam, pair):
    """Deliberate, and m027 keeps no cascade for the same reason.

    Subject deletion is soft (#15). The student's judgement about a pair did
    not stop being true while one of them was archived, and a restored
    subject keeps its rejections.
    """
    a, b = pair
    user_db.execute(
        "UPDATE subject_nodes SET status = 'archived' WHERE id = ?", (b,))
    user_db.conn.commit()

    recorded = user_db.record_relation_rejection(a, b, kind='not_related')
    assert recorded['id']


def test_a_rejection_can_be_undone(user_db, exam, pair):
    """A hard delete, like `delete_subject_relation`.

    A tombstone would mean a student who changed their mind could never be
    offered the proposal again -- the sentinel's failure mode in a third hat.
    """
    a, b = pair
    recorded = user_db.record_relation_rejection(a, b, kind='not_related')

    assert user_db.is_relation_rejected(a, b)
    assert user_db.delete_relation_rejection(recorded['id']) is True
    assert not user_db.is_relation_rejected(a, b)
    assert user_db.delete_relation_rejection(recorded['id']) is False


def test_the_recorded_row_keeps_the_passage(user_db, exam, pair, entries):
    """Provenance. m027 keeps it so extraction quality can be reviewed later
    against the text that produced the bad proposal."""
    a, b = pair
    mine, _other = entries
    recorded = user_db.record_relation_rejection(
        a, b, kind='misread', source_entry_id=mine,
        passage='Chronic hypertension and stroke both appear here.')
    assert recorded['passage'].startswith('Chronic hypertension and stroke')
    assert recorded['source_entry_id'] == mine
    assert recorded['kind'] == 'misread'


# --------------------------------------------------------------------------
# The batch form
# --------------------------------------------------------------------------

def test_listing_by_entry_is_not_the_same_question_as_suppression(
        user_db, exam, pair, entries):
    """Two different questions, and conflating them is the easy mistake.

    `list_relation_rejections(source_entry_id=N)` is "what was recorded
    against N". `rejected_pairs_for_entry(N)` is "what is suppressed when
    extracting from N" -- which includes every `not_related` recorded
    anywhere.
    """
    a, b = pair
    mine, other = entries
    c = _node(user_db, 'Aortic dissection')
    user_db.record_relation_rejection(
        a, b, kind='misread', source_entry_id=mine)
    user_db.record_relation_rejection(
        a, c, kind='not_related', source_entry_id=other)

    recorded_here = user_db.list_relation_rejections(source_entry_id=mine)
    assert [r['kind'] for r in recorded_here] == ['misread']

    suppressed_here = user_db.rejected_pairs_for_entry(mine)
    assert (a, b, None) in suppressed_here, 'its own misread'
    assert (a, c, None) in suppressed_here, (
        "a not_related recorded against another entry still suppresses here")


def test_the_batch_form_agrees_with_the_single_form(user_db, exam, pair):
    """`is_relation_rejected` is documented as the single-pair form of
    `rejected_pairs_for_entry`, and a caller filtering a batch is told to
    prefer the set. They must not disagree."""
    a, b = pair
    confused = _type_id(user_db, exam, 'confused with')
    user_db.record_relation_rejection(
        b, a, kind='not_related', relation_type_id=confused)

    pairs = user_db.rejected_pairs_for_entry(None)
    # The set holds the canonical order; the single form canonicalises first,
    # so both spellings answer True through it.
    assert (min(a, b), max(a, b), confused) in pairs
    assert user_db.is_relation_rejected(a, b, relation_type_id=confused)
    assert user_db.is_relation_rejected(b, a, relation_type_id=confused)


def test_a_nonexistent_entry_is_a_sentence_not_an_integrity_error(
        user_db, exam, pair):
    """How this test file's own first draft failed, turned into behaviour.

    m027 declares `source_entry_id REFERENCES question_entries(id)`, so an
    invented id already failed -- as `DatabaseIntegrityError: FOREIGN KEY
    constraint failed`, from inside `execute`, naming neither the column nor
    the value. Five tests here hit exactly that before the fixture was fixed:
    the constraint was working and the diagnosis was useless.

    #66 2.2 asks for a sentence instead, which is the same reason the
    `misread` CHECK is re-checked in Python rather than left to the schema.
    """
    a, b = pair
    with pytest.raises(ValidationError) as exc:
        user_db.record_relation_rejection(
            a, b, kind='misread', source_entry_id=999_999)

    assert '999999' in str(exc.value).replace(',', '')
    assert not isinstance(exc.value, DatabaseIntegrityError)
