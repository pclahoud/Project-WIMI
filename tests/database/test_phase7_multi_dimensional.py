"""
Test Phase 7: Multi-Dimensional Hierarchy System

Comprehensive test suite for:
1. Dimension CRUD operations
2. Hierarchy tag CRUD operations  
3. Dimension detection
4. Backward compatibility with legacy exams
5. Edge cases and error handling

Author: WIMI Development Team
Date: January 2026
"""
import pytest
import tempfile
import sqlite3
from pathlib import Path
from datetime import date, datetime
from typing import Optional

# Import database modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from database import MasterDatabase, UserDatabase
from database.base_db import DatabaseIntegrityError  # Added import
from database.exceptions import (
    ValidationError
)


# ==================== Fixtures ====================

@pytest.fixture
def temp_dir():
    """Create temporary directory for test databases"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    """Create master database"""
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def test_user(master_db):
    """Create test user"""
    return master_db.create_user(
        username="test_student",
        display_name="Test Student",
        user_types=["student"]
    )


@pytest.fixture
def user_db(master_db, test_user):
    """Create user database"""
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username
    )
    yield db
    db.close()


@pytest.fixture
def exam_context(user_db):
    """Create a test exam context"""
    user_db._ensure_phase2_schema()
    return user_db.create_exam_context(
        exam_name="NBME Surgery Shelf",
        exam_description="Test exam for multi-dimensional testing"
    )


@pytest.fixture
def simple_exam_context(user_db):
    """Create a simple exam context (no dimensions)"""
    user_db._ensure_phase2_schema()
    return user_db.create_exam_context(
        exam_name="SAT Math",
        exam_description="Simple exam without dimensions"
    )


@pytest.fixture
def multi_dim_exam_with_dimensions(user_db, exam_context):
    """Create exam with dimensions set up"""
    user_db._ensure_phase7_schema()
    
    dim1_id = user_db.create_dimension(
        exam_id=exam_context.id,
        name="Site of Care",
        display_order=1,
        is_required=True,
        description="Where the patient encounter occurs"
    )
    
    dim2_id = user_db.create_dimension(
        exam_id=exam_context.id,
        name="Physician Task",
        display_order=2,
        is_required=True,
        description="What the physician must do"
    )
    
    dim3_id = user_db.create_dimension(
        exam_id=exam_context.id,
        name="System",
        display_order=3,
        is_required=False,
        allow_multiple=True,
        description="Organ system involved"
    )
    
    return {
        'exam_context': exam_context,
        'dimensions': {
            'site_of_care': dim1_id,
            'physician_task': dim2_id,
            'system': dim3_id
        }
    }


@pytest.fixture
def subject_nodes(user_db, exam_context):
    """Create test subject nodes for hierarchy"""
    nodes = {}
    
    nodes['emergency'] = user_db.create_subject_node(
        exam_context="NBME Surgery Shelf",
        name="Emergency Department",
        level_type="Site"
    )
    
    nodes['inpatient'] = user_db.create_subject_node(
        exam_context="NBME Surgery Shelf",
        name="Inpatient Ward",
        level_type="Site"
    )
    
    nodes['diagnosis'] = user_db.create_subject_node(
        exam_context="NBME Surgery Shelf",
        name="Diagnosis",
        level_type="Task"
    )
    
    nodes['management'] = user_db.create_subject_node(
        exam_context="NBME Surgery Shelf",
        name="Management",
        level_type="Task"
    )
    
    nodes['cardio'] = user_db.create_subject_node(
        exam_context="NBME Surgery Shelf",
        name="Cardiovascular",
        level_type="System"
    )
    
    return nodes


@pytest.fixture
def review_session_with_entries(user_db, exam_context):
    """Create a review session with question entries"""
    user_db._ensure_phase4_schema()
    
    session = user_db.create_review_session(
        exam_context_id=exam_context.id,
        total_questions=10,
        total_incorrect=3
    )
    
    entries = []
    for i in range(3):
        entry = user_db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection=f"Test reflection {i}",
            explanation=f"Test explanation {i}",
            primary_subject_ids=[]
        )
        entries.append(entry)
    
    return {
        'session': session,
        'entries': entries
    }


# ==================== Dimension CRUD Tests ====================

class TestDimensionCRUD:
    """Test dimension CRUD operations"""
    
    def test_create_dimension(self, user_db, exam_context):
        """Test creating dimension with all fields"""
        user_db._ensure_phase7_schema()
        
        dim_id = user_db.create_dimension(
            exam_id=exam_context.id,
            name="Site of Care",
            display_order=1,
            is_required=True,
            allow_multiple=False,
            description="Where the patient encounter occurs"
        )
        
        assert dim_id is not None
        assert dim_id > 0
        
        dim = user_db.get_dimension(dim_id)
        assert dim is not None
        assert dim['name'] == "Site of Care"
        assert dim['display_order'] == 1
        assert dim['is_required'] == 1
        assert dim['allow_multiple'] == 0
        assert dim['description'] == "Where the patient encounter occurs"
    
    def test_create_dimension_minimal(self, user_db, exam_context):
        """Test creating dimension with minimal required fields"""
        user_db._ensure_phase7_schema()
        
        dim_id = user_db.create_dimension(
            exam_id=exam_context.id,
            name="Task",
            display_order=1
        )
        
        assert dim_id > 0
        
        dim = user_db.get_dimension(dim_id)
        assert dim['is_required'] == 1
        assert dim['allow_multiple'] == 0
        assert dim['description'] is None
    
    def test_create_dimension_duplicate_name(self, user_db, exam_context):
        """Test creating dimension with duplicate name (should fail)"""
        user_db._ensure_phase7_schema()
        
        user_db.create_dimension(
            exam_id=exam_context.id,
            name="Test Dimension",
            display_order=1
        )
        
        # Changed from sqlite3.IntegrityError to DatabaseIntegrityError
        with pytest.raises(DatabaseIntegrityError):
            user_db.create_dimension(
                exam_id=exam_context.id,
                name="Test Dimension",
                display_order=2
            )
    
    def test_create_dimension_duplicate_display_order(self, user_db, exam_context):
        """Test creating dimension with duplicate display_order (should fail)"""
        user_db._ensure_phase7_schema()
        
        user_db.create_dimension(
            exam_id=exam_context.id,
            name="First Dimension",
            display_order=1
        )
        
        # Changed from sqlite3.IntegrityError to DatabaseIntegrityError
        with pytest.raises(DatabaseIntegrityError):
            user_db.create_dimension(
                exam_id=exam_context.id,
                name="Second Dimension",
                display_order=1
            )
    
    def test_get_exam_dimensions(self, user_db, exam_context):
        """Test retrieving all dimensions for an exam, verify ordering"""
        user_db._ensure_phase7_schema()
        
        user_db.create_dimension(exam_id=exam_context.id, name="Third", display_order=3)
        user_db.create_dimension(exam_id=exam_context.id, name="First", display_order=1)
        user_db.create_dimension(exam_id=exam_context.id, name="Second", display_order=2)
        
        dimensions = user_db.get_exam_dimensions(exam_context.id)
        
        assert len(dimensions) == 3
        assert dimensions[0]['name'] == "First"
        assert dimensions[1]['name'] == "Second"
        assert dimensions[2]['name'] == "Third"
    
    def test_get_exam_dimensions_empty(self, user_db, exam_context):
        """Test retrieving dimensions for exam with none"""
        user_db._ensure_phase7_schema()
        
        dimensions = user_db.get_exam_dimensions(exam_context.id)
        assert dimensions == []
    
    def test_get_dimension(self, user_db, exam_context):
        """Test retrieving single dimension by ID"""
        user_db._ensure_phase7_schema()
        
        created_id = user_db.create_dimension(
            exam_id=exam_context.id,
            name="Test",
            display_order=1
        )
        
        dim = user_db.get_dimension(created_id)
        assert dim is not None
        assert dim['id'] == created_id
        assert dim['name'] == "Test"
    
    def test_get_dimension_not_found(self, user_db, exam_context):
        """Test retrieving non-existent dimension (should return None)"""
        user_db._ensure_phase7_schema()
        
        dim = user_db.get_dimension(99999)
        assert dim is None
    
    def test_update_dimension_name(self, user_db, exam_context):
        """Test updating dimension name"""
        user_db._ensure_phase7_schema()
        
        dim_id = user_db.create_dimension(
            exam_id=exam_context.id,
            name="Original Name",
            display_order=1
        )
        
        rows = user_db.update_dimension(dim_id, name="Updated Name")
        
        assert rows == 1
        dim = user_db.get_dimension(dim_id)
        assert dim['name'] == "Updated Name"
    
    def test_update_dimension_all_fields(self, user_db, exam_context):
        """Test updating all fields at once"""
        user_db._ensure_phase7_schema()
        
        dim_id = user_db.create_dimension(
            exam_id=exam_context.id,
            name="Original",
            display_order=1,
            is_required=True,
            allow_multiple=False,
            description="Original description"
        )
        
        rows = user_db.update_dimension(
            dim_id,
            name="Updated",
            display_order=2,
            is_required=False,
            allow_multiple=True,
            description="Updated description"
        )
        
        assert rows == 1
        dim = user_db.get_dimension(dim_id)
        assert dim['name'] == "Updated"
        assert dim['display_order'] == 2
        assert dim['is_required'] == 0
        assert dim['allow_multiple'] == 1
        assert dim['description'] == "Updated description"
    
    def test_update_dimension_no_fields(self, user_db, exam_context):
        """Test update with no fields (should return 0)"""
        user_db._ensure_phase7_schema()
        
        dim_id = user_db.create_dimension(
            exam_id=exam_context.id,
            name="Test",
            display_order=1
        )
        
        rows = user_db.update_dimension(dim_id)
        assert rows == 0
    
    def test_delete_dimension(self, user_db, exam_context):
        """Test deleting dimension"""
        user_db._ensure_phase7_schema()
        # Add dependency: delete cascades to tags which require question_entries table
        user_db._ensure_phase4_schema()
        
        dim_id = user_db.create_dimension(
            exam_id=exam_context.id,
            name="To Delete",
            display_order=1
        )
        
        rows = user_db.delete_dimension(dim_id)
        
        assert rows == 1
        assert user_db.get_dimension(dim_id) is None
    
    def test_delete_dimension_cascades_tags(
        self, user_db, multi_dim_exam_with_dimensions, 
        subject_nodes, review_session_with_entries
    ):
        """Test that deleting dimension cascades to delete tags"""
        user_db._ensure_phase7_schema()
        
        dim_id = multi_dim_exam_with_dimensions['dimensions']['site_of_care']
        entry = review_session_with_entries['entries'][0]
        node = subject_nodes['emergency']
        
        user_db.create_hierarchy_tag(
            entry_id=entry.id,
            hierarchy_id=node.id,
            dimension_id=dim_id
        )
        
        tags = user_db.get_entry_tags(entry.id)
        assert len(tags) == 1
        
        user_db.delete_dimension(dim_id)
        
        tags = user_db.get_entry_tags(entry.id)
        assert len(tags) == 0


# ==================== Tag CRUD Tests ====================

class TestHierarchyTagCRUD:
    """Test hierarchy tag CRUD operations"""
    
    def test_create_tag(
        self, user_db, multi_dim_exam_with_dimensions,
        subject_nodes, review_session_with_entries
    ):
        """Test creating tag"""
        dim_id = multi_dim_exam_with_dimensions['dimensions']['site_of_care']
        entry = review_session_with_entries['entries'][0]
        node = subject_nodes['emergency']
        
        tag_id = user_db.create_hierarchy_tag(
            entry_id=entry.id,
            hierarchy_id=node.id,
            dimension_id=dim_id
        )
        
        assert tag_id is not None
        assert tag_id > 0
    
    def test_create_tag_duplicate(
        self, user_db, multi_dim_exam_with_dimensions,
        subject_nodes, review_session_with_entries
    ):
        """Test creating duplicate tag (should fail)"""
        dim_id = multi_dim_exam_with_dimensions['dimensions']['site_of_care']
        entry = review_session_with_entries['entries'][0]
        node = subject_nodes['emergency']
        
        user_db.create_hierarchy_tag(
            entry_id=entry.id,
            hierarchy_id=node.id,
            dimension_id=dim_id
        )
        
        # Changed from sqlite3.IntegrityError to DatabaseIntegrityError
        with pytest.raises(DatabaseIntegrityError):
            user_db.create_hierarchy_tag(
                entry_id=entry.id,
                hierarchy_id=node.id,
                dimension_id=dim_id
            )
    
    def test_get_entry_tags(
        self, user_db, multi_dim_exam_with_dimensions,
        subject_nodes, review_session_with_entries
    ):
        """Test retrieving all tags for an entry, verify ordering"""
        dims = multi_dim_exam_with_dimensions['dimensions']
        entry = review_session_with_entries['entries'][0]
        
        user_db.create_hierarchy_tag(
            entry_id=entry.id,
            hierarchy_id=subject_nodes['cardio'].id,
            dimension_id=dims['system']
        )
        user_db.create_hierarchy_tag(
            entry_id=entry.id,
            hierarchy_id=subject_nodes['emergency'].id,
            dimension_id=dims['site_of_care']
        )
        user_db.create_hierarchy_tag(
            entry_id=entry.id,
            hierarchy_id=subject_nodes['diagnosis'].id,
            dimension_id=dims['physician_task']
        )
        
        tags = user_db.get_entry_tags(entry.id)
        
        assert len(tags) == 3
        assert tags[0]['dimension_name'] == "Site of Care"
        assert tags[1]['dimension_name'] == "Physician Task"
        assert tags[2]['dimension_name'] == "System"
    
    def test_get_entry_tags_empty(self, user_db, review_session_with_entries):
        """Test retrieving tags for entry with none"""
        user_db._ensure_phase7_schema()
        
        entry = review_session_with_entries['entries'][0]
        tags = user_db.get_entry_tags(entry.id)
        
        assert tags == []
    
    def test_delete_tag(
        self, user_db, multi_dim_exam_with_dimensions,
        subject_nodes, review_session_with_entries
    ):
        """Test deleting single tag"""
        dim_id = multi_dim_exam_with_dimensions['dimensions']['site_of_care']
        entry = review_session_with_entries['entries'][0]
        node = subject_nodes['emergency']
        
        tag_id = user_db.create_hierarchy_tag(
            entry_id=entry.id,
            hierarchy_id=node.id,
            dimension_id=dim_id
        )
        
        rows = user_db.delete_hierarchy_tag(tag_id)
        
        assert rows == 1
        tags = user_db.get_entry_tags(entry.id)
        assert len(tags) == 0
    
    def test_delete_entry_tags_by_dimension(
        self, user_db, multi_dim_exam_with_dimensions,
        subject_nodes, review_session_with_entries
    ):
        """Test deleting all tags in a dimension for an entry"""
        dims = multi_dim_exam_with_dimensions['dimensions']
        entry = review_session_with_entries['entries'][0]
        
        user_db.create_hierarchy_tag(
            entry_id=entry.id,
            hierarchy_id=subject_nodes['emergency'].id,
            dimension_id=dims['site_of_care']
        )
        user_db.create_hierarchy_tag(
            entry_id=entry.id,
            hierarchy_id=subject_nodes['diagnosis'].id,
            dimension_id=dims['physician_task']
        )
        
        rows = user_db.delete_entry_tags_by_dimension(
            entry_id=entry.id,
            dimension_id=dims['site_of_care']
        )
        
        assert rows == 1
        
        tags = user_db.get_entry_tags(entry.id)
        assert len(tags) == 1
        assert tags[0]['dimension_name'] == "Physician Task"


# ==================== Detection Tests ====================

class TestDimensionDetection:
    """Test dimension detection functionality"""
    
    def test_exam_uses_dimensions_false(self, user_db, simple_exam_context):
        """Test detection for simple exam (should return False)"""
        user_db._ensure_phase7_schema()
        
        result = user_db.exam_uses_dimensions(simple_exam_context.id)
        assert result is False
    
    def test_exam_uses_dimensions_true(
        self, user_db, multi_dim_exam_with_dimensions
    ):
        """Test detection for multi-dimensional exam (should return True)"""
        exam = multi_dim_exam_with_dimensions['exam_context']
        
        result = user_db.exam_uses_dimensions(exam.id)
        assert result is True
    
    def test_exam_uses_dimensions_after_delete_all(
        self, user_db, exam_context
    ):
        """Test detection after deleting all dimensions"""
        user_db._ensure_phase7_schema()
        # Add dependency: delete cascades to tags which require question_entries table
        user_db._ensure_phase4_schema()
        
        dim_id = user_db.create_dimension(
            exam_id=exam_context.id,
            name="Temporary",
            display_order=1
        )
        
        assert user_db.exam_uses_dimensions(exam_context.id) is True
        
        user_db.delete_dimension(dim_id)
        
        assert user_db.exam_uses_dimensions(exam_context.id) is False


# ==================== Backward Compatibility Tests ====================

class TestBackwardCompatibility:
    """Test backward compatibility with legacy exams"""
    
    def test_legacy_exam_hierarchy_still_works(self, user_db, simple_exam_context):
        """Test that existing hierarchy queries still work"""
        # Phase 7 adds 'dimension_id' column to subject_nodes, needed for this test query
        user_db._ensure_phase7_schema()
        
        node = user_db.create_subject_node(
            exam_context="SAT Math",
            name="Algebra",
            level_type="Domain"
        )
        
        assert node is not None
        assert node.name == "Algebra"
        
        result = user_db.fetchone(
            "SELECT dimension_id FROM subject_nodes WHERE id = ?",
            (node.id,)
        )
        assert result['dimension_id'] is None
    
    def test_exam_uses_dimensions_legacy(self, user_db, simple_exam_context):
        """Test detection returns False for legacy exam"""
        user_db._ensure_phase7_schema()
        
        result = user_db.exam_uses_dimensions(simple_exam_context.id)
        assert result is False
    
    def test_phase7_schema_is_additive(self, user_db, simple_exam_context):
        """Test that Phase 7 schema doesn't break existing tables"""
        user_db._ensure_phase4_schema()
        
        session = user_db.create_review_session(
            exam_context_id=simple_exam_context.id,
            total_questions=10,
            total_incorrect=2
        )
        
        user_db._ensure_phase7_schema()
        
        retrieved_session = user_db.get_review_session(session.id)
        assert retrieved_session is not None
        assert retrieved_session.total_questions == 10


# ==================== Integration Tests ====================

class TestPhase7Integration:
    """Integration tests for Phase 7 with other phases"""
    
    def test_full_multidimensional_workflow(self, user_db, exam_context):
        """Test complete workflow: create exam, add dimensions, tag entries"""
        user_db._ensure_phase7_schema()
        user_db._ensure_phase4_schema()
        
        site_dim = user_db.create_dimension(
            exam_id=exam_context.id,
            name="Site",
            display_order=1,
            is_required=True
        )
        
        task_dim = user_db.create_dimension(
            exam_id=exam_context.id,
            name="Task",
            display_order=2,
            is_required=True
        )
        
        emergency = user_db.create_subject_node(
            exam_context=exam_context.exam_name,
            name="Emergency",
            level_type="Site"
        )
        
        diagnosis = user_db.create_subject_node(
            exam_context=exam_context.exam_name,
            name="Diagnosis",
            level_type="Task"
        )
        
        session = user_db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=5,
            total_incorrect=1
        )
        
        entry = user_db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="I misread the question",
            explanation="The correct approach is...",
            primary_subject_ids=[]
        )
        
        user_db.create_hierarchy_tag(
            entry_id=entry.id,
            hierarchy_id=emergency.id,
            dimension_id=site_dim
        )
        
        user_db.create_hierarchy_tag(
            entry_id=entry.id,
            hierarchy_id=diagnosis.id,
            dimension_id=task_dim
        )
        
        assert user_db.exam_uses_dimensions(exam_context.id) is True
        
        tags = user_db.get_entry_tags(entry.id)
        assert len(tags) == 2
        
        validation = user_db.validate_entry_dimensions_complete(
            entry_id=entry.id,
            exam_id=exam_context.id
        )
        assert validation['is_complete'] is True


# ==================== Cross-Dimensional Polyhierarchy (Non-Goal) ====================

class TestCrossDimensionalPolyhierarchyRejection:
    """Verify the §2 plan non-goal: a single subject node cannot have parents
    in different dimensions in this initial polyhierarchy migration.

    The migration plan (POLYHIERARCHY_MIGRATION.md §2) explicitly defers
    cross-dimensional polyhierarchy: "Both parents of a multi-parent leaf
    must share the same ``dimension_id`` for now." The current schema
    enforces this at the level of ``subject_nodes.dimension_id`` (a node
    has exactly one dimension_id), so any attempt to add an edge from a
    parent in a different dimension is logically a domain violation even
    if not blocked at the SQL layer.

    This test documents the invariant: when both endpoints of an edge
    have non-NULL ``dimension_id`` values, they must match. The current
    code does not enforce this in ``add_edge`` (a deliberate scope cut
    for this migration), so the test simply asserts the data shape that
    a future enforcement layer would protect against.
    """

    def test_node_has_single_dimension_id(self, multi_dim_exam_with_dimensions, user_db):
        """A subject_nodes row stores a single dimension_id. The polyhierarchy
        migration does not move dimension_id onto subject_edges (§3.1 plan),
        so the schema's single-dimension invariant per node is preserved.
        """
        site_dim = multi_dim_exam_with_dimensions['dimensions']['site_of_care']
        task_dim = multi_dim_exam_with_dimensions['dimensions']['physician_task']

        # Create two parent nodes in different dimensions.
        emergency = user_db.create_subject_node(
            exam_context="NBME Surgery Shelf",
            name="Emergency",
            level_type="Site",
            dimension_id=site_dim,
        )
        diagnosis = user_db.create_subject_node(
            exam_context="NBME Surgery Shelf",
            name="Diagnosis",
            level_type="Task",
            dimension_id=task_dim,
        )

        # The two nodes have distinct dimension_id values — confirm the
        # schema invariant that motivates the §2 non-goal.
        emergency_row = user_db.fetchone(
            "SELECT dimension_id FROM subject_nodes WHERE id = ?",
            (emergency.id,),
        )
        diagnosis_row = user_db.fetchone(
            "SELECT dimension_id FROM subject_nodes WHERE id = ?",
            (diagnosis.id,),
        )
        assert emergency_row['dimension_id'] == site_dim
        assert diagnosis_row['dimension_id'] == task_dim
        assert emergency_row['dimension_id'] != diagnosis_row['dimension_id']

        # A leaf logically belongs to a single dimension. Phase 7's
        # multi-dimensional analytics queries (e.g.
        # ``_cross_dimension_query_with_children``) all filter by
        # dimension_id at seed time, ensuring traversal stays within a
        # dimension even after the polyhierarchy migration.

    def test_descendant_query_stays_within_dimension(
        self, multi_dim_exam_with_dimensions, user_db
    ):
        """Within a single dimension, descendant traversal works as
        expected; cross-dimension descendants are *not* surfaced because
        the seed query filters by dimension_id and edges between
        same-dimension nodes form the only legal polyhierarchy.
        """
        site_dim = multi_dim_exam_with_dimensions['dimensions']['site_of_care']

        emergency = user_db.create_subject_node(
            exam_context="NBME Surgery Shelf",
            name="Emergency",
            level_type="Site",
            dimension_id=site_dim,
        )
        triage = user_db.create_subject_node(
            exam_context="NBME Surgery Shelf",
            name="Triage",
            level_type="Site",
            parent_id=emergency.id,
            dimension_id=site_dim,
        )

        descendants = user_db._get_descendant_node_ids(emergency.id)
        assert triage.id in descendants
        # Traversal yields only nodes within the same dimension because
        # the parent-child edges (created by create_subject_node) only
        # connect nodes within the same dimension.
        for d_id in descendants:
            row = user_db.fetchone(
                "SELECT dimension_id FROM subject_nodes WHERE id = ?",
                (d_id,),
            )
            assert row['dimension_id'] == site_dim


if __name__ == "__main__":
    pytest.main([__file__, "-v"])