"""``_serialize_entry_note`` omits ``question_entry_id`` for a free note (#848).

Absent, not null: the ``path_omitted_ancestors`` convention (#301), so a page
tests ``'question_entry_id' in note`` rather than comparing against ``null``.
An entry note still carries the integer. No ``QApplication``; the bridge is
constructed directly as the other ``tests/app/test_bridge_*.py`` do.
"""
from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.models import EntryNote


@pytest.fixture
def bridge():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=Path(tmpdir), error_logger=None)
        try:
            yield DatabaseBridge(master_db=master, user_db=None)
        finally:
            master.close()


def _note(origin):
    return EntryNote(
        id=7, question_entry_id=origin, content_html='<p>x</p>', content_json=None,
        sort_order=0, linked_subject_ids=[3], is_migrated=False,
        created_at=datetime(2026, 11, 5, 12, 0), updated_at=datetime(2026, 11, 5, 12, 0))


def test_a_free_note_has_no_question_entry_id_key(bridge):
    data = bridge._serialize_entry_note(_note(None))
    assert 'question_entry_id' not in data
    assert data['id'] == 7
    assert data['linked_subject_ids'] == [3]


def test_an_entry_note_carries_the_integer(bridge):
    data = bridge._serialize_entry_note(_note(42))
    assert data['question_entry_id'] == 42


def test_the_models_own_dict_follows_the_same_rule():
    """``EntryNote.to_dict`` is the second shape a page receives a note in
    (``_base.py`` builds an entry's ``notes_list`` with it). Both shapes omit
    the key for a free note, so no page has two conventions to test."""
    assert 'question_entry_id' not in _note(None).to_dict()
    assert _note(42).to_dict()['question_entry_id'] == 42


def test_no_other_key_was_added(bridge):
    free = set(bridge._serialize_entry_note(_note(None)))
    on_entry = set(bridge._serialize_entry_note(_note(42)))
    assert on_entry - free == {'question_entry_id'}
    assert free == {
        'id', 'content_html', 'content_json', 'sort_order', 'linked_subject_ids',
        'is_general', 'is_migrated', 'attachment_count', 'created_at', 'updated_at'}
