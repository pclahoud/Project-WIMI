"""Tests for session import feature: mapping profiles CRUD and import execution."""

import json
import os
import pytest
from datetime import date

from database.user_db import UserDatabase


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def db(tmp_path):
    """Create a temporary UserDatabase with all schemas initialized."""
    db_path = tmp_path / "test_user.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")
    db._ensure_phase4_schema()
    db._ensure_phase7_schema()
    return db


@pytest.fixture
def db_with_session(db):
    """Create a database with an exam context, source, and session for import testing."""
    exam = db.create_exam_context(
        exam_name="Test Exam",
        exam_description="For import testing",
        hierarchy_levels=["System", "Topic"]
    )
    source = db.create_question_source(
        source_name="AMBOSS",
        source_type="commercial_prep"
    )
    session = db.create_review_session(
        exam_context_id=exam.id,
        session_name="Import Test Session",
        date_encountered=date.today(),
        total_questions=3,
        total_incorrect=3,
        question_source_id=source.id
    )
    return {
        'db': db,
        'exam': exam,
        'source': source,
        'session': session
    }


@pytest.fixture
def sample_json_file(tmp_path):
    """Create a sample JSON file mimicking AMBOSS format."""
    session_dir = tmp_path / "session_Test"
    session_dir.mkdir()

    data = {
        "session_id": "1",
        "session_name": "Test Session",
        "date_scraped": "2026-02-17T13:52:30.990227",
        "questions": [
            {
                "question_number": 1,
                "question_text": "A 58-year-old woman presents with abdominal pain.",
                "correct_answer": "ERCP",
                "incorrect_answer": "Cholecystectomy",
                "answer_choices": [],
                "correct_answer_explanation": "ERCP is the correct treatment because...",
                "incorrect_answer_explanation": "Cholecystectomy alone does not address...",
                "images": [
                    {"filename": "q1_001.jpg", "original_url": "", "alt_text": "X-ray"},
                    {"filename": "q1_002.jpg", "original_url": "", "alt_text": "CT scan"}
                ],
                "anki_cards": []
            },
            {
                "question_number": 2,
                "question_text": "A 45-year-old man with chest pain.",
                "correct_answer": "Troponin",
                "incorrect_answer": "BNP",
                "answer_choices": [],
                "correct_answer_explanation": "Troponin is the gold standard...",
                "incorrect_answer_explanation": "BNP is not specific...",
                "images": [],
                "anki_cards": []
            },
            {
                "question_number": 3,
                "question_text": "A 30-year-old woman with headache.",
                "correct_answer": "MRI",
                "incorrect_answer": "CT",
                "answer_choices": [],
                "correct_answer_explanation": "MRI provides better soft tissue detail...",
                "incorrect_answer_explanation": "CT is faster but less sensitive...",
                "images": [
                    {"filename": "q3_001.jpg", "original_url": "", "alt_text": "MRI image"}
                ],
                "anki_cards": []
            }
        ]
    }

    json_path = session_dir / "session_Test.json"
    with open(json_path, 'w') as f:
        json.dump(data, f)

    # Create images directory with small test images
    images_dir = session_dir / "images"
    images_dir.mkdir()

    # Create tiny JPEG-like files for testing
    for fname in ["q1_001.jpg", "q1_002.jpg", "q3_001.jpg"]:
        img_path = images_dir / fname
        # Minimal JPEG header (not a real image but enough for file I/O tests)
        img_path.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100)

    return {
        'json_path': str(json_path),
        'session_dir': str(session_dir),
        'images_dir': str(images_dir),
        'data': data
    }


# =========================================================================
# Import Mapping Profiles - Table & CRUD
# =========================================================================

class TestImportMappingsTable:
    """Test that the import_mapping_profiles table is created during schema migration."""

    def test_table_exists(self, db):
        tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {row['name'] for row in tables}
        assert 'import_mapping_profiles' in table_names

    def test_table_columns(self, db):
        columns = db.fetchall("PRAGMA table_info(import_mapping_profiles)")
        col_names = {col['name'] for col in columns}
        assert col_names == {
            'id', 'profile_name', 'source_type', 'field_mappings',
            'created_at', 'updated_at'
        }

    def test_ensure_idempotent(self, db):
        """Calling _ensure_import_mappings_table multiple times is safe."""
        db._ensure_import_mappings_table()
        db._ensure_import_mappings_table()
        tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {row['name'] for row in tables}
        assert 'import_mapping_profiles' in table_names


class TestCreateImportMappingProfile:
    def test_create_basic(self, db):
        mappings = json.dumps({"mappings": [
            {"source": "question_number", "target": "question_id"}
        ]})
        result = db.create_import_mapping_profile(
            profile_name='Test Profile',
            source_type='amboss',
            field_mappings=mappings
        )
        assert result['profile_name'] == 'Test Profile'
        assert result['source_type'] == 'amboss'
        assert result['id'] is not None
        assert json.loads(result['field_mappings']) == json.loads(mappings)

    def test_create_with_multiple_mappings(self, db):
        mappings = json.dumps({"mappings": [
            {"source": "question_number", "target": "question_id"},
            {"source": "incorrect_answer", "target": "user_answer"},
            {"source": "correct_answer", "target": "correct_answer"},
            {"source": "correct_answer_explanation", "target": "explanation"},
            {"source": "incorrect_answer_explanation", "target": "reflection"}
        ]})
        result = db.create_import_mapping_profile(
            profile_name='Full AMBOSS',
            source_type='amboss',
            field_mappings=mappings
        )
        parsed = json.loads(result['field_mappings'])
        assert len(parsed['mappings']) == 5


class TestGetImportMappingProfiles:
    def test_get_empty(self, db):
        result = db.get_import_mapping_profiles()
        assert result == []

    def test_get_all(self, db):
        db.create_import_mapping_profile('Profile A', 'amboss', '{"mappings": []}')
        db.create_import_mapping_profile('Profile B', 'uworld', '{"mappings": []}')
        result = db.get_import_mapping_profiles()
        assert len(result) == 2

    def test_ordered_by_name(self, db):
        db.create_import_mapping_profile('Zebra', 'custom', '{"mappings": []}')
        db.create_import_mapping_profile('Alpha', 'custom', '{"mappings": []}')
        result = db.get_import_mapping_profiles()
        names = [r['profile_name'] for r in result]
        assert names == ['Alpha', 'Zebra']


class TestUpdateImportMappingProfile:
    def test_update_name(self, db):
        p = db.create_import_mapping_profile('Old Name', 'amboss', '{"mappings": []}')
        result = db.update_import_mapping_profile(p['id'], profile_name='New Name')
        assert result['profile_name'] == 'New Name'
        assert result['source_type'] == 'amboss'

    def test_update_source_type(self, db):
        p = db.create_import_mapping_profile('Test', 'amboss', '{"mappings": []}')
        result = db.update_import_mapping_profile(p['id'], source_type='uworld')
        assert result['source_type'] == 'uworld'

    def test_update_field_mappings(self, db):
        p = db.create_import_mapping_profile('Test', 'amboss', '{"mappings": []}')
        new_mappings = '{"mappings": [{"source": "x", "target": "y"}]}'
        result = db.update_import_mapping_profile(p['id'], field_mappings=new_mappings)
        parsed = json.loads(result['field_mappings'])
        assert len(parsed['mappings']) == 1

    def test_update_nothing(self, db):
        p = db.create_import_mapping_profile('Test', 'amboss', '{"mappings": []}')
        result = db.update_import_mapping_profile(p['id'])
        assert result['profile_name'] == 'Test'


class TestDeleteImportMappingProfile:
    def test_delete(self, db):
        p = db.create_import_mapping_profile('ToDelete', 'custom', '{"mappings": []}')
        assert db.delete_import_mapping_profile(p['id']) is True
        assert db.get_import_mapping_profiles() == []

    def test_delete_one_of_many(self, db):
        p1 = db.create_import_mapping_profile('Keep', 'a', '{}')
        p2 = db.create_import_mapping_profile('Delete', 'b', '{}')
        p3 = db.create_import_mapping_profile('AlsoKeep', 'c', '{}')
        db.delete_import_mapping_profile(p2['id'])
        result = db.get_import_mapping_profiles()
        assert len(result) == 2
        names = [r['profile_name'] for r in result]
        assert 'Keep' in names
        assert 'AlsoKeep' in names
        assert 'Delete' not in names


# =========================================================================
# Bridge Import Logic - _apply_field_mappings
# =========================================================================

class TestApplyFieldMappings:
    """Test the field mapping logic from the bridge layer."""

    def _get_bridge(self):
        """Create a minimal bridge instance for testing _apply_field_mappings."""
        # Import here to avoid import errors if PyQt6 is not available
        try:
            from app.bridge import DatabaseBridge
            bridge = DatabaseBridge.__new__(DatabaseBridge)
            return bridge
        except ImportError:
            pytest.skip("PyQt6 not available for bridge tests")

    def test_basic_mapping(self):
        bridge = self._get_bridge()
        question = {
            "question_number": 5,
            "correct_answer": "ERCP",
            "incorrect_answer": "Cholecystectomy"
        }
        mappings = [
            {"source": "question_number", "target": "question_id"},
            {"source": "correct_answer", "target": "correct_answer"},
            {"source": "incorrect_answer", "target": "user_answer"}
        ]
        result = bridge._apply_field_mappings(question, mappings)
        assert result['question_id'] == '5'
        assert result['correct_answer'] == 'ERCP'
        assert result['user_answer'] == 'Cholecystectomy'

    def test_skip_fields(self):
        bridge = self._get_bridge()
        question = {"field1": "value1", "field2": "value2"}
        mappings = [
            {"source": "field1", "target": "(skip)"},
            {"source": "field2", "target": "notes"}
        ]
        result = bridge._apply_field_mappings(question, mappings)
        assert 'field1' not in result
        assert result['notes'] == 'value2'

    def test_merge_fields(self):
        bridge = self._get_bridge()
        question = {
            "correct_explanation": "First part",
            "incorrect_explanation": "Second part"
        }
        mappings = [
            {"source": "correct_explanation", "target": "explanation", "merge_order": 1},
            {"source": "incorrect_explanation", "target": "explanation", "merge_order": 2}
        ]
        result = bridge._apply_field_mappings(question, mappings)
        assert result['explanation'] == 'First part<hr>Second part'

    def test_merge_order_respected(self):
        bridge = self._get_bridge()
        question = {"a": "AAA", "b": "BBB"}
        mappings = [
            {"source": "a", "target": "reflection", "merge_order": 2},
            {"source": "b", "target": "reflection", "merge_order": 1}
        ]
        result = bridge._apply_field_mappings(question, mappings)
        assert result['reflection'] == 'BBB<hr>AAA'

    def test_missing_source_field(self):
        bridge = self._get_bridge()
        question = {"existing_field": "value"}
        mappings = [
            {"source": "missing_field", "target": "notes"},
            {"source": "existing_field", "target": "explanation"}
        ]
        result = bridge._apply_field_mappings(question, mappings)
        assert 'notes' not in result
        assert result['explanation'] == 'value'

    def test_numeric_fields(self):
        bridge = self._get_bridge()
        question = {"difficulty": "3", "time": "120"}
        mappings = [
            {"source": "difficulty", "target": "perceived_difficulty"},
            {"source": "time", "target": "time_spent_seconds"}
        ]
        result = bridge._apply_field_mappings(question, mappings)
        assert result['perceived_difficulty'] == 3
        assert result['time_spent_seconds'] == 120

    def test_empty_mappings(self):
        bridge = self._get_bridge()
        question = {"field": "value"}
        result = bridge._apply_field_mappings(question, [])
        assert result == {}

    def test_flattened_anki_field_mapping(self):
        """Test that flattened anki_card_ids can be mapped to notes."""
        bridge = self._get_bridge()
        # Simulate a pre-flattened question (as the bridge would provide)
        question_flat = bridge._flatten_question_fields({
            "question_number": 1,
            "anki_cards": [{"card_id": "e40xRT", "card_name": "", "deck": ""}]
        })
        assert 'anki_card_ids' in question_flat
        mappings = [
            {"source": "question_number", "target": "question_id"},
            {"source": "anki_card_ids", "target": "notes"}
        ]
        result = bridge._apply_field_mappings(question_flat, mappings)
        assert result['notes'] == 'e40xRT'

    def test_flattened_answer_choices_mapping(self):
        """Test that flattened answer_choices_text can be mapped."""
        bridge = self._get_bridge()
        question_flat = bridge._flatten_question_fields({
            "answer_choices": [
                {"letter": "A", "text": "Option A", "is_correct": False},
                {"letter": "B", "text": "Option B", "is_correct": True}
            ]
        })
        assert 'answer_choices_text' in question_flat
        assert '[CORRECT]' in question_flat['answer_choices_text']
        assert 'A. Option A' in question_flat['answer_choices_text']
        assert 'B. Option B' in question_flat['answer_choices_text']


class TestFlattenQuestionFields:
    """Test the _flatten_question_fields helper."""

    def _get_bridge(self):
        try:
            from app.bridge import DatabaseBridge
            bridge = DatabaseBridge.__new__(DatabaseBridge)
            return bridge
        except ImportError:
            pytest.skip("PyQt6 not available for bridge tests")

    def test_flatten_anki_cards(self):
        bridge = self._get_bridge()
        result = bridge._flatten_question_fields({
            "question_number": 1,
            "anki_cards": [
                {"card_id": "abc123", "card_name": "Card 1", "deck": "Surgery"},
                {"card_id": "def456", "card_name": "", "deck": ""}
            ]
        })
        assert result['anki_card_ids'] == 'abc123 | Card 1 | deck: Surgery; def456'
        # Original field preserved for reference
        assert 'anki_cards' in result

    def test_flatten_anki_cards_empty(self):
        bridge = self._get_bridge()
        result = bridge._flatten_question_fields({
            "anki_cards": []
        })
        assert 'anki_card_ids' not in result

    def test_flatten_answer_choices(self):
        bridge = self._get_bridge()
        result = bridge._flatten_question_fields({
            "answer_choices": [
                {"letter": "A", "text": "Alpha", "is_correct": False},
                {"letter": "B", "text": "Beta", "is_correct": True},
            ]
        })
        text = result['answer_choices_text']
        assert 'A. Alpha' in text
        assert 'B. Beta [CORRECT]' in text

    def test_flatten_answer_choices_no_letter(self):
        """AMBOSS format has empty letter fields."""
        bridge = self._get_bridge()
        result = bridge._flatten_question_fields({
            "answer_choices": [
                {"letter": "", "text": "ERCP", "is_correct": True},
                {"letter": "", "text": "Cholecystectomy", "is_correct": False},
            ]
        })
        text = result['answer_choices_text']
        assert 'ERCP [CORRECT]' in text
        assert 'Cholecystectomy' in text
        assert text.startswith('ERCP')  # No letter prefix

    def test_flatten_preserves_simple_fields(self):
        bridge = self._get_bridge()
        result = bridge._flatten_question_fields({
            "question_number": 42,
            "question_text": "Some question",
            "correct_answer": "Right",
            "incorrect_answer": "Wrong",
        })
        assert result['question_number'] == 42
        assert result['question_text'] == 'Some question'
        assert result['correct_answer'] == 'Right'

    def test_images_preserved_for_import_engine(self):
        """Images array should be preserved (not flattened) for the import engine."""
        bridge = self._get_bridge()
        images = [{"filename": "q1.jpg", "original_url": "http://...", "alt_text": "img"}]
        result = bridge._flatten_question_fields({"images": images})
        assert result['images'] == images


# =========================================================================
# Integration: Import Execution (database-level only)
# =========================================================================

class TestImportExecution:
    """Test the actual import flow: JSON → session + entries.

    These tests create entries directly via user_db methods to verify the
    import pipeline would work correctly. We don't call the bridge method
    directly (it requires PyQt6 runtime) but test the underlying DB operations.
    """

    def test_basic_import_creates_session_and_entries(self, db):
        """Simulate importing 3 questions into a new session."""
        exam = db.create_exam_context(
            exam_name="Import Exam",
            exam_description="Test",
            hierarchy_levels=["System"]
        )
        session = db.create_review_session(
            exam_context_id=exam.id,
            session_name="Imported Session",
            date_encountered=date.today(),
            total_questions=3,
            total_incorrect=3
        )

        questions = [
            {"question_id": "1", "user_answer": "A", "correct_answer": "B",
             "explanation": "Explanation 1"},
            {"question_id": "2", "user_answer": "C", "correct_answer": "D",
             "explanation": "Explanation 2"},
            {"question_id": "3", "user_answer": "E", "correct_answer": "F",
             "explanation": "Explanation 3"},
        ]

        entries = []
        for q in questions:
            entry = db.create_question_entry(
                review_session_id=session.id,
                user_answer=q['user_answer'],
                correct_answer=q['correct_answer'],
                question_id=q.get('question_id'),
                explanation=q.get('explanation')
            )
            entries.append(entry)

        assert len(entries) == 3
        assert entries[0].question_id == "1"
        assert entries[1].user_answer == "C"
        assert entries[2].explanation == "Explanation 3"

    def test_entries_created_as_drafts(self, db):
        """All imported entries should be drafts (no subjects assigned)."""
        exam = db.create_exam_context(
            exam_name="Draft Exam",
            exam_description="Test",
            hierarchy_levels=["System"]
        )
        session = db.create_review_session(
            exam_context_id=exam.id,
            total_questions=1,
            total_incorrect=1
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B"
        )
        # No subjects assigned = draft
        assert entry.id is not None
        # Verify no subject mappings exist
        mappings = db.fetchall(
            "SELECT * FROM entry_subject_mappings WHERE question_entry_id = ?",
            (entry.id,)
        )
        assert len(mappings) == 0

    def test_merged_explanation_field(self, db):
        """Test creating entry with merged explanation (two sources → one target)."""
        exam = db.create_exam_context(
            exam_name="Merge Exam",
            exam_description="Test",
            hierarchy_levels=["System"]
        )
        session = db.create_review_session(
            exam_context_id=exam.id,
            total_questions=1,
            total_incorrect=1
        )
        merged_explanation = "Correct answer explanation<hr>Incorrect answer explanation"
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            explanation=merged_explanation
        )
        assert entry.explanation == merged_explanation
        assert '<hr>' in entry.explanation

    def test_partial_failure_allows_other_entries(self, db):
        """If one entry fails, others should still be created."""
        exam = db.create_exam_context(
            exam_name="Partial Exam",
            exam_description="Test",
            hierarchy_levels=["System"]
        )
        session = db.create_review_session(
            exam_context_id=exam.id,
            total_questions=3,
            total_incorrect=3
        )

        entries_created = 0
        errors = []

        questions = [
            {"user_answer": "A", "correct_answer": "B"},
            {"user_answer": None, "correct_answer": None},  # This should still work (empty strings)
            {"user_answer": "E", "correct_answer": "F"},
        ]

        for idx, q in enumerate(questions):
            try:
                db.create_question_entry(
                    review_session_id=session.id,
                    user_answer=q['user_answer'] or '',
                    correct_answer=q['correct_answer'] or '',
                )
                entries_created += 1
            except Exception as e:
                errors.append(f"Question {idx + 1}: {e}")

        assert entries_created == 3

    def test_import_with_all_field_types(self, db):
        """Test importing entry with all mappable fields populated."""
        exam = db.create_exam_context(
            exam_name="Full Exam",
            exam_description="Test",
            hierarchy_levels=["System"]
        )
        session = db.create_review_session(
            exam_context_id=exam.id,
            total_questions=1,
            total_incorrect=1
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            question_id="Q42",
            user_answer="Answer A",
            correct_answer="Answer B",
            explanation="The explanation",
            reflection="The reflection",
            notes="Some notes",
            perceived_difficulty=3,
            time_spent_seconds=120
        )
        assert entry.question_id == "Q42"
        assert entry.user_answer == "Answer A"
        assert entry.correct_answer == "Answer B"
        assert entry.explanation == "The explanation"
        assert entry.reflection == "The reflection"
        assert entry.perceived_difficulty == 3
        assert entry.time_spent_seconds == 120
