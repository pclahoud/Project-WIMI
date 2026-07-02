"""
Tests for Phase 4: Question Entry System
"""
import pytest
import json
from datetime import date, datetime
from pathlib import Path
import tempfile
import os

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

from database.user_db import UserDatabase
from database.exceptions import (
    ValidationError, ReviewSessionError, ReviewSessionNotFoundError,
    QuestionEntryError, QuestionEntryNotFoundError, QuestionSourceError,
    MediaError, TagError
)


@pytest.fixture
def temp_db():
    """Create a temporary user database for testing"""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test_user.db"
        db = UserDatabase(db_path, user_id=1, username="test_user")

        # Ensure Phase 2 and Phase 4 schemas are set up
        db._ensure_phase2_schema()
        db._ensure_phase4_schema()

        # Create a test exam context
        exam_context = db.create_exam_context(
            exam_name="Test Exam",
            exam_description="A test exam for unit testing"
        )

        # Create some test subject nodes
        root_node = db.create_subject_node(
            exam_context="Test Exam",
            name="Root Topic",
            level_type="System"
        )
        child_node = db.create_subject_node(
            exam_context="Test Exam",
            name="Child Topic",
            level_type="Subsystem",
            parent_id=root_node.id
        )

        yield {
            'db': db,
            'exam_context': exam_context,
            'root_node': root_node,
            'child_node': child_node
        }

        # Ensure database connection is closed before temp directory cleanup
        db.close()


class TestQuestionSourceManagement:
    """Tests for Question Source CRUD operations"""
    
    def test_create_question_source(self, temp_db):
        """Test creating a question source"""
        db = temp_db['db']
        
        source = db.create_question_source(
            source_name="UWorld",
            source_type="commercial_prep",
            description="Popular USMLE prep",
            url="https://uworld.com"
        )
        
        assert source is not None
        assert source.source_name == "UWorld"
        assert source.source_type == "commercial_prep"
        assert source.is_active == True
    
    def test_create_question_source_invalid_type(self, temp_db):
        """Test that invalid source types are rejected"""
        db = temp_db['db']
        
        with pytest.raises(ValidationError):
            db.create_question_source(
                source_name="Bad Source",
                source_type="invalid_type"
            )
    
    def test_create_question_source_invalid_rating(self, temp_db):
        """Test that invalid ratings are rejected"""
        db = temp_db['db']
        
        with pytest.raises(ValidationError):
            db.create_question_source(
                source_name="Bad Source",
                user_rating=6  # Max is 5
            )
    
    def test_get_question_sources(self, temp_db):
        """Test retrieving question sources"""
        db = temp_db['db']
        
        # Create multiple sources
        db.create_question_source(source_name="Source A")
        db.create_question_source(source_name="Source B")
        
        sources = db.get_question_sources()
        assert len(sources) == 2
    
    def test_update_question_source(self, temp_db):
        """Test updating a question source"""
        db = temp_db['db']
        
        source = db.create_question_source(source_name="Original")
        updated = db.update_question_source(
            source.id,
            source_name="Updated",
            user_rating=5
        )
        
        assert updated.source_name == "Updated"
        assert updated.user_rating == 5
    
    def test_delete_question_source(self, temp_db):
        """Test soft-deleting a question source"""
        db = temp_db['db']
        
        source = db.create_question_source(source_name="To Delete")
        db.delete_question_source(source.id)
        
        # Should not be retrievable with default parameters
        result = db.get_question_source(source.id)
        assert result is None
        
        # Should be retrievable when including inactive
        sources = db.get_question_sources(include_inactive=True)
        assert len(sources) == 1


class TestReviewSessionManagement:
    """Tests for Review Session CRUD operations"""
    
    def test_create_review_session(self, temp_db):
        """Test creating a review session"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )
        
        assert session is not None
        assert session.total_questions == 40
        assert session.total_incorrect == 12
        assert session.entries_completed == 0
        assert session.session_status == 'in_progress'
        assert session.session_name is not None  # Auto-generated
    
    def test_create_review_session_with_source(self, temp_db):
        """Test creating a session with a question source"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        source = db.create_question_source(source_name="UWorld")
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12,
            question_source_id=source.id
        )
        
        assert session.question_source_id == source.id
        assert "UWorld" in session.session_name
    
    def test_create_review_session_invalid_exam(self, temp_db):
        """Test that invalid exam context IDs are rejected"""
        db = temp_db['db']
        
        with pytest.raises(ReviewSessionError):
            db.create_review_session(
                exam_context_id=999,
                total_questions=40,
                total_incorrect=12
            )
    
    def test_get_review_sessions(self, temp_db):
        """Test retrieving review sessions"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=10
        )
        db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=50,
            total_incorrect=15
        )
        
        sessions = db.get_review_sessions()
        assert len(sessions) == 2
    
    def test_update_review_session(self, temp_db):
        """Test updating a review session"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )
        
        updated = db.update_review_session(
            session.id,
            session_name="New Name",
            session_status="completed"
        )
        
        assert updated.session_name == "New Name"
        assert updated.session_status == "completed"

    def test_update_review_session_total_incorrect(self, temp_db):
        """Test updating total_incorrect and total_questions on a review session"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )

        # Increase total_incorrect
        updated = db.update_review_session(
            session.id,
            total_incorrect=20
        )
        assert updated.total_incorrect == 20

        # Update total_questions
        updated = db.update_review_session(
            session.id,
            total_questions=50
        )
        assert updated.total_questions == 50

        # Update both at once
        updated = db.update_review_session(
            session.id,
            total_incorrect=25,
            total_questions=60
        )
        assert updated.total_incorrect == 25
        assert updated.total_questions == 60

    def test_update_review_session_total_incorrect_validation(self, temp_db):
        """Test that total_incorrect cannot be set below entries_completed"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )

        # Simulate some entries completed
        db.update_review_session(session.id, entries_completed=5)

        # Should fail: total_incorrect < entries_completed
        import pytest
        with pytest.raises(ValueError, match="cannot be less than"):
            db.update_review_session(session.id, total_incorrect=3)

        # Should succeed: total_incorrect == entries_completed
        updated = db.update_review_session(session.id, total_incorrect=5)
        assert updated.total_incorrect == 5

        # Should succeed: total_incorrect > entries_completed
        updated = db.update_review_session(session.id, total_incorrect=15)
        assert updated.total_incorrect == 15

    def test_session_completion_percentage(self, temp_db):
        """Test session completion percentage calculation"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=10
        )
        
        assert session.completion_percentage == 0.0
        assert session.remaining_entries == 10


class TestQuestionEntryManagement:
    """Tests for Question Entry CRUD operations"""
    
    def test_create_question_entry_draft(self, temp_db):
        """Test creating a draft question entry"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )
        
        # Create entry without required fields (should be draft)
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B"
        )
        
        assert entry is not None
        assert entry.is_draft == True
        assert 'reflection' in entry.draft_missing_fields
        assert 'explanation' in entry.draft_missing_fields
        assert 'primary_subjects' in entry.draft_missing_fields
    
    def test_create_question_entry_complete(self, temp_db):
        """Test creating a complete question entry"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )
        
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="I misread the question",
            explanation="The correct answer is B because...",
            primary_subject_ids=[root_node.id]
        )
        
        assert entry.is_draft == False
        assert entry.completed_at is not None
        
        # Session should be updated
        updated_session = db.get_review_session(session.id)
        assert updated_session.entries_completed == 1
    
    def test_create_question_entry_invalid_session(self, temp_db):
        """Test that invalid session IDs are rejected"""
        db = temp_db['db']
        
        with pytest.raises(ReviewSessionNotFoundError):
            db.create_question_entry(
                review_session_id=999,
                user_answer="A",
                correct_answer="B"
            )
    
    def test_create_question_entry_invalid_difficulty(self, temp_db):
        """Test that invalid difficulty ratings are rejected"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )
        
        with pytest.raises(ValidationError):
            db.create_question_entry(
                review_session_id=session.id,
                user_answer="A",
                correct_answer="B",
                perceived_difficulty=6  # Max is 5
            )
    
    def test_get_session_entries(self, temp_db):
        """Test retrieving entries for a session"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )
        
        db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B"
        )
        db.create_question_entry(
            review_session_id=session.id,
            user_answer="C",
            correct_answer="D"
        )
        
        entries = db.get_session_entries(session.id)
        assert len(entries) == 2
        assert entries[0].entry_order == 1
        assert entries[1].entry_order == 2
    
    def test_update_question_entry(self, temp_db):
        """Test updating a question entry"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )
        
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B"
        )
        
        updated = db.update_question_entry(
            entry.id,
            reflection="Updated reflection",
            explanation="Updated explanation",
            primary_subject_ids=[root_node.id]
        )
        
        assert updated.reflection == "Updated reflection"
        assert updated.is_draft == False  # Now complete
    
    def test_delete_question_entry(self, temp_db):
        """Test deleting a question entry"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )
        
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="Test",
            explanation="Test",
            primary_subject_ids=[root_node.id]
        )
        
        # Session should have 1 completed entry
        session = db.get_review_session(session.id)
        assert session.entries_completed == 1
        
        # Delete the entry
        db.delete_question_entry(entry.id)
        
        # Entry should be gone
        assert db.get_question_entry(entry.id) is None
        
        # Session count should be decremented
        session = db.get_review_session(session.id)
        assert session.entries_completed == 0

    def test_create_dedups_subject_across_primary_and_secondary(self, temp_db):
        """The (entry, subject) UNIQUE index is mapping_type-agnostic.

        The same subject appearing in both lists must not crash the save —
        the DB layer keeps it as primary and silently drops the secondary
        copy. Regression for the IntegrityError surfaced by the entry form.
        """
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']
        child_node = temp_db['child_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12,
        )

        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            primary_subject_ids=[root_node.id, child_node.id],
            secondary_subject_ids=[root_node.id],  # duplicate of primary
        )

        rows = db.fetchall(
            "SELECT subject_node_id, mapping_type FROM entry_subject_mappings "
            "WHERE question_entry_id = ? ORDER BY subject_node_id, mapping_type",
            (entry.id,),
        )
        pairs = {(r['subject_node_id'], r['mapping_type']) for r in rows}
        assert (root_node.id, 'primary') in pairs
        assert (child_node.id, 'primary') in pairs
        assert (root_node.id, 'secondary') not in pairs  # deduped

    def test_create_dedups_within_each_subject_list(self, temp_db):
        """Duplicated ids inside a single list collapse to a single mapping."""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12,
        )

        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            primary_subject_ids=[root_node.id, root_node.id, root_node.id],
        )

        count = db.fetchone(
            "SELECT COUNT(*) AS n FROM entry_subject_mappings "
            "WHERE question_entry_id = ? AND subject_node_id = ?",
            (entry.id, root_node.id),
        )['n']
        assert count == 1

    def test_update_dedups_subject_across_primary_and_secondary(self, temp_db):
        """update_question_entry honors the same dedup as create."""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']
        child_node = temp_db['child_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12,
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            primary_subject_ids=[root_node.id],
        )

        # Re-save with overlapping lists — must not raise.
        db.update_question_entry(
            entry.id,
            primary_subject_ids=[root_node.id, child_node.id],
            secondary_subject_ids=[child_node.id],  # collides with primary
        )

        pairs = {
            (r['subject_node_id'], r['mapping_type'])
            for r in db.fetchall(
                "SELECT subject_node_id, mapping_type FROM entry_subject_mappings "
                "WHERE question_entry_id = ?",
                (entry.id,),
            )
        }
        assert (root_node.id, 'primary') in pairs
        assert (child_node.id, 'primary') in pairs
        assert (child_node.id, 'secondary') not in pairs


class TestEntryMediaManagement:
    """Tests for Entry Media CRUD operations"""
    
    def test_add_entry_media(self, temp_db):
        """Test adding media to an entry"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )
        
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B"
        )
        
        media = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="abc-123-def",
            original_filename="screenshot.png",
            mime_type="image/png",
            file_size_bytes=1024
        )
        
        assert media is not None
        assert media.file_uuid == "abc-123-def"
        assert media.original_filename == "screenshot.png"
        assert media.sort_order == 0
    
    def test_update_entry_media(self, temp_db):
        """Test updating media metadata"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )
        
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B"
        )
        
        media = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="abc-123",
            original_filename="original.png"
        )
        
        updated = db.update_entry_media(
            media.id,
            user_filename="renamed.png"
        )
        
        assert updated.user_filename == "renamed.png"
        assert updated.display_name == "renamed.png"
    
    def test_reorder_entry_media(self, temp_db):
        """Test reordering media"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=40,
            total_incorrect=12
        )
        
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B"
        )
        
        media1 = db.add_entry_media(entry_id=entry.id, file_uuid="uuid-1")
        media2 = db.add_entry_media(entry_id=entry.id, file_uuid="uuid-2")
        media3 = db.add_entry_media(entry_id=entry.id, file_uuid="uuid-3")
        
        # Reorder: 3, 1, 2
        db.reorder_entry_media(entry.id, [media3.id, media1.id, media2.id])
        
        # Verify new order
        entry_with_media = db.get_question_entry(entry.id)
        assert entry_with_media.media[0].file_uuid == "uuid-3"
        assert entry_with_media.media[1].file_uuid == "uuid-1"
        assert entry_with_media.media[2].file_uuid == "uuid-2"


class TestHierarchicalTagManagement:
    """Tests for Hierarchical Tag CRUD operations"""
    
    def test_create_tag_group(self, temp_db):
        """Test creating a tag group"""
        db = temp_db['db']
        
        group = db.create_tag_group(
            exam_context="Test Exam",
            group_name="Knowledge Issues",
            color_hex="#EF4444"
        )
        
        assert group is not None
        assert group.tag_name == "Knowledge Issues"
    
    def test_create_hierarchical_tag(self, temp_db):
        """Test creating a tag within a group"""
        db = temp_db['db']
        
        group = db.create_tag_group(
            exam_context="Test Exam",
            group_name="Knowledge Issues"
        )
        
        tag = db.create_hierarchical_tag(
            exam_context="Test Exam",
            tag_name="Knowledge Gap",
            group_id=group.id
        )
        
        assert tag is not None
        assert tag.tag_name == "Knowledge Gap"
    
    def test_get_tag_hierarchy(self, temp_db):
        """Test retrieving tag hierarchy"""
        db = temp_db['db']
        
        group = db.create_tag_group(
            exam_context="Test Exam",
            group_name="Test Group"
        )
        
        db.create_hierarchical_tag(
            exam_context="Test Exam",
            tag_name="Tag 1",
            group_id=group.id
        )
        db.create_hierarchical_tag(
            exam_context="Test Exam",
            tag_name="Tag 2",
            group_id=group.id
        )
        
        hierarchy = db.get_tag_hierarchy("Test Exam")
        
        assert len(hierarchy) == 1
        assert hierarchy[0]['name'] == "Test Group"
        assert hierarchy[0]['is_group'] == True
        assert len(hierarchy[0]['children']) == 2
    
    def test_seed_default_tags(self, temp_db):
        """Test seeding default tags"""
        db = temp_db['db']
        
        db.seed_default_tags("Test Exam")
        
        hierarchy = db.get_tag_hierarchy("Test Exam")
        
        # Should have 5 groups
        assert len(hierarchy) == 5
        
        # Check that children exist
        total_tags = sum(len(g['children']) for g in hierarchy)
        assert total_tags > 0
    
    def test_seed_default_tags_idempotent(self, temp_db):
        """Test that seeding is idempotent"""
        db = temp_db['db']
        
        db.seed_default_tags("Test Exam")
        db.seed_default_tags("Test Exam")  # Should not add duplicates
        
        hierarchy = db.get_tag_hierarchy("Test Exam")
        assert len(hierarchy) == 5


class TestSubjectSearch:
    """Tests for Subject Search functionality"""
    
    def test_search_subjects(self, temp_db):
        """Test searching subjects"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        results = db.search_subjects(
            exam_context_id=exam_context.id,
            query="Topic"
        )
        
        assert len(results) > 0
        # Should find both Root Topic and Child Topic
        names = [r['name'] for r in results]
        assert "Root Topic" in names or "Child Topic" in names
    
    def test_search_subjects_with_path(self, temp_db):
        """Test that search results include full path"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        
        results = db.search_subjects(
            exam_context_id=exam_context.id,
            query="Child"
        )
        
        assert len(results) > 0
        child_result = next((r for r in results if r['name'] == "Child Topic"), None)
        
        if child_result:
            assert ">" in child_result['path']  # Should have parent in path
            assert "Root Topic" in child_result['path']

    def test_search_entries_by_subject_name(self, temp_db):
        """Test that get_entries_paginated search_query finds entries by subject name.

        Bug fix: Search was not finding entries when searching for subject names
        from any dimension. The search should find entries associated with subjects
        whose names match the search query.
        """
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        # Create a subject with a distinctive name for searching
        unique_subject = db.create_subject_node(
            exam_context="Test Exam",
            name="Bacterial Endocarditis",
            level_type="Topic"
        )

        # Create a review session
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )

        # Create an entry with the unique subject
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="General reflection text",
            explanation="General explanation text",
            primary_subject_ids=[unique_subject.id]
        )

        # Search by subject name - should find the entry
        entries, total = db.get_entries_paginated(
            exam_context_id=exam_context.id,
            search_query="Bacterial Endocarditis"
        )

        assert total == 1
        assert len(entries) == 1
        assert entries[0].id == entry.id

        # Search by partial subject name - should also find the entry
        entries, total = db.get_entries_paginated(
            exam_context_id=exam_context.id,
            search_query="Endocarditis"
        )

        assert total == 1
        assert entries[0].id == entry.id

        # Search for non-matching term - should NOT find the entry
        entries, total = db.get_entries_paginated(
            exam_context_id=exam_context.id,
            search_query="Nonexistent Subject XYZ"
        )

        assert total == 0

    def test_search_entries_fulltext_by_subject_name(self, temp_db):
        """Test that search_entries_fulltext finds entries by subject name.

        Companion test to verify the full-text search also includes subject names.
        """
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        # Create a subject with a distinctive name
        unique_subject = db.create_subject_node(
            exam_context="Test Exam",
            name="Mitral Valve Prolapse",
            level_type="Topic"
        )

        # Create a review session
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=5,
            total_incorrect=2
        )

        # Create an entry with the unique subject
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="C",
            correct_answer="D",
            reflection="Some reflection",
            explanation="Some explanation",
            primary_subject_ids=[unique_subject.id]
        )

        # Search by subject name
        results = db.search_entries_fulltext(
            query="Mitral Valve",
            exam_context_id=exam_context.id
        )

        assert len(results) == 1
        assert results[0].id == entry.id


class TestGetMediaBySubject:
    """Tests for get_media_by_subject method - Bug #5 fix verification.

    Bug #5: get_media_by_subject was returning false positives by joining
    to entry_subject_mappings. The fix checks linked_subject_ids JSON array
    directly on the media record.
    """

    def test_media_with_linked_subject_returned(self, temp_db):
        """Test that media with target subject in linked_subject_ids is returned"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )

        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="Test reflection",
            explanation="Test explanation",
            primary_subject_ids=[root_node.id]
        )

        # Add media with linked_subject_ids containing target subject
        media = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-linked-target",
            original_filename="linked.png",
            linked_subject_ids=[root_node.id]
        )

        # Should return the media
        results = db.get_media_by_subject(
            subject_node_id=root_node.id
        )

        assert len(results) == 1
        assert results[0].file_uuid == "uuid-linked-target"

    def test_media_with_empty_linked_subject_ids_not_returned(self, temp_db):
        """Test that media with empty linked_subject_ids [] is NOT returned"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )

        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="Test reflection",
            explanation="Test explanation",
            primary_subject_ids=[root_node.id]
        )

        # Add media with empty linked_subject_ids
        media = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-empty-linked",
            original_filename="empty.png",
            linked_subject_ids=[]
        )

        # Should NOT return the media (empty array)
        results = db.get_media_by_subject(
            subject_node_id=root_node.id
        )

        assert len(results) == 0

    def test_media_with_null_linked_subject_ids_not_returned(self, temp_db):
        """Test that media with NULL linked_subject_ids is NOT returned"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )

        # Create entry without primary subjects (so media won't auto-inherit)
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B"
        )

        # Directly insert media with NULL linked_subject_ids via raw SQL
        # since add_entry_media defaults to entry's primary subjects
        db.execute("""
            INSERT INTO entry_media (
                question_entry_id, file_uuid, original_filename,
                sort_order, linked_subject_ids
            ) VALUES (?, ?, ?, ?, NULL)
        """, (entry.id, "uuid-null-linked", "null.png", 0))

        # Should NOT return the media (NULL)
        results = db.get_media_by_subject(
            subject_node_id=root_node.id
        )

        assert len(results) == 0

    def test_media_with_other_subjects_not_returned(self, temp_db):
        """Test that media linked to OTHER subjects is NOT returned"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']
        child_node = temp_db['child_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )

        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="Test reflection",
            explanation="Test explanation",
            primary_subject_ids=[child_node.id]
        )

        # Add media linked to child_node (different from root_node)
        media = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-other-subject",
            original_filename="other.png",
            linked_subject_ids=[child_node.id]
        )

        # Query for root_node - should NOT return media linked to child_node
        results = db.get_media_by_subject(
            subject_node_id=root_node.id
        )

        assert len(results) == 0

    def test_mixed_media_returns_only_linked(self, temp_db):
        """Test that only media with target subject is returned from mixed set"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']
        child_node = temp_db['child_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )

        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="Test reflection",
            explanation="Test explanation",
            primary_subject_ids=[root_node.id, child_node.id]
        )

        # Media 1: Linked to target (root_node)
        media1 = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-target-linked",
            original_filename="target.png",
            linked_subject_ids=[root_node.id]
        )

        # Media 2: Linked to other subject (child_node only)
        media2 = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-other-linked",
            original_filename="other.png",
            linked_subject_ids=[child_node.id]
        )

        # Media 3: Empty linked subjects
        media3 = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-empty",
            original_filename="empty.png",
            linked_subject_ids=[]
        )

        # Media 4: Linked to both subjects
        media4 = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-both-linked",
            original_filename="both.png",
            linked_subject_ids=[root_node.id, child_node.id]
        )

        # Query for root_node
        results = db.get_media_by_subject(
            subject_node_id=root_node.id
        )

        # Should return only media1 and media4 (those with root_node in linked_subject_ids)
        assert len(results) == 2
        result_uuids = {r.file_uuid for r in results}
        assert "uuid-target-linked" in result_uuids
        assert "uuid-both-linked" in result_uuids
        assert "uuid-other-linked" not in result_uuids
        assert "uuid-empty" not in result_uuids

    def test_get_media_by_subject_with_dimension_filter(self, temp_db):
        """Test get_media_by_subject with dimension_id filter"""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )

        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="Test reflection",
            explanation="Test explanation",
            primary_subject_ids=[root_node.id]
        )

        # Media 1: Linked to target, dimension 1
        media1 = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-dim1",
            original_filename="dim1.png",
            linked_subject_ids=[root_node.id]
        )
        db.update_entry_media(media1.id, dimension_id=1)

        # Media 2: Linked to target, dimension 2
        media2 = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-dim2",
            original_filename="dim2.png",
            linked_subject_ids=[root_node.id]
        )
        db.update_entry_media(media2.id, dimension_id=2)

        # Media 3: Linked to target, no dimension
        media3 = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-nodim",
            original_filename="nodim.png",
            linked_subject_ids=[root_node.id]
        )

        # Query with dimension_id=1
        results = db.get_media_by_subject(
            subject_node_id=root_node.id,
            dimension_id=1
        )

        # Should return only media with dimension_id=1
        assert len(results) == 1
        assert results[0].file_uuid == "uuid-dim1"

        # Query without dimension filter should return all linked
        all_results = db.get_media_by_subject(
            subject_node_id=root_node.id
        )
        assert len(all_results) == 3


class TestGetMediaBySubjects:
    """Tests for the plural get_media_by_subjects method.

    Plural sibling of get_media_by_subject — backs the "Related from other
    entries" UI surface on entry edit/detail pages.
    """

    def test_empty_subject_ids_returns_empty(self, temp_db):
        """Empty subject_ids list short-circuits to [] with no SQL."""
        db = temp_db['db']
        assert db.get_media_by_subjects([]) == []

    def test_single_subject_matches_existing_behavior(self, temp_db):
        """Single-element list matches the singular method's behavior."""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r",
            explanation="e",
            primary_subject_ids=[root_node.id]
        )
        db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-single",
            original_filename="single.png",
            linked_subject_ids=[root_node.id]
        )

        results = db.get_media_by_subjects([root_node.id])
        assert len(results) == 1
        assert results[0].file_uuid == "uuid-single"

    def test_multi_subject_union(self, temp_db):
        """Entry tagged with S1 only is returned when S1 is in the subject list."""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']
        child_node = temp_db['child_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )

        entry1 = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r1",
            explanation="e1",
            primary_subject_ids=[root_node.id]
        )
        entry2 = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r2",
            explanation="e2",
            primary_subject_ids=[child_node.id]
        )

        db.add_entry_media(
            entry_id=entry1.id,
            file_uuid="uuid-root-only",
            original_filename="r.png",
            linked_subject_ids=[root_node.id]
        )
        db.add_entry_media(
            entry_id=entry2.id,
            file_uuid="uuid-child-only",
            original_filename="c.png",
            linked_subject_ids=[child_node.id]
        )

        # Query for [root_node, child_node] — both media should be returned
        results = db.get_media_by_subjects([root_node.id, child_node.id])
        uuids = {r.file_uuid for r in results}
        assert uuids == {"uuid-root-only", "uuid-child-only"}

        # Query for [root_node] only — only root-tagged media
        results_root = db.get_media_by_subjects([root_node.id])
        assert {r.file_uuid for r in results_root} == {"uuid-root-only"}

    def test_exclude_entry_id_removes_that_entrys_media(self, temp_db):
        """exclude_entry_id filters out media belonging to the named entry."""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry_a = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="ra",
            explanation="ea",
            primary_subject_ids=[root_node.id]
        )
        entry_b = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="rb",
            explanation="eb",
            primary_subject_ids=[root_node.id]
        )

        db.add_entry_media(
            entry_id=entry_a.id,
            file_uuid="uuid-a",
            original_filename="a.png",
            linked_subject_ids=[root_node.id]
        )
        db.add_entry_media(
            entry_id=entry_b.id,
            file_uuid="uuid-b",
            original_filename="b.png",
            linked_subject_ids=[root_node.id]
        )

        results = db.get_media_by_subjects(
            [root_node.id],
            exclude_entry_id=entry_a.id
        )
        assert {r.file_uuid for r in results} == {"uuid-b"}

    def test_null_linked_subject_ids_excluded(self, temp_db):
        """Rows with NULL linked_subject_ids are excluded."""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B"
        )

        db.execute("""
            INSERT INTO entry_media (
                question_entry_id, file_uuid, original_filename,
                sort_order, linked_subject_ids, user_id
            ) VALUES (?, ?, ?, ?, NULL, ?)
        """, (entry.id, "uuid-null", "null.png", 0, db.user_id))

        results = db.get_media_by_subjects([root_node.id])
        assert results == []

    def test_empty_array_linked_subject_ids_excluded(self, temp_db):
        """Rows with linked_subject_ids = '[]' are excluded."""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r",
            explanation="e",
            primary_subject_ids=[root_node.id]
        )
        db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-empty",
            original_filename="e.png",
            linked_subject_ids=[]
        )

        results = db.get_media_by_subjects([root_node.id])
        assert results == []

    def test_multi_user_isolation(self):
        """Media belonging to a different user is not returned."""
        with tempfile.TemporaryDirectory() as td:
            db1_path = Path(td) / "u1.db"
            db2_path = Path(td) / "u2.db"

            db1 = UserDatabase(db1_path, user_id=1, username="u1")
            db1._ensure_phase2_schema()
            db1._ensure_phase4_schema()
            db2 = UserDatabase(db2_path, user_id=2, username="u2")
            db2._ensure_phase2_schema()
            db2._ensure_phase4_schema()

            try:
                # Both users share an exam-context name but their subject IDs
                # are independent per-DB. We just need a stable id for the
                # cross-user query — pick 999 to ensure it doesn't collide.
                exam1 = db1.create_exam_context(exam_name="E1")
                exam2 = db2.create_exam_context(exam_name="E2")

                root1 = db1.create_subject_node(
                    exam_context="E1",
                    name="R1",
                    level_type="System"
                )
                root2 = db2.create_subject_node(
                    exam_context="E2",
                    name="R2",
                    level_type="System"
                )

                s1 = db1.create_review_session(
                    exam_context_id=exam1.id,
                    total_questions=1,
                    total_incorrect=1
                )
                s2 = db2.create_review_session(
                    exam_context_id=exam2.id,
                    total_questions=1,
                    total_incorrect=1
                )

                e1 = db1.create_question_entry(
                    review_session_id=s1.id,
                    user_answer="A",
                    correct_answer="B",
                    reflection="r",
                    explanation="e",
                    primary_subject_ids=[root1.id]
                )
                e2 = db2.create_question_entry(
                    review_session_id=s2.id,
                    user_answer="A",
                    correct_answer="B",
                    reflection="r",
                    explanation="e",
                    primary_subject_ids=[root2.id]
                )

                db1.add_entry_media(
                    entry_id=e1.id,
                    file_uuid="u1-media",
                    original_filename="u1.png",
                    linked_subject_ids=[root1.id]
                )
                db2.add_entry_media(
                    entry_id=e2.id,
                    file_uuid="u2-media",
                    original_filename="u2.png",
                    linked_subject_ids=[root2.id]
                )

                # Even if we asked db1 about a subject id that happens to
                # also exist in db2, only db1's media should come back.
                r1 = db1.get_media_by_subjects([root1.id, root2.id])
                r1_uuids = {r.file_uuid for r in r1}
                assert "u1-media" in r1_uuids
                assert "u2-media" not in r1_uuids

                r2 = db2.get_media_by_subjects([root1.id, root2.id])
                r2_uuids = {r.file_uuid for r in r2}
                assert "u2-media" in r2_uuids
                assert "u1-media" not in r2_uuids
            finally:
                db1.close()
                db2.close()

    def test_dimension_filter(self, temp_db):
        """dimension_id narrows results to media with that dimension."""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r",
            explanation="e",
            primary_subject_ids=[root_node.id]
        )

        m1 = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-dim1",
            original_filename="d1.png",
            linked_subject_ids=[root_node.id]
        )
        db.update_entry_media(m1.id, dimension_id=1)

        m2 = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-dim2",
            original_filename="d2.png",
            linked_subject_ids=[root_node.id]
        )
        db.update_entry_media(m2.id, dimension_id=2)

        m3 = db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-nodim",
            original_filename="n.png",
            linked_subject_ids=[root_node.id]
        )

        only_d1 = db.get_media_by_subjects([root_node.id], dimension_id=1)
        assert {r.file_uuid for r in only_d1} == {"uuid-dim1"}

        unfiltered = db.get_media_by_subjects([root_node.id])
        assert len(unfiltered) == 3

    def test_limit_caps_results(self, temp_db):
        """limit caps the number of returned rows."""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r",
            explanation="e",
            primary_subject_ids=[root_node.id]
        )
        for i in range(5):
            db.add_entry_media(
                entry_id=entry.id,
                file_uuid=f"uuid-{i}",
                original_filename=f"{i}.png",
                linked_subject_ids=[root_node.id]
            )

        results = db.get_media_by_subjects([root_node.id], limit=3)
        assert len(results) == 3


class TestGetNotesBySubjects:
    """Tests for the plural get_notes_by_subjects method."""

    def test_empty_subject_ids_returns_empty(self, temp_db):
        db = temp_db['db']
        assert db.get_notes_by_subjects([]) == []

    def test_single_subject_match(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r",
            explanation="e",
            primary_subject_ids=[root_node.id]
        )
        note = db.add_entry_note(
            entry.id,
            content_html="<p>linked</p>",
            linked_subject_ids=[root_node.id]
        )

        results = db.get_notes_by_subjects([root_node.id])
        assert len(results) == 1
        assert results[0].id == note.id

    def test_multi_subject_union(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']
        child_node = temp_db['child_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        e1 = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r1",
            explanation="e1",
            primary_subject_ids=[root_node.id]
        )
        e2 = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r2",
            explanation="e2",
            primary_subject_ids=[child_node.id]
        )

        n_root = db.add_entry_note(
            e1.id,
            content_html="<p>root</p>",
            linked_subject_ids=[root_node.id]
        )
        n_child = db.add_entry_note(
            e2.id,
            content_html="<p>child</p>",
            linked_subject_ids=[child_node.id]
        )

        results = db.get_notes_by_subjects([root_node.id, child_node.id])
        ids = {r.id for r in results}
        assert ids == {n_root.id, n_child.id}

        only_root = db.get_notes_by_subjects([root_node.id])
        assert {r.id for r in only_root} == {n_root.id}

    def test_exclude_entry_id_removes_that_entrys_notes(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        e_a = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="ra",
            explanation="ea",
            primary_subject_ids=[root_node.id]
        )
        e_b = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="rb",
            explanation="eb",
            primary_subject_ids=[root_node.id]
        )

        n_a = db.add_entry_note(
            e_a.id,
            content_html="<p>a</p>",
            linked_subject_ids=[root_node.id]
        )
        n_b = db.add_entry_note(
            e_b.id,
            content_html="<p>b</p>",
            linked_subject_ids=[root_node.id]
        )

        results = db.get_notes_by_subjects(
            [root_node.id],
            exclude_entry_id=e_a.id
        )
        assert {r.id for r in results} == {n_b.id}

    def test_null_linked_subject_ids_excluded(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B"
        )

        # General note (NULL linked_subject_ids by default when None is passed)
        db.add_entry_note(entry.id, content_html="<p>general</p>")

        results = db.get_notes_by_subjects([root_node.id])
        assert results == []

    def test_empty_array_linked_subject_ids_excluded(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r",
            explanation="e",
            primary_subject_ids=[root_node.id]
        )

        # Directly insert a note row with linked_subject_ids = '[]'
        db.execute("""
            INSERT INTO entry_notes (
                question_entry_id, content_html, sort_order, linked_subject_ids
            ) VALUES (?, ?, ?, ?)
        """, (entry.id, "<p>empty</p>", 0, "[]"))

        results = db.get_notes_by_subjects([root_node.id])
        assert results == []

    def test_multi_user_isolation(self):
        """Notes in a different user DB are not visible across instances."""
        with tempfile.TemporaryDirectory() as td:
            db1_path = Path(td) / "u1.db"
            db2_path = Path(td) / "u2.db"

            db1 = UserDatabase(db1_path, user_id=1, username="u1")
            db1._ensure_phase2_schema()
            db1._ensure_phase4_schema()
            db2 = UserDatabase(db2_path, user_id=2, username="u2")
            db2._ensure_phase2_schema()
            db2._ensure_phase4_schema()

            try:
                exam1 = db1.create_exam_context(exam_name="E1")
                exam2 = db2.create_exam_context(exam_name="E2")
                root1 = db1.create_subject_node(
                    exam_context="E1",
                    name="R1",
                    level_type="System"
                )
                root2 = db2.create_subject_node(
                    exam_context="E2",
                    name="R2",
                    level_type="System"
                )

                s1 = db1.create_review_session(
                    exam_context_id=exam1.id,
                    total_questions=1,
                    total_incorrect=1
                )
                s2 = db2.create_review_session(
                    exam_context_id=exam2.id,
                    total_questions=1,
                    total_incorrect=1
                )
                e1 = db1.create_question_entry(
                    review_session_id=s1.id,
                    user_answer="A",
                    correct_answer="B",
                    reflection="r",
                    explanation="e",
                    primary_subject_ids=[root1.id]
                )
                e2 = db2.create_question_entry(
                    review_session_id=s2.id,
                    user_answer="A",
                    correct_answer="B",
                    reflection="r",
                    explanation="e",
                    primary_subject_ids=[root2.id]
                )

                db1.add_entry_note(
                    e1.id,
                    content_html="<p>u1-note</p>",
                    linked_subject_ids=[root1.id]
                )
                db2.add_entry_note(
                    e2.id,
                    content_html="<p>u2-note</p>",
                    linked_subject_ids=[root2.id]
                )

                # Per-user DBs are physically separate SQLite files, so the
                # auto-increment ids collide. Verify isolation by content
                # rather than id.
                r1 = db1.get_notes_by_subjects([root1.id, root2.id])
                r1_html = {r.content_html for r in r1}
                assert "<p>u1-note</p>" in r1_html
                assert "<p>u2-note</p>" not in r1_html

                r2 = db2.get_notes_by_subjects([root1.id, root2.id])
                r2_html = {r.content_html for r in r2}
                assert "<p>u2-note</p>" in r2_html
                assert "<p>u1-note</p>" not in r2_html
            finally:
                db1.close()
                db2.close()

    def test_limit_caps_results(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r",
            explanation="e",
            primary_subject_ids=[root_node.id]
        )
        for i in range(5):
            db.add_entry_note(
                entry.id,
                content_html=f"<p>{i}</p>",
                linked_subject_ids=[root_node.id]
            )

        results = db.get_notes_by_subjects([root_node.id], limit=3)
        assert len(results) == 3


def _make_entry_with_note(db, exam_context, root_node, *, note_html="<p>n</p>"):
    """Helper: create a fresh session+entry and attach a single note to it.

    Returns ``(entry, note)``. Used by the Wave R1B attach/detach tests so
    every test starts from a known clean setup.
    """
    session = db.create_review_session(
        exam_context_id=exam_context.id,
        total_questions=5,
        total_incorrect=2,
    )
    entry = db.create_question_entry(
        review_session_id=session.id,
        user_answer="A",
        correct_answer="B",
        reflection="r",
        explanation="e",
        primary_subject_ids=[root_node.id],
    )
    note = db.add_entry_note(
        entry.id,
        content_html=note_html,
        linked_subject_ids=[root_node.id],
    )
    return entry, note


def _make_entry_with_media(db, exam_context, *, file_uuid="uuid-mediaX"):
    """Helper: create a fresh session+entry and attach a single media item.

    Returns ``(entry, media)``.
    """
    session = db.create_review_session(
        exam_context_id=exam_context.id,
        total_questions=5,
        total_incorrect=2,
    )
    entry = db.create_question_entry(
        review_session_id=session.id,
        user_answer="A",
        correct_answer="B",
    )
    media = db.add_entry_media(
        entry_id=entry.id,
        file_uuid=file_uuid,
        original_filename=f"{file_uuid}.png",
        mime_type="image/png",
    )
    return entry, media


class TestAttachExistingNoteToEntry:
    """Wave R1B: attach_existing_note_to_entry — junction-table writer."""

    def test_attach_happy_path_creates_junction_row(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        # Source entry owns the note; target entry will reuse it.
        # ``add_entry_note`` writes an originating attachment for the
        # target's own note at sort_order=0, so the reuse-attached
        # source-note lands at sort_order=1.
        _, note = _make_entry_with_note(db, exam_context, root_node)
        target_entry, _ = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>target-original</p>"
        )

        created = db.attach_existing_note_to_entry(note.id, target_entry.id)
        assert created is True

        row = db.fetchone(
            """
            SELECT question_entry_id, note_id, sort_order
            FROM entry_note_attachments
            WHERE question_entry_id = ? AND note_id = ?
            """,
            (target_entry.id, note.id),
        )
        assert row is not None
        assert row['question_entry_id'] == target_entry.id
        assert row['note_id'] == note.id
        # Target's own note holds sort_order=0; reuse-attached note → 1.
        assert row['sort_order'] == 1

    def test_reattach_is_idempotent_no_duplicate(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        _, note = _make_entry_with_note(db, exam_context, root_node)
        target_entry, _ = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>t2</p>"
        )

        assert db.attach_existing_note_to_entry(note.id, target_entry.id) is True
        # Second call must be a no-op.
        assert db.attach_existing_note_to_entry(note.id, target_entry.id) is False

        count = db.fetchone(
            """
            SELECT COUNT(*) AS c FROM entry_note_attachments
            WHERE question_entry_id = ? AND note_id = ?
            """,
            (target_entry.id, note.id),
        )['c']
        assert count == 1

    def test_sort_order_is_max_plus_one(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        _, note_a = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>a</p>"
        )
        _, note_b = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>b</p>"
        )
        _, note_c = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>c</p>"
        )
        target_entry, target_note = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>target</p>"
        )

        db.attach_existing_note_to_entry(note_a.id, target_entry.id)
        db.attach_existing_note_to_entry(note_b.id, target_entry.id)
        db.attach_existing_note_to_entry(note_c.id, target_entry.id)

        rows = db.fetchall(
            """
            SELECT note_id, sort_order FROM entry_note_attachments
            WHERE question_entry_id = ?
            ORDER BY sort_order
            """,
            (target_entry.id,),
        )
        # Target's own note holds sort_order=0 (originating attachment
        # written by ``add_entry_note`` via _make_entry_with_note);
        # reuse-attached notes follow at 1, 2, 3.
        assert [r['sort_order'] for r in rows] == [0, 1, 2, 3]
        assert [r['note_id'] for r in rows] == [
            target_note.id, note_a.id, note_b.id, note_c.id,
        ]

    def test_explicit_sort_order_respected(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        _, note = _make_entry_with_note(db, exam_context, root_node)
        target_entry, _ = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>t</p>"
        )

        db.attach_existing_note_to_entry(
            note.id, target_entry.id, sort_order=42
        )

        row = db.fetchone(
            """
            SELECT sort_order FROM entry_note_attachments
            WHERE question_entry_id = ? AND note_id = ?
            """,
            (target_entry.id, note.id),
        )
        assert row['sort_order'] == 42

    def test_invalid_note_id_raises_validation_error(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        target_entry, _ = _make_entry_with_note(db, exam_context, root_node)
        with pytest.raises(ValidationError):
            db.attach_existing_note_to_entry(999_999, target_entry.id)

    def test_invalid_entry_id_raises_validation_error(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        _, note = _make_entry_with_note(db, exam_context, root_node)
        with pytest.raises(ValidationError):
            db.attach_existing_note_to_entry(note.id, 999_999)


class TestDetachNoteFromEntry:
    """Wave R1B: detach_note_from_entry — hard DELETE on junction."""

    def test_detach_happy_path_removes_row(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        _, note = _make_entry_with_note(db, exam_context, root_node)
        target_entry, _ = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>t</p>"
        )
        db.attach_existing_note_to_entry(note.id, target_entry.id)

        removed = db.detach_note_from_entry(note.id, target_entry.id)
        assert removed is True

        row = db.fetchone(
            """
            SELECT 1 FROM entry_note_attachments
            WHERE question_entry_id = ? AND note_id = ?
            """,
            (target_entry.id, note.id),
        )
        assert row is None

    def test_detach_when_not_attached_returns_false(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        _, note = _make_entry_with_note(db, exam_context, root_node)
        target_entry, _ = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>t</p>"
        )
        # Never attached.
        assert db.detach_note_from_entry(note.id, target_entry.id) is False

    def test_detach_does_not_delete_underlying_note(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        _, note = _make_entry_with_note(db, exam_context, root_node)
        target_entry, _ = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>t</p>"
        )
        db.attach_existing_note_to_entry(note.id, target_entry.id)
        db.detach_note_from_entry(note.id, target_entry.id)

        row = db.fetchone(
            "SELECT id FROM entry_notes WHERE id = ?", (note.id,)
        )
        assert row is not None, "underlying note must not be deleted"

    def test_detach_only_removes_one_attachment(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        _, note = _make_entry_with_note(db, exam_context, root_node)
        target_a, _ = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>a</p>"
        )
        target_b, _ = _make_entry_with_note(
            db, exam_context, root_node, note_html="<p>b</p>"
        )
        db.attach_existing_note_to_entry(note.id, target_a.id)
        db.attach_existing_note_to_entry(note.id, target_b.id)

        db.detach_note_from_entry(note.id, target_a.id)

        a_row = db.fetchone(
            """
            SELECT 1 FROM entry_note_attachments
            WHERE question_entry_id = ? AND note_id = ?
            """,
            (target_a.id, note.id),
        )
        b_row = db.fetchone(
            """
            SELECT 1 FROM entry_note_attachments
            WHERE question_entry_id = ? AND note_id = ?
            """,
            (target_b.id, note.id),
        )
        assert a_row is None
        assert b_row is not None


class TestAttachExistingMediaToEntry:
    """Wave R1B: attach_existing_media_to_entry — soft-delete-aware writer."""

    def test_attach_happy_path_creates_active_mapping(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        _, media = _make_entry_with_media(db, exam_context, file_uuid="u-a1")
        target_entry, _ = _make_entry_with_media(
            db, exam_context, file_uuid="u-target-a"
        )

        created = db.attach_existing_media_to_entry(media.id, target_entry.id)
        assert created is True

        row = db.fetchone(
            """
            SELECT is_active, sort_order FROM entry_media_mapping
            WHERE question_entry_id = ? AND media_id = ?
            """,
            (target_entry.id, media.id),
        )
        assert row is not None
        assert row['is_active'] == 1
        # Target already has its own native media (sort_order=0), so this
        # attach should slot in at sort_order=1.
        assert row['sort_order'] == 1

    def test_attach_existing_active_is_noop(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        _, media = _make_entry_with_media(db, exam_context, file_uuid="u-b1")
        target_entry, _ = _make_entry_with_media(
            db, exam_context, file_uuid="u-target-b"
        )

        assert db.attach_existing_media_to_entry(media.id, target_entry.id) is True
        # Re-attach: no-op because already active.
        assert db.attach_existing_media_to_entry(media.id, target_entry.id) is False

        count = db.fetchone(
            """
            SELECT COUNT(*) AS c FROM entry_media_mapping
            WHERE question_entry_id = ? AND media_id = ?
            """,
            (target_entry.id, media.id),
        )['c']
        assert count == 1

    def test_attach_reactivates_soft_deleted_mapping(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        _, media = _make_entry_with_media(db, exam_context, file_uuid="u-c1")
        target_entry, _ = _make_entry_with_media(
            db, exam_context, file_uuid="u-target-c"
        )

        db.attach_existing_media_to_entry(media.id, target_entry.id)
        # Soft-delete via the new detach writer.
        assert db.detach_media_from_entry(media.id, target_entry.id) is True

        before = db.fetchone(
            """
            SELECT id, is_active FROM entry_media_mapping
            WHERE question_entry_id = ? AND media_id = ?
            """,
            (target_entry.id, media.id),
        )
        assert before['is_active'] == 0
        prior_id = before['id']

        # Re-attaching must flip is_active back to 1, not insert a new row.
        reactivated = db.attach_existing_media_to_entry(media.id, target_entry.id)
        assert reactivated is True

        after = db.fetchall(
            """
            SELECT id, is_active FROM entry_media_mapping
            WHERE question_entry_id = ? AND media_id = ?
            """,
            (target_entry.id, media.id),
        )
        assert len(after) == 1
        assert after[0]['id'] == prior_id
        assert after[0]['is_active'] == 1

    def test_explicit_sort_order_respected_on_insert(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        _, media = _make_entry_with_media(db, exam_context, file_uuid="u-d1")
        # Use a brand-new entry with no media so we can pick our own sort_order.
        session = db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=5,
            total_incorrect=2,
        )
        target_entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
        )

        db.attach_existing_media_to_entry(
            media.id, target_entry.id, sort_order=7
        )
        row = db.fetchone(
            """
            SELECT sort_order FROM entry_media_mapping
            WHERE question_entry_id = ? AND media_id = ?
            """,
            (target_entry.id, media.id),
        )
        assert row['sort_order'] == 7

    def test_invalid_media_id_raises_validation_error(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        target_entry, _ = _make_entry_with_media(
            db, exam_context, file_uuid="u-e1"
        )
        with pytest.raises(ValidationError):
            db.attach_existing_media_to_entry(999_999, target_entry.id)

    def test_invalid_entry_id_raises_validation_error(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        _, media = _make_entry_with_media(db, exam_context, file_uuid="u-f1")
        with pytest.raises(ValidationError):
            db.attach_existing_media_to_entry(media.id, 999_999)


class TestDetachMediaFromEntry:
    """Wave R1B: detach_media_from_entry — soft-delete writer."""

    def test_detach_flips_is_active_to_zero(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        _, media = _make_entry_with_media(db, exam_context, file_uuid="u-g1")
        target_entry, _ = _make_entry_with_media(
            db, exam_context, file_uuid="u-target-g"
        )
        db.attach_existing_media_to_entry(media.id, target_entry.id)

        removed = db.detach_media_from_entry(media.id, target_entry.id)
        assert removed is True

        row = db.fetchone(
            """
            SELECT is_active FROM entry_media_mapping
            WHERE question_entry_id = ? AND media_id = ?
            """,
            (target_entry.id, media.id),
        )
        # Row is preserved but inactive (soft-delete).
        assert row is not None
        assert row['is_active'] == 0

    def test_detach_already_inactive_returns_false(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        _, media = _make_entry_with_media(db, exam_context, file_uuid="u-h1")
        target_entry, _ = _make_entry_with_media(
            db, exam_context, file_uuid="u-target-h"
        )
        db.attach_existing_media_to_entry(media.id, target_entry.id)
        db.detach_media_from_entry(media.id, target_entry.id)

        # Second detach: nothing to flip, returns False.
        assert db.detach_media_from_entry(media.id, target_entry.id) is False

    def test_detach_nonexistent_mapping_returns_false(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        _, media = _make_entry_with_media(db, exam_context, file_uuid="u-i1")
        target_entry, _ = _make_entry_with_media(
            db, exam_context, file_uuid="u-target-i"
        )
        # Never attached at all.
        assert db.detach_media_from_entry(media.id, target_entry.id) is False

    def test_detach_does_not_delete_media_record(self, temp_db):
        db = temp_db['db']
        exam_context = temp_db['exam_context']

        _, media = _make_entry_with_media(db, exam_context, file_uuid="u-j1")
        target_entry, _ = _make_entry_with_media(
            db, exam_context, file_uuid="u-target-j"
        )
        db.attach_existing_media_to_entry(media.id, target_entry.id)
        db.detach_media_from_entry(media.id, target_entry.id)

        row = db.fetchone(
            "SELECT id FROM entry_media WHERE id = ?", (media.id,)
        )
        assert row is not None, "underlying media row must be preserved"


class TestEntryNoteAttachments:
    """Tests for m008 entry_note_attachments junction + Wave R3 read path.

    Covers: backfill of legacy rows, the originating-attachment side
    effect of ``add_entry_note``, multi-entry attach via
    ``attach_existing_note_to_entry``, ``attachment_count`` aggregation,
    junction cascade semantics, and migration idempotency. The
    ``temp_db`` fixture constructs a full ``UserDatabase`` which runs
    the migration runner in its ``__init__`` — so by the time these
    tests start, m008 has already been applied and
    ``entry_note_attachments`` exists.
    """

    def _make_entry(self, temp_db, label="t"):
        """Helper: spin up a session + entry on the existing exam/subject."""
        db = temp_db['db']
        exam_context = temp_db['exam_context']
        root_node = temp_db['root_node']

        session = db.create_review_session(
            exam_context_id=exam_context.id,
            session_name=f"sess-{label}",
            total_questions=1,
            total_incorrect=1,
        )
        return db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            primary_subject_ids=[root_node.id],
        )

    def test_junction_table_created(self, temp_db):
        """m008 should have run via UserDatabase.__init__ — the table must exist."""
        db = temp_db['db']
        rows = db.fetchall(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='entry_note_attachments'"
        )
        assert len(rows) == 1

    def test_add_entry_note_creates_originating_attachment(self, temp_db):
        """add_entry_note should also write a junction row so the new JOIN read path sees the note."""
        db = temp_db['db']
        entry = self._make_entry(temp_db, "orig")

        note = db.add_entry_note(entry.id, content_html="<p>via add_entry_note</p>")

        rows = db.fetchall(
            "SELECT note_id FROM entry_note_attachments "
            "WHERE question_entry_id = ?",
            (entry.id,),
        )
        note_ids = {r['note_id'] for r in rows}
        assert note.id in note_ids, (
            "add_entry_note must produce an originating attachment row "
            "so the JOIN-based read path can see the note"
        )

        loaded = db.get_entry_notes_list(entry.id)
        assert any(n.id == note.id for n in loaded), (
            "the new read path (JOIN through entry_note_attachments) "
            "must return the freshly added note"
        )

    def test_backfill_on_fresh_db(self, tmp_path):
        """A legacy 1:1 entry_notes row (no junction row) should be picked up by an upgrade run.

        Simulates the production upgrade path: a user's existing 1:1
        notes (whose ``question_entry_id`` is populated) should become
        single-attachment rows in the junction after the m008 upgrade
        runs.
        """
        from datetime import date

        db_path = tmp_path / "backfill.db"
        db = UserDatabase(db_path, user_id=1, username="backfill_user")
        try:
            exam = db.create_exam_context(
                exam_name="Backfill Exam",
                exam_description="x",
            )
            session = db.create_review_session(
                exam_context_id=exam.id,
                session_name="s",
                date_encountered=date.today(),
                total_questions=1,
                total_incorrect=1,
            )
            entry = db.create_question_entry(
                review_session_id=session.id,
                user_answer="A",
                correct_answer="B",
            )

            # Simulate a pre-m008 row: write directly into entry_notes
            # and wipe any junction row that add_entry_note's
            # originating side-effect might have created.
            db.execute(
                "INSERT INTO entry_notes "
                "(question_entry_id, content_html, sort_order) "
                "VALUES (?, ?, 0)",
                (entry.id, "<p>pre-m008 note</p>"),
            )
            db.execute(
                "DELETE FROM entry_note_attachments WHERE question_entry_id = ?",
                (entry.id,),
            )
            db.conn.commit()

            # Re-run the m009 upgrade — it should backfill the
            # orphaned entry_notes row into entry_note_attachments.
            from database.migrations.user import m009_entry_note_attachments
            m009_entry_note_attachments.upgrade(db.conn)
            db.conn.commit()

            rows = db.fetchall(
                "SELECT note_id FROM entry_note_attachments "
                "WHERE question_entry_id = ?",
                (entry.id,),
            )
            assert len(rows) == 1, (
                "backfill should produce one junction row per legacy 1:1 note"
            )

            loaded = db.get_entry_notes_list(entry.id)
            assert len(loaded) == 1
            assert loaded[0].content_html == "<p>pre-m008 note</p>"
        finally:
            db.close()

    def test_note_visible_on_multiple_entries(self, temp_db):
        """A reuse-attached note must appear on BOTH its originating entry and the reusing entry."""
        db = temp_db['db']
        entry_a = self._make_entry(temp_db, "a")
        entry_b = self._make_entry(temp_db, "b")

        note = db.add_entry_note(entry_a.id, content_html="<p>shared</p>")

        # Reuse-attach to B via the Wave R1B writer.
        attached = db.attach_existing_note_to_entry(note.id, entry_b.id)
        assert attached is True

        loaded_a = db.get_entry_notes_list(entry_a.id)
        loaded_b = db.get_entry_notes_list(entry_b.id)

        assert note.id in [n.id for n in loaded_a], (
            "originating entry should still see its own note"
        )
        assert note.id in [n.id for n in loaded_b], (
            "reuse-attached entry should also see the note"
        )

    def test_attachment_count_reflects_total_attachments(self, temp_db):
        """attachment_count must equal the number of junction rows referencing the note."""
        db = temp_db['db']
        entry_a = self._make_entry(temp_db, "a")
        entry_b = self._make_entry(temp_db, "b")
        entry_c = self._make_entry(temp_db, "c")

        note = db.add_entry_note(entry_a.id, content_html="<p>counted</p>")

        # 1 originating attachment.
        loaded = db.get_entry_notes_list(entry_a.id)
        found = next(n for n in loaded if n.id == note.id)
        assert getattr(found, 'attachment_count', None) == 1

        # +1 reuse → total 2.
        db.attach_existing_note_to_entry(note.id, entry_b.id)
        loaded = db.get_entry_notes_list(entry_a.id)
        found = next(n for n in loaded if n.id == note.id)
        assert getattr(found, 'attachment_count', None) == 2

        # +1 more reuse → total 3, regardless of which entry we read from.
        db.attach_existing_note_to_entry(note.id, entry_c.id)
        loaded = db.get_entry_notes_list(entry_b.id)
        found = next(n for n in loaded if n.id == note.id)
        assert getattr(found, 'attachment_count', None) == 3

    def test_cascade_on_attaching_entry_does_not_delete_note(self, temp_db):
        """Deleting an *attaching* entry drops only its junction row, never the note record."""
        db = temp_db['db']
        entry_a = self._make_entry(temp_db, "a")  # originator
        entry_b = self._make_entry(temp_db, "b")  # attacher

        note = db.add_entry_note(entry_a.id, content_html="<p>survive</p>")
        db.attach_existing_note_to_entry(note.id, entry_b.id)

        # Sanity: both entries see the note.
        assert any(n.id == note.id for n in db.get_entry_notes_list(entry_a.id))
        assert any(n.id == note.id for n in db.get_entry_notes_list(entry_b.id))

        # Delete entry B (the attacher).
        db.execute("DELETE FROM question_entries WHERE id = ?", (entry_b.id,))
        db.conn.commit()

        # B's junction row should be gone…
        b_rows = db.fetchall(
            "SELECT * FROM entry_note_attachments WHERE question_entry_id = ?",
            (entry_b.id,),
        )
        assert len(b_rows) == 0

        # …but the note record itself must survive.
        note_row = db.fetchone(
            "SELECT * FROM entry_notes WHERE id = ?", (note.id,)
        )
        assert note_row is not None
        assert note_row['content_html'] == "<p>survive</p>"

        # And the originating entry must still see it.
        loaded_a = db.get_entry_notes_list(entry_a.id)
        assert any(n.id == note.id for n in loaded_a)

    def test_migration_idempotent(self, temp_db):
        """Running m008.upgrade twice must not error or double-insert backfill rows."""
        db = temp_db['db']
        entry = self._make_entry(temp_db, "idem")

        # Drop the junction table so we get a clean backfill to count.
        db.execute("DROP TABLE IF EXISTS entry_note_attachments")
        db.conn.commit()

        # Seed a legacy 1:1 row.
        db.execute(
            "INSERT INTO entry_notes "
            "(question_entry_id, content_html, sort_order) "
            "VALUES (?, ?, 0)",
            (entry.id, "<p>idem</p>"),
        )
        db.conn.commit()

        from database.migrations.user import m009_entry_note_attachments

        # First run: creates table + backfills.
        m009_entry_note_attachments.upgrade(db.conn)
        db.conn.commit()
        count_after_first = db.fetchone(
            "SELECT COUNT(*) AS n FROM entry_note_attachments "
            "WHERE question_entry_id = ?",
            (entry.id,),
        )['n']
        assert count_after_first == 1

        # Second run: must be a no-op (no doubles, no errors).
        m009_entry_note_attachments.upgrade(db.conn)
        db.conn.commit()
        count_after_second = db.fetchone(
            "SELECT COUNT(*) AS n FROM entry_note_attachments "
            "WHERE question_entry_id = ?",
            (entry.id,),
        )['n']
        assert count_after_second == 1, (
            "re-running m008 must not duplicate backfill rows "
            "(INSERT OR IGNORE + composite PK should prevent this)"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
