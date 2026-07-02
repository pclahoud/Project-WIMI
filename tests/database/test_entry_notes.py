"""
Tests for Phase 9: Entry Notes
Tests CRUD operations, migration, subject linking, and integration with existing getters.
"""

import pytest
import json
from datetime import date
from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    """Create a database with basic exam/session/entry data."""
    db_path = tmp_path / "test_user.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")
    db._ensure_phase7_schema()

    # Create exam context
    exam = db.create_exam_context(
        exam_name="Test Exam",
        exam_description="For notes testing",
        hierarchy_levels=["System", "Topic"]
    )

    # Create subject nodes
    subj1 = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Cardiology",
        level_type="System"
    )
    subj2 = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Pulmonology",
        level_type="System"
    )

    # Create a question source and session
    source = db.create_question_source(
        source_name="Test Source",
        source_type="textbook"
    )
    session = db.create_review_session(
        exam_context_id=exam.id,
        session_name="Test Session",
        date_encountered=date.today(),
        total_questions=5,
        total_incorrect=2,
        question_source_id=source.id
    )

    # Create a question entry
    entry = db.create_question_entry(
        review_session_id=session.id,
        user_answer="A",
        correct_answer="B",
        primary_subject_ids=[subj1.id],
        secondary_subject_ids=[subj2.id]
    )

    return {
        'db': db,
        'exam': exam,
        'session': session,
        'entry': entry,
        'subj1': subj1,
        'subj2': subj2
    }


class TestEntryNotesTable:
    """Test table creation and migration."""

    def test_table_exists(self, db):
        """entry_notes table should be created automatically."""
        udb = db['db']
        tables = udb.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {row['name'] for row in tables}
        assert 'entry_notes' in table_names

    def test_table_creation_idempotent(self, db):
        """Calling migration again should not fail."""
        udb = db['db']
        udb._ensure_entry_notes_table()
        tables = udb.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {row['name'] for row in tables}
        assert 'entry_notes' in table_names


class TestLegacyMigration:
    """Test migration of legacy notes field to entry_notes."""

    def test_legacy_notes_migrated(self, tmp_path):
        """Existing notes in question_entries should be migrated to entry_notes."""
        db_path = tmp_path / "test_migration.db"
        udb = UserDatabase(str(db_path), user_id=1, username="migrateuser")

        exam = udb.create_exam_context(
            exam_name="Migration Exam",
            exam_description="Test",
            hierarchy_levels=["System"]
        )
        source = udb.create_question_source(source_name="Src", source_type="textbook")
        session = udb.create_review_session(
            exam_context_id=exam.id,
            session_name="Sess",
            date_encountered=date.today(),
            total_questions=1,
            total_incorrect=1,
            question_source_id=source.id
        )

        entry = udb.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B"
        )
        # Set legacy notes directly
        udb.execute(
            "UPDATE question_entries SET notes = ?, notes_json = ? WHERE id = ?",
            ("<p>Legacy note content</p>", '{"type":"doc"}', entry.id)
        )
        udb.conn.commit()

        # Drop entry_notes table to simulate pre-migration state
        udb.execute("DROP TABLE IF EXISTS entry_notes")
        udb.conn.commit()

        # Run migration
        udb._ensure_entry_notes_table()

        # Verify migration
        notes = udb.get_entry_notes_list(entry.id)
        assert len(notes) == 1
        assert notes[0].content_html == "<p>Legacy note content</p>"
        assert notes[0].content_json == '{"type":"doc"}'
        assert notes[0].is_migrated is True
        assert notes[0].is_general is True

    def test_migration_idempotent(self, tmp_path):
        """Running migration twice should not create duplicate notes."""
        db_path = tmp_path / "test_idempotent.db"
        udb = UserDatabase(str(db_path), user_id=1, username="idempotentuser")

        exam = udb.create_exam_context(
            exam_name="Idem Exam", exam_description="Test",
            hierarchy_levels=["System"]
        )
        source = udb.create_question_source(source_name="Src", source_type="textbook")
        session = udb.create_review_session(
            exam_context_id=exam.id, session_name="Sess",
            date_encountered=date.today(),
            total_questions=1, total_incorrect=1,
            question_source_id=source.id
        )
        entry = udb.create_question_entry(
            review_session_id=session.id, user_answer="A", correct_answer="B"
        )
        udb.execute("UPDATE question_entries SET notes = ? WHERE id = ?", ("test", entry.id))
        udb.conn.commit()

        # Drop and re-migrate twice
        udb.execute("DROP TABLE IF EXISTS entry_notes")
        udb.conn.commit()
        udb._ensure_entry_notes_table()
        # Re-run migration helper (table already exists)
        udb._migrate_legacy_notes()

        notes = udb.get_entry_notes_list(entry.id)
        assert len(notes) == 1


class TestAddEntryNote:
    """Test adding notes."""

    def test_add_basic_note(self, db):
        """Add a note with HTML content."""
        udb = db['db']
        entry = db['entry']

        note = udb.add_entry_note(entry.id, content_html="<p>Hello</p>")
        assert note.id is not None
        assert note.question_entry_id == entry.id
        assert note.content_html == "<p>Hello</p>"
        assert note.sort_order == 0
        assert note.is_general is True
        assert note.linked_subject_ids is None

    def test_add_note_with_json(self, db):
        """Add a note with both HTML and JSON content."""
        udb = db['db']
        entry = db['entry']

        json_str = json.dumps({"type": "doc", "content": []})
        note = udb.add_entry_note(entry.id, content_html="<p>Rich</p>", content_json=json_str)
        assert note.content_json == json_str

    def test_add_note_with_subjects(self, db):
        """Add a note linked to subjects."""
        udb = db['db']
        entry = db['entry']
        subj1 = db['subj1']

        note = udb.add_entry_note(entry.id, content_html="<p>Subject note</p>",
                                  linked_subject_ids=[subj1.id])
        assert note.linked_subject_ids == [subj1.id]
        assert note.is_general is False

    def test_sort_order_increments(self, db):
        """Each new note should get an incrementing sort_order."""
        udb = db['db']
        entry = db['entry']

        n1 = udb.add_entry_note(entry.id, content_html="<p>First</p>")
        n2 = udb.add_entry_note(entry.id, content_html="<p>Second</p>")
        n3 = udb.add_entry_note(entry.id, content_html="<p>Third</p>")

        assert n1.sort_order == 0
        assert n2.sort_order == 1
        assert n3.sort_order == 2


class TestGetEntryNotes:
    """Test retrieving notes."""

    def test_get_notes_list(self, db):
        """Get all notes for an entry ordered by sort_order."""
        udb = db['db']
        entry = db['entry']

        udb.add_entry_note(entry.id, content_html="<p>First</p>")
        udb.add_entry_note(entry.id, content_html="<p>Second</p>")

        notes = udb.get_entry_notes_list(entry.id)
        assert len(notes) == 2
        assert notes[0].content_html == "<p>First</p>"
        assert notes[1].content_html == "<p>Second</p>"

    def test_get_notes_empty(self, db):
        """Getting notes for entry with none should return empty list."""
        udb = db['db']
        notes = udb.get_entry_notes_list(99999)
        assert notes == []


class TestUpdateEntryNote:
    """Test updating notes."""

    def test_update_content(self, db):
        """Update a note's HTML content."""
        udb = db['db']
        entry = db['entry']

        note = udb.add_entry_note(entry.id, content_html="<p>Old</p>")
        updated = udb.update_entry_note(note.id, content_html="<p>New</p>")
        assert updated.content_html == "<p>New</p>"
        assert updated.id == note.id

    def test_update_linked_subjects(self, db):
        """Update a note's linked subject IDs."""
        udb = db['db']
        entry = db['entry']
        subj1 = db['subj1']
        subj2 = db['subj2']

        note = udb.add_entry_note(entry.id, content_html="<p>Test</p>")
        assert note.is_general is True

        updated = udb.update_entry_note(note.id, linked_subject_ids=[subj1.id, subj2.id])
        assert updated.linked_subject_ids == [subj1.id, subj2.id]
        assert updated.is_general is False

    def test_update_to_general(self, db):
        """Clear linked subjects to make note general again."""
        udb = db['db']
        entry = db['entry']
        subj1 = db['subj1']

        note = udb.add_entry_note(entry.id, content_html="<p>Test</p>",
                                  linked_subject_ids=[subj1.id])
        updated = udb.update_entry_note(note.id, linked_subject_ids=[])
        assert updated.linked_subject_ids is None
        assert updated.is_general is True

    def test_update_no_changes(self, db):
        """Updating with no fields should return unchanged note."""
        udb = db['db']
        entry = db['entry']

        note = udb.add_entry_note(entry.id, content_html="<p>Same</p>")
        updated = udb.update_entry_note(note.id)
        assert updated.content_html == "<p>Same</p>"


class TestDeleteEntryNote:
    """Test deleting notes."""

    def test_delete_note(self, db):
        """Delete a note from the database."""
        udb = db['db']
        entry = db['entry']

        note = udb.add_entry_note(entry.id, content_html="<p>Delete me</p>")
        result = udb.delete_entry_note(note.id)
        assert result is True

        notes = udb.get_entry_notes_list(entry.id)
        assert len(notes) == 0


class TestClearEntryNote:
    """Test clearing note content."""

    def test_clear_note(self, db):
        """Clear a note's content but keep the record."""
        udb = db['db']
        entry = db['entry']

        note = udb.add_entry_note(entry.id, content_html="<p>Content</p>",
                                  content_json='{"test": true}')
        cleared = udb.clear_entry_note(note.id)
        assert cleared.content_html == ''
        assert cleared.content_json is None
        assert cleared.id == note.id

        # Record still exists
        notes = udb.get_entry_notes_list(entry.id)
        assert len(notes) == 1


class TestCascadeDelete:
    """Test cascade delete when parent entry is deleted."""

    def test_notes_deleted_with_entry(self, db):
        """Notes should be deleted when the parent entry is deleted."""
        udb = db['db']
        entry = db['entry']

        udb.add_entry_note(entry.id, content_html="<p>Note 1</p>")
        udb.add_entry_note(entry.id, content_html="<p>Note 2</p>")

        # Delete the entry
        udb.execute("DELETE FROM question_entries WHERE id = ?", (entry.id,))
        udb.conn.commit()

        notes = udb.get_entry_notes_list(entry.id)
        assert len(notes) == 0


class TestIntegrationWithGetters:
    """Test that notes_list is populated in existing entry getters."""

    def test_get_question_entry_includes_notes(self, db):
        """get_question_entry should populate notes_list."""
        udb = db['db']
        entry = db['entry']

        udb.add_entry_note(entry.id, content_html="<p>Getter test</p>")

        loaded = udb.get_question_entry(entry.id)
        assert hasattr(loaded, 'notes_list')
        assert len(loaded.notes_list) == 1
        assert loaded.notes_list[0].content_html == "<p>Getter test</p>"

    def test_get_session_entries_includes_notes(self, db):
        """get_session_entries should populate notes_list on each entry."""
        udb = db['db']
        entry = db['entry']
        session = db['session']

        udb.add_entry_note(entry.id, content_html="<p>Session test</p>")

        entries = udb.get_session_entries(session.id)
        matching = [e for e in entries if e.id == entry.id]
        assert len(matching) == 1
        assert len(matching[0].notes_list) == 1

    def test_get_entry_with_context_includes_notes(self, db):
        """get_entry_with_context should include notes_list in the entry dict."""
        udb = db['db']
        entry = db['entry']

        udb.add_entry_note(entry.id, content_html="<p>Context test</p>")

        result = udb.get_entry_with_context(entry.id)
        assert result is not None
        assert 'notes_list' in result['entry']
        assert len(result['entry']['notes_list']) == 1
        assert result['entry']['notes_list'][0]['content_html'] == "<p>Context test</p>"

    def test_entry_to_dict_serializes_notes(self, db):
        """_entry_to_dict should include notes_list with to_dict() output."""
        udb = db['db']
        entry = db['entry']
        subj1 = db['subj1']

        udb.add_entry_note(entry.id, content_html="<p>Dict test</p>",
                           linked_subject_ids=[subj1.id])

        loaded = udb.get_question_entry(entry.id)
        d = udb._entry_to_dict(loaded)
        assert 'notes_list' in d
        assert len(d['notes_list']) == 1
        note_dict = d['notes_list'][0]
        assert note_dict['content_html'] == "<p>Dict test</p>"
        assert note_dict['linked_subject_ids'] == [subj1.id]
        assert note_dict['is_general'] is False


class TestLegacyFallback:
    """Test legacy notes field behavior."""

    def test_empty_notes_list_with_legacy(self, db):
        """Entry with no entry_notes but legacy notes field should still work."""
        udb = db['db']
        entry = db['entry']

        # Set legacy notes directly without creating entry_notes
        udb.execute("UPDATE question_entries SET notes = ? WHERE id = ?",
                    ("<p>Legacy only</p>", entry.id))
        udb.conn.commit()

        loaded = udb.get_question_entry(entry.id)
        # notes_list should be empty (only migration populates it)
        # but legacy notes field should still be accessible
        assert loaded.notes == "<p>Legacy only</p>"
