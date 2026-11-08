"""The three slots that let a page reach a free note (#848 Wave 1).

``addNote`` creates a note on no entry -- the int-typed ``addEntryNote`` cannot
carry a NULL origin -- ``getNote`` reads one note by id, and ``listFreeNotes``
lists the notes whose origin is NULL, newest first. The bridge is built the
way ``tests/app/test_bridge.py`` builds it: ``DatabaseBridge(master_db=...,
user_db=...)``, slots called as plain methods, ``json.loads`` on the reply, no
``QApplication``.

Two rules the assertions lean on:

- ``serialize_response`` leaves ``data`` ABSENT, not null, when a slot passes
  ``None`` (CLAUDE.md, measured 2026-10-12), so every read here is ``.get``.
- ``_serialize_entry_note`` omits ``question_entry_id`` for a free note and
  carries the integer for an entry note (Wave 0, PR #861).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase

REPO_ROOT = Path(__file__).resolve().parents[2]


# ==================== Fixtures ====================

@pytest.fixture
def user_db(tmp_path) -> Generator[UserDatabase, None, None]:
    db = UserDatabase(db_path=tmp_path / 'free_notes_bridge.db', user_id=1,
                      username='free_notes')
    yield db
    db.close()


@pytest.fixture
def master_db(tmp_path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=tmp_path / 'master', error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    master_db.bootstrap_first_user(username='test_admin', display_name='Test Admin')
    return DatabaseBridge(master_db=master_db, user_db=user_db)


@pytest.fixture
def no_db_bridge(master_db: MasterDatabase) -> DatabaseBridge:
    """The guard path: a bridge with no user database attached."""
    return DatabaseBridge(master_db=master_db, user_db=None)


@pytest.fixture
def world(bridge: DatabaseBridge) -> dict:
    """One exam, one subject, one session, two entries, through the user db."""
    db = bridge.user_db
    exam = db.create_exam_context(exam_name='Free Notes Exam',
                                  exam_description='bridge slots for a free note')
    subject = db.create_subject_node(exam_context=exam.exam_name, name='Cardiology',
                                     level_type='System')
    session = db.create_review_session(exam_context_id=exam.id, total_questions=5,
                                       total_incorrect=2)
    e1 = db.create_question_entry(review_session_id=session.id, user_answer='A',
                                  correct_answer='B', primary_subject_ids=[subject.id])
    e2 = db.create_question_entry(review_session_id=session.id, user_answer='A',
                                  correct_answer='B', primary_subject_ids=[subject.id])
    return {'db': db, 'exam': exam, 'subject': subject, 'e1': e1, 'e2': e2}


def _origin(db, note_id):
    row = db.fetchone('SELECT question_entry_id FROM entry_notes WHERE id = ?', (note_id,))
    return None if row is None else row['question_entry_id']


def _junction(db, note_id):
    return {r['question_entry_id'] for r in db.fetchall(
        'SELECT question_entry_id FROM entry_note_attachments WHERE note_id = ?',
        (note_id,))}


# ==================== the user_db=None guard ====================

class TestTheGuard:
    def test_add_note_without_a_user_db(self, no_db_bridge):
        response = json.loads(no_db_bridge.addNote(json.dumps({'content_html': '<p>x</p>'})))
        assert response['success'] is False
        assert response['error'] == 'No user database connected'
        assert response.get('data') is None

    def test_get_note_without_a_user_db(self, no_db_bridge):
        response = json.loads(no_db_bridge.getNote(1))
        assert response['success'] is False
        assert response['error'] == 'No user database connected'

    def test_list_free_notes_without_a_user_db(self, no_db_bridge):
        response = json.loads(no_db_bridge.listFreeNotes(50))
        assert response['success'] is False
        assert response['error'] == 'No user database connected'


# ==================== addNote ====================

class TestAddNote:
    def test_creates_a_row_with_a_null_origin_and_no_junction_row(self, bridge, world):
        payload = {'content_html': '<p>free</p>', 'content_json': None,
                   'linked_subject_ids': [world['subject'].id]}
        response = json.loads(bridge.addNote(json.dumps(payload)))

        assert response['success'] is True
        note = response.get('data')
        assert note is not None
        assert 'question_entry_id' not in note
        assert note['content_html'] == '<p>free</p>'
        assert note['linked_subject_ids'] == [world['subject'].id]
        assert note['attachment_count'] == 0

        db = world['db']
        assert _origin(db, note['id']) is None
        assert _junction(db, note['id']) == set()

    def test_the_payload_shape_is_add_entry_notes(self, bridge, world):
        """One builder on the page serves both slots: the same dict handed to
        ``addEntryNote`` makes an entry note, handed to ``addNote`` a free one,
        and the two replies differ only by the origin key."""
        payload = {'content_html': '<p>same shape</p>',
                   'linked_subject_ids': [world['subject'].id]}
        on_entry = json.loads(bridge.addEntryNote(world['e1'].id, json.dumps(payload)))['data']
        free = json.loads(bridge.addNote(json.dumps(payload)))['data']

        assert on_entry['question_entry_id'] == world['e1'].id
        assert 'question_entry_id' not in free
        assert set(on_entry) ^ set(free) == {'question_entry_id'}
        assert on_entry['content_html'] == free['content_html']
        assert on_entry['linked_subject_ids'] == free['linked_subject_ids']

    def test_a_tag_is_optional(self, bridge, world):
        response = json.loads(bridge.addNote(json.dumps({'content_html': '<p>untagged</p>'})))
        assert response['success'] is True
        note = response.get('data')
        assert note['is_general'] is True
        assert note['linked_subject_ids'] in (None, [])

    def test_an_empty_payload_still_creates_a_note(self, bridge, world):
        """``api.addNote()`` with nothing sends ``'{}'``; the wrapper's
        ``noteData || {}`` means an empty string never reaches the slot, but
        the slot tolerates both."""
        for raw in ('{}', ''):
            response = json.loads(bridge.addNote(raw))
            assert response['success'] is True, raw
            assert 'question_entry_id' not in response.get('data')

    def test_invalid_json_is_a_failure(self, bridge, world):
        response = json.loads(bridge.addNote('not-json'))
        assert response['success'] is False
        assert 'Invalid JSON' in response['error']
        assert response.get('data') is None
        assert world['db'].list_free_notes() == []

    def test_a_non_object_payload_is_a_failure(self, bridge, world):
        response = json.loads(bridge.addNote(json.dumps([1, 2, 3])))
        assert response['success'] is False
        assert response.get('data') is None
        assert world['db'].list_free_notes() == []

    @pytest.mark.parametrize('bad', [12, '12', {'a': 1}, [1, 'x'], [True]])
    def test_linked_subject_ids_must_be_a_list_of_ids(self, bridge, world, bad):
        """A scalar would be stored as JSON (m036's CHECK accepts any JSON) and
        then read two ways: ``json_each`` offers the note in the picker as if
        the tag were ``[12]`` while every payload reader gets a number. Refused
        before any write instead (PR #863's review)."""
        response = json.loads(bridge.addNote(json.dumps(
            {'content_html': '<p>x</p>', 'linked_subject_ids': bad})))
        assert response['success'] is False, bad
        assert 'linked_subject_ids' in response['error']
        assert response.get('data') is None
        assert world['db'].list_free_notes() == []

    def test_a_write_that_raises_is_a_failure_and_writes_no_row(self, bridge, world):
        """The slot's outer except: a dict bound as a SQLite parameter raises
        inside ``add_free_note``, the transaction rolls back, and the reply is
        the failure sentence rather than an exception crossing the bridge."""
        response = json.loads(bridge.addNote(json.dumps({'content_html': {'a': 1}})))
        assert response['success'] is False
        assert response['error'].startswith('Failed to add note')
        assert world['db'].list_free_notes() == []

    def test_the_note_is_reachable_through_get_note_and_list_free_notes(self, bridge, world):
        created = json.loads(bridge.addNote(json.dumps({'content_html': '<p>x</p>'})))['data']

        got = json.loads(bridge.getNote(created['id']))
        assert got['success'] is True
        assert got.get('data') == created

        listed = json.loads(bridge.listFreeNotes(50))
        assert [n['id'] for n in listed.get('data')] == [created['id']]


# ==================== getNote ====================

class TestGetNote:
    def test_an_entry_note_carries_the_integer_origin(self, bridge, world):
        note = world['db'].add_entry_note(world['e1'].id, content_html='<p>on e1</p>')
        response = json.loads(bridge.getNote(note.id))
        assert response['success'] is True
        data = response.get('data')
        assert data['id'] == note.id
        assert data['question_entry_id'] == world['e1'].id
        assert data['attachment_count'] == 1

    def test_a_free_note_omits_the_key(self, bridge, world):
        note = world['db'].add_free_note(content_html='<p>free</p>')
        data = json.loads(bridge.getNote(note.id)).get('data')
        assert data['id'] == note.id
        assert 'question_entry_id' not in data
        assert data['attachment_count'] == 0

    def test_a_freed_note_omits_the_key_and_keeps_its_attachment(self, bridge, world):
        """Decision 4's shape: born on e1, attached to e2, detached from e1.
        The row the deep dive now draws as text (6c23254) is this one."""
        db = world['db']
        note = db.add_entry_note(world['e1'].id, content_html='<p>shared</p>')
        db.attach_existing_note_to_entry(note.id, world['e2'].id)
        db.detach_note_from_entry(note.id, world['e1'].id)

        data = json.loads(bridge.getNote(note.id)).get('data')
        assert 'question_entry_id' not in data
        assert data['attachment_count'] == 1

    def test_a_missing_note_is_a_failure_with_the_sentence(self, bridge, world):
        response = json.loads(bridge.getNote(999_999))
        assert response['success'] is False
        assert response['error'] == 'Note 999999 not found'
        assert 'data' not in response, (
            '#240: a success that carries nothing is indistinguishable from one '
            'that worked, so a missing note must not read as success')


# ==================== listFreeNotes ====================

class TestListFreeNotes:
    def test_an_empty_list_is_success_with_data_empty(self, bridge, world):
        response = json.loads(bridge.listFreeNotes(50))
        assert response['success'] is True
        assert response.get('data') == []
        assert 'data' in response, 'an empty list is [] in the reply, not an absent key'

    def test_newest_first_by_updated_at_and_entry_notes_excluded(self, bridge, world):
        """The FIRST-created note is given the LATER ``updated_at``, so
        ``updated_at DESC`` and ``id DESC`` disagree and only the former
        passes: a note the student edits later rises to the top of *Your
        notes*. Stamps that agreed with creation order pinned nothing (PR
        #863's review)."""
        db = world['db']
        first = db.add_free_note(content_html='<p>first, edited later</p>')
        second = db.add_free_note(content_html='<p>second</p>')
        on_entry = db.add_entry_note(world['e1'].id, content_html='<p>entry note</p>')
        db.execute("UPDATE entry_notes SET updated_at = '2026-02-01 00:00:00' WHERE id = ?",
                   (first.id,))
        db.execute("UPDATE entry_notes SET updated_at = '2026-01-01 00:00:00' WHERE id = ?",
                   (second.id,))
        db.conn.commit()

        data = json.loads(bridge.listFreeNotes(50)).get('data')
        assert [n['id'] for n in data] == [first.id, second.id]
        assert on_entry.id not in {n['id'] for n in data}
        assert all('question_entry_id' not in n for n in data)
        assert [n['attachment_count'] for n in data] == [0, 0]

    def test_equal_timestamps_break_the_tie_by_id_newest_first(self, bridge, world):
        db = world['db']
        first = db.add_free_note(content_html='<p>first</p>')
        second = db.add_free_note(content_html='<p>second</p>')
        db.execute("UPDATE entry_notes SET updated_at = '2026-03-01 00:00:00' WHERE id IN (?, ?)",
                   (first.id, second.id))
        db.conn.commit()
        data = json.loads(bridge.listFreeNotes(50)).get('data')
        assert [n['id'] for n in data] == [second.id, first.id]

    def test_a_free_note_attached_to_an_entry_is_still_listed(self, bridge, world):
        """Free is about the origin, not about attachments: a free note the
        student later put on e2 is still a note on its own."""
        db = world['db']
        note = db.add_free_note(content_html='<p>free then attached</p>')
        db.attach_existing_note_to_entry(note.id, world['e2'].id)

        data = json.loads(bridge.listFreeNotes(50)).get('data')
        assert [n['id'] for n in data] == [note.id]
        assert data[0]['attachment_count'] == 1
        assert 'question_entry_id' not in data[0]

    def test_honours_the_limit(self, bridge, world):
        db = world['db']
        for i in range(3):
            db.add_free_note(content_html=f'<p>{i}</p>')
        assert len(json.loads(bridge.listFreeNotes(2)).get('data')) == 2
        assert len(json.loads(bridge.listFreeNotes(50)).get('data')) == 3

    def test_a_non_positive_limit_falls_back_to_the_default(self, bridge, world):
        db = world['db']
        for i in range(3):
            db.add_free_note(content_html=f'<p>{i}</p>')
        assert len(json.loads(bridge.listFreeNotes(0)).get('data')) == 3


# ==================== the slots are registered and instrumented ====================

def test_the_three_slots_are_pyqt_slots_paired_with_instrumentation():
    """Each new slot is ``@pyqtSlot(..., result=str)`` directly followed by
    ``@instrumented_slot``, the convention ``check_instrumented_slots.py``
    gates on. Asserted on the source, so a decorator dropped from one slot
    fails here as well as at the gate."""
    source = (REPO_ROOT / 'src' / 'app' / 'bridge_domains' / 'notes.py').read_text(
        encoding='utf-8')
    for name in ('addNote', 'getNote', 'listFreeNotes'):
        pattern = re.compile(
            r'@pyqtSlot\([^)]*result=str\)\s*@instrumented_slot\s*def ' + name + r'\(')
        assert pattern.search(source), (
            f'{name} is not a @pyqtSlot paired with @instrumented_slot')


def test_the_js_wrappers_name_the_slots():
    """``api/notes.js`` calls the three slots by their registered names, so
    ``test_api_layer_matches_the_bridge.py``'s pairing sweep sees them."""
    js = (REPO_ROOT / 'src' / 'web' / 'js' / 'api' / 'notes.js').read_text(encoding='utf-8')
    for name in ('addNote', 'getNote', 'listFreeNotes'):
        assert f'api.{name} = async function' in js, f'api.{name} is not defined'
        assert f"_callBridge('{name}'" in js, f'api.{name} does not call the {name} slot'
