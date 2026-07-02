"""
Tests for field-specific search filtering in get_entries_paginated().
Verifies that field_filters parameter correctly filters entries by
specific fields (user_answer, correct_answer, subject, reflection,
explanation, notes, question_id).
"""

import pytest
from datetime import date
from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    """Create a database with diverse entries for field search testing."""
    db_path = tmp_path / "test_field_search.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")
    db._ensure_phase7_schema()

    # Create exam context
    exam = db.create_exam_context(
        exam_name="Test Exam",
        exam_description="For field search testing",
        hierarchy_levels=["System", "Topic"]
    )

    # Create subject nodes
    cardiology = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Cardiology",
        level_type="System"
    )
    pulmonology = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Pulmonology",
        level_type="System"
    )
    nephrology = db.create_subject_node(
        exam_context=exam.exam_name,
        name="Nephrology",
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
        total_incorrect=3,
        question_source_id=source.id
    )

    # Entry 1: Cardiology entry about ACE inhibitors
    entry1 = db.create_question_entry(
        review_session_id=session.id,
        user_answer="ACE inhibitor",
        correct_answer="Beta blocker",
        question_id="Q101",
        reflection="I confused ACE inhibitors with beta blockers",
        explanation="ACE inhibitors reduce angiotensin",
        notes="Review pharmacology chapter",
        primary_subject_ids=[cardiology.id]
    )

    # Entry 2: Pulmonology entry about bronchodilators
    entry2 = db.create_question_entry(
        review_session_id=session.id,
        user_answer="Albuterol",
        correct_answer="Ipratropium",
        question_id="Q202",
        reflection="Mixed up short-acting agents",
        explanation="Ipratropium is anticholinergic",
        notes="Study COPD treatment algorithm",
        primary_subject_ids=[pulmonology.id]
    )

    # Entry 3: Nephrology entry with ACE in correct_answer
    entry3 = db.create_question_entry(
        review_session_id=session.id,
        user_answer="Losartan",
        correct_answer="ACE inhibitor",
        question_id="Q103",
        reflection="ARBs vs ACE inhibitors in renal protection",
        explanation="ACE inhibitors are first-line for diabetic nephropathy",
        primary_subject_ids=[nephrology.id]
    )

    # Add an entry_note on entry2
    db._ensure_entry_notes_table()
    db.add_entry_note(
        entry_id=entry2.id,
        content_html="<p>Important: review bronchodilator mechanisms</p>"
    )

    db._test_data = {
        'exam': exam,
        'session': session,
        'cardiology': cardiology,
        'pulmonology': pulmonology,
        'nephrology': nephrology,
        'entry1': entry1,
        'entry2': entry2,
        'entry3': entry3,
    }
    return db


class TestFieldFilterUserAnswer:
    """Test user_answer field filter."""

    def test_user_answer_filter_matches(self, db):
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'user_answer': 'ACE inhibitor'}
        )
        assert total == 1
        assert entries[0].id == db._test_data['entry1'].id

    def test_user_answer_partial_match(self, db):
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'user_answer': 'ACE'}
        )
        assert total == 1
        assert entries[0].id == db._test_data['entry1'].id


class TestFieldFilterCorrectAnswer:
    """Test correct_answer field filter."""

    def test_correct_answer_filter(self, db):
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'correct_answer': 'ACE inhibitor'}
        )
        assert total == 1
        assert entries[0].id == db._test_data['entry3'].id


class TestFieldFilterSubject:
    """Test subject field filter via subquery join."""

    def test_subject_filter_cardiology(self, db):
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'subject': 'Cardiology'}
        )
        assert total == 1
        assert entries[0].id == db._test_data['entry1'].id

    def test_subject_filter_partial(self, db):
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'subject': 'ology'}
        )
        # All three subjects contain "ology"
        assert total == 3


class TestFieldFilterNotes:
    """Test notes field filter searches both qe.notes and entry_notes.content_html."""

    def test_notes_filter_legacy_field(self, db):
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'notes': 'pharmacology'}
        )
        assert total == 1
        assert entries[0].id == db._test_data['entry1'].id

    def test_notes_filter_entry_notes_table(self, db):
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'notes': 'bronchodilator mechanisms'}
        )
        assert total == 1
        assert entries[0].id == db._test_data['entry2'].id


class TestFieldFilterQuestionId:
    """Test question_id field filter with prefix match."""

    def test_question_id_prefix_match(self, db):
        """Q10 should match Q101 and Q103."""
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'question_id': 'Q10'}
        )
        assert total == 2
        ids = {e.id for e in entries}
        assert db._test_data['entry1'].id in ids
        assert db._test_data['entry3'].id in ids

    def test_question_id_exact(self, db):
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'question_id': 'Q202'}
        )
        assert total == 1
        assert entries[0].id == db._test_data['entry2'].id


class TestFieldFilterReflectionExplanation:
    """Test reflection and explanation field filters."""

    def test_reflection_filter(self, db):
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'reflection': 'renal protection'}
        )
        assert total == 1
        assert entries[0].id == db._test_data['entry3'].id

    def test_explanation_filter(self, db):
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'explanation': 'anticholinergic'}
        )
        assert total == 1
        assert entries[0].id == db._test_data['entry2'].id


class TestMixedMode:
    """Test plain text search + field filters combined with AND."""

    def test_plain_text_and_field_filter(self, db):
        """Search 'ACE' in all fields AND filter user_answer to 'ACE'."""
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            search_query='ACE',
            field_filters={'user_answer': 'ACE'}
        )
        # Only entry1 has 'ACE' in user_answer; entry3 has ACE in reflection/explanation
        # but not in user_answer
        assert total == 1
        assert entries[0].id == db._test_data['entry1'].id

    def test_multiple_field_filters_and(self, db):
        """Multiple field filters combined with AND."""
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={
                'correct_answer': 'ACE',
                'subject': 'Nephrology'
            }
        )
        assert total == 1
        assert entries[0].id == db._test_data['entry3'].id

    def test_multiple_field_filters_no_match(self, db):
        """Conflicting field filters should return zero results."""
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={
                'user_answer': 'ACE',
                'subject': 'Pulmonology'
            }
        )
        assert total == 0


class TestEdgeCases:
    """Test edge cases: unknown fields, empty filters, backward compat."""

    def test_unknown_field_ignored(self, db):
        """Unknown field names should be silently ignored."""
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={'nonexistent_field': 'anything'}
        )
        # Should return all entries (filter is ignored)
        assert total == 3

    def test_empty_field_filters(self, db):
        """Empty dict should behave like no field filters."""
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters={}
        )
        assert total == 3

    def test_none_field_filters(self, db):
        """None should behave like no field filters (backward compat)."""
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            field_filters=None
        )
        assert total == 3

    def test_backward_compat_search_query_alone(self, db):
        """search_query without field_filters works identically to before."""
        entries, total = db.get_entries_paginated(
            exam_context_id=db._test_data['exam'].id,
            search_query='ACE'
        )
        # ACE appears in entry1 (user_answer, reflection, explanation)
        # and entry3 (correct_answer, reflection, explanation)
        assert total == 2
        ids = {e.id for e in entries}
        assert db._test_data['entry1'].id in ids
        assert db._test_data['entry3'].id in ids
