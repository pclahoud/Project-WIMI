"""
Phase 3 Tests: Database Bridge
Tests for the PyQt-JavaScript bridge layer (bridge.py)
"""
import pytest
import json
import tempfile
from pathlib import Path
from datetime import date
from typing import Generator
from unittest.mock import MagicMock, patch

from database.user_db import UserDatabase
from database.master_db import MasterDatabase
from app.bridge import DatabaseBridge, serialize_response


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except:
        pass


@pytest.fixture
def temp_master_db_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for master database"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def user_db(temp_db_path: Path) -> Generator[UserDatabase, None, None]:
    """Create a UserDatabase instance for testing"""
    db = UserDatabase(
        db_path=temp_db_path,
        user_id=1,
        username="test_user"
    )
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    """Create a MasterDatabase instance for testing"""
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    """Create a DatabaseBridge instance for testing"""
    # Bootstrap a user in master_db first
    master_db.bootstrap_first_user(
        username="test_admin",
        display_name="Test Admin"
    )
    return DatabaseBridge(master_db=master_db, user_db=user_db)


@pytest.fixture
def bridge_with_exam(bridge: DatabaseBridge) -> DatabaseBridge:
    """Bridge with a pre-created exam context"""
    bridge.createExamContext(
        exam_name="Test Exam",
        exam_description="Test description",
        exam_date="2026-06-15",
        weight_rules_json="",
        hierarchy_levels_json="",
        notes=""
    )
    return bridge


# ==================== Helper Functions ====================

def parse_response(json_str: str) -> dict:
    """Parse JSON response string"""
    return json.loads(json_str)


def assert_success(response: str) -> dict:
    """Assert response is successful and return data"""
    result = parse_response(response)
    assert result['success'] is True, f"Expected success but got error: {result.get('error')}"
    return result.get('data')


def assert_error(response: str, expected_message: str = None) -> str:
    """Assert response is an error and optionally check message"""
    result = parse_response(response)
    assert result['success'] is False, "Expected error but got success"
    if expected_message:
        assert expected_message in result.get('error', ''), \
            f"Expected '{expected_message}' in error but got: {result.get('error')}"
    return result.get('error')


# ==================== serialize_response Tests ====================

class TestSerializeResponse:
    """Tests for the serialize_response helper function"""
    
    def test_success_response(self):
        """Test creating a success response"""
        response = serialize_response(True, data={'id': 1, 'name': 'test'})
        result = parse_response(response)
        
        assert result['success'] is True
        assert result['data']['id'] == 1
        assert result['data']['name'] == 'test'
        assert 'error' not in result
    
    def test_error_response(self):
        """Test creating an error response"""
        response = serialize_response(False, error='Something went wrong')
        result = parse_response(response)
        
        assert result['success'] is False
        assert result['error'] == 'Something went wrong'
        assert 'data' not in result
    
    def test_date_serialization(self):
        """Test that dates are serialized to ISO format"""
        response = serialize_response(True, data={'date': date(2025, 12, 26)})
        result = parse_response(response)
        
        assert result['data']['date'] == '2025-12-26'


# ==================== Connection Tests ====================

class TestBridgeConnection:
    """Tests for bridge connection status"""
    
    def test_check_connection_both_connected(self, bridge: DatabaseBridge):
        """Test connection check with both databases connected"""
        response = bridge.checkConnection()
        data = assert_success(response)
        
        assert data['master_db_connected'] is True
        assert data['user_db_connected'] is True
    
    def test_check_connection_no_user_db(self, master_db: MasterDatabase):
        """Test connection check without user database"""
        bridge = DatabaseBridge(master_db=master_db, user_db=None)
        response = bridge.checkConnection()
        data = assert_success(response)
        
        assert data['master_db_connected'] is True
        assert data['user_db_connected'] is False
    
    def test_get_app_info(self, bridge: DatabaseBridge):
        """Test getting app information"""
        response = bridge.getAppInfo()
        data = assert_success(response)
        
        assert data['name'] == 'WIMI'
        assert 'version' in data
        assert data['phase'] == 4


# ==================== Exam Context Tests ====================

class TestExamContextBridge:
    """Tests for exam context operations via bridge"""
    
    def test_create_exam_context_basic(self, bridge: DatabaseBridge):
        """Test creating a basic exam context"""
        response = bridge.createExamContext(
            exam_name="USMLE Step 1",
            exam_description="Medical licensing exam",
            exam_date="",
            weight_rules_json="",
            hierarchy_levels_json="",
            notes=""
        )
        data = assert_success(response)
        
        assert data['exam_name'] == "USMLE Step 1"
        assert data['exam_description'] == "Medical licensing exam"
        assert data['is_active'] is True
        assert 'id' in data
    
    def test_create_exam_context_with_date(self, bridge: DatabaseBridge):
        """Test creating exam context with date"""
        response = bridge.createExamContext(
            exam_name="GRE",
            exam_description="",
            exam_date="2026-06-15",
            weight_rules_json="",
            hierarchy_levels_json="",
            notes=""
        )
        data = assert_success(response)
        
        assert data['exam_date'] == "2026-06-15"
    
    def test_create_exam_context_with_custom_levels(self, bridge: DatabaseBridge):
        """Test creating exam context with custom hierarchy levels"""
        levels = json.dumps(["Domain", "Topic", "Subtopic"])
        response = bridge.createExamContext(
            exam_name="CPA",
            exam_description="",
            exam_date="",
            weight_rules_json="",
            hierarchy_levels_json=levels,
            notes=""
        )
        data = assert_success(response)
        
        assert data['hierarchy_levels'] == ["Domain", "Topic", "Subtopic"]
    
    def test_create_exam_context_with_weight_rules(self, bridge: DatabaseBridge):
        """Test creating exam context with custom weight rules"""
        rules = json.dumps({
            "autonomous_weight_balancing": False,
            "precision_decimal_places": 2,
            "balancing_algorithm": "even"
        })
        response = bridge.createExamContext(
            exam_name="BAR",
            exam_description="",
            exam_date="",
            weight_rules_json=rules,
            hierarchy_levels_json="",
            notes=""
        )
        data = assert_success(response)
        
        assert data['autonomous_balancing'] is False
        assert data['precision'] == 2
        assert data['balancing_algorithm'] == "even"
    
    def test_create_duplicate_exam_context_error(self, bridge: DatabaseBridge):
        """Test that creating duplicate exam raises error"""
        bridge.createExamContext(
            exam_name="SAT",
            exam_description="",
            exam_date="",
            weight_rules_json="",
            hierarchy_levels_json="",
            notes=""
        )
        
        response = bridge.createExamContext(
            exam_name="SAT",
            exam_description="",
            exam_date="",
            weight_rules_json="",
            hierarchy_levels_json="",
            notes=""
        )
        assert_error(response, "already exists")
    
    def test_get_exam_context(self, bridge_with_exam: DatabaseBridge):
        """Test getting exam context by ID"""
        # First get all to find the ID
        all_response = bridge_with_exam.getAllExamContexts(True)
        all_data = assert_success(all_response)
        exam_id = all_data[0]['id']
        
        response = bridge_with_exam.getExamContext(exam_id)
        data = assert_success(response)
        
        assert data['exam_name'] == "Test Exam"
        assert data['id'] == exam_id
    
    def test_get_exam_context_not_found(self, bridge_with_exam: DatabaseBridge):
        """Test getting non-existent exam context"""
        response = bridge_with_exam.getExamContext(99999)
        assert_error(response, "not found")
    
    def test_get_all_exam_contexts(self, bridge: DatabaseBridge):
        """Test getting all exam contexts"""
        # Create multiple exams
        bridge.createExamContext("Exam 1", "", "", "", "", "")
        bridge.createExamContext("Exam 2", "", "", "", "", "")
        bridge.createExamContext("Exam 3", "", "", "", "", "")
        
        response = bridge.getAllExamContexts(True)
        data = assert_success(response)
        
        assert len(data) == 3
    
    def test_update_exam_context_settings(self, bridge_with_exam: DatabaseBridge):
        """Test updating exam context settings"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        settings = json.dumps({
            "exam_description": "Updated description",
            "precision": 2
        })
        
        response = bridge_with_exam.updateExamContextSettings(exam_id, settings)
        data = assert_success(response)
        
        assert data['exam_description'] == "Updated description"
        assert data['precision'] == 2
    
    def test_delete_exam_context(self, bridge_with_exam: DatabaseBridge):
        """Test soft-deleting exam context"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        response = bridge_with_exam.deleteExamContext(exam_id)
        data = assert_success(response)
        
        assert data['deleted'] is True
        
        # Verify it's no longer in active list
        all_response = bridge_with_exam.getAllExamContexts(True)
        active_data = assert_success(all_response)
        assert len(active_data) == 0


# ==================== Hierarchy Level Tests ====================

class TestHierarchyLevelsBridge:
    """Tests for hierarchy level operations via bridge"""
    
    def test_get_hierarchy_levels(self, bridge_with_exam: DatabaseBridge):
        """Test getting hierarchy levels"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        response = bridge_with_exam.getHierarchyLevels(exam_id)
        data = assert_success(response)
        
        assert len(data) == 5  # Default levels
        assert data[0]['level_name'] == "System"
        assert data[0]['level_order'] == 1
    
    def test_add_custom_hierarchy_level(self, bridge_with_exam: DatabaseBridge):
        """Test adding custom hierarchy level"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        response = bridge_with_exam.addCustomHierarchyLevel(
            exam_id, "Sub-Child", "Child of {parent_name}"
        )
        data = assert_success(response)
        
        assert data['level_name'] == "Sub-Child"
        assert data['level_order'] == 6
        assert data['is_custom_level'] is True


# ==================== Subject Node Tests ====================

class TestSubjectNodeBridge:
    """Tests for subject node operations via bridge"""
    
    def test_create_subject_node(self, bridge_with_exam: DatabaseBridge):
        """Test creating a subject node"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        node_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Cardiovascular",
            "level_type": "System",
            "parent_id": None,
            "weight": 25.0
        })
        
        response = bridge_with_exam.createSubjectNode(node_data)
        data = assert_success(response)
        
        assert data['name'] == "Cardiovascular"
        assert data['level_type'] == "System"
        assert data['weight'] == 25.0
    
    def test_create_child_node(self, bridge_with_exam: DatabaseBridge):
        """Test creating a child node"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        # Create parent
        parent_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Cardiovascular",
            "level_type": "System",
            "parent_id": None,
            "weight": 100.0
        })
        parent_response = bridge_with_exam.createSubjectNode(parent_data)
        parent_id = assert_success(parent_response)['id']
        
        # Create child
        child_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Heart Anatomy",
            "level_type": "Subsystem",
            "parent_id": parent_id,
            "weight": 50.0
        })
        
        response = bridge_with_exam.createSubjectNode(child_data)
        data = assert_success(response)
        
        assert data['name'] == "Heart Anatomy"
        assert data['parent_id'] == parent_id
    
    def test_get_subject_hierarchy(self, bridge_with_exam: DatabaseBridge):
        """Test getting full subject hierarchy"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        # Create some nodes
        node_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Root Topic",
            "level_type": "System",
            "parent_id": None,
            "weight": 100.0
        })
        bridge_with_exam.createSubjectNode(node_data)
        
        response = bridge_with_exam.getSubjectHierarchy(exam_id)
        data = assert_success(response)
        
        assert 'root_nodes' in data
        assert len(data['root_nodes']) == 1
        assert data['root_nodes'][0]['name'] == "Root Topic"
    
    def test_update_subject_node(self, bridge_with_exam: DatabaseBridge):
        """Test updating a subject node"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        # Create node
        node_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Original Name",
            "level_type": "System",
            "parent_id": None,
            "weight": 50.0
        })
        create_response = bridge_with_exam.createSubjectNode(node_data)
        node_id = assert_success(create_response)['id']
        
        # Update node
        updates = json.dumps({"name": "Updated Name"})
        response = bridge_with_exam.updateSubjectNode(node_id, updates)
        data = assert_success(response)
        
        assert data['name'] == "Updated Name"
    
    def test_delete_subject_node(self, bridge_with_exam: DatabaseBridge):
        """Test deleting (archiving) a subject node"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        # Create node
        node_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "To Be Deleted",
            "level_type": "System",
            "parent_id": None,
            "weight": 50.0
        })
        create_response = bridge_with_exam.createSubjectNode(node_data)
        node_id = assert_success(create_response)['id']
        
        # Delete node
        response = bridge_with_exam.deleteSubjectNode(node_id)
        data = assert_success(response)
        
        assert data['deleted'] is True
        
        # Verify it's no longer in hierarchy
        hierarchy_response = bridge_with_exam.getSubjectHierarchy(exam_id)
        hierarchy_data = assert_success(hierarchy_response)
        assert len(hierarchy_data['root_nodes']) == 0
    
    def test_delete_node_with_children(self, bridge_with_exam: DatabaseBridge):
        """Test deleting a node cascades to children"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        # Create parent
        parent_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Parent",
            "level_type": "System",
            "parent_id": None,
            "weight": 100.0
        })
        parent_response = bridge_with_exam.createSubjectNode(parent_data)
        parent_id = assert_success(parent_response)['id']
        
        # Create children
        for i in range(3):
            child_data = json.dumps({
                "exam_context_id": exam_id,
                "name": f"Child {i+1}",
                "level_type": "Subsystem",
                "parent_id": parent_id,
                "weight": 33.3
            })
            bridge_with_exam.createSubjectNode(child_data)
        
        # Delete parent - should cascade
        response = bridge_with_exam.deleteSubjectNode(parent_id)
        assert_success(response)
        
        # Verify all are gone
        hierarchy_response = bridge_with_exam.getSubjectHierarchy(exam_id)
        hierarchy_data = assert_success(hierarchy_response)
        assert len(hierarchy_data['root_nodes']) == 0


# ==================== Weight Management Tests ====================

class TestWeightManagementBridge:
    """Tests for weight management via bridge"""
    
    def test_update_subject_node_weight(self, bridge_with_exam: DatabaseBridge):
        """Test updating a subject node's weight"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        # Create parent with children for weight balancing
        parent_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Parent",
            "level_type": "System",
            "parent_id": None,
            "weight": 100.0
        })
        parent_response = bridge_with_exam.createSubjectNode(parent_data)
        parent_id = assert_success(parent_response)['id']
        
        # Create two children
        child1_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Child 1",
            "level_type": "Subsystem",
            "parent_id": parent_id,
            "weight": 50.0
        })
        child1_response = bridge_with_exam.createSubjectNode(child1_data)
        child1_id = assert_success(child1_response)['id']
        
        child2_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Child 2",
            "level_type": "Subsystem",
            "parent_id": parent_id,
            "weight": 50.0
        })
        bridge_with_exam.createSubjectNode(child2_data)
        
        # Update weight
        response = bridge_with_exam.updateSubjectNodeWeight(
            child1_id, 70.0, "Test update", ""
        )
        data = assert_success(response)
        
        assert data['updated_node_id'] == child1_id
        assert data['total_updates'] >= 1
    
    def test_get_weight_history(self, bridge_with_exam: DatabaseBridge):
        """Test getting weight history"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        # Create node
        node_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Test Node",
            "level_type": "System",
            "parent_id": None,
            "weight": 50.0
        })
        create_response = bridge_with_exam.createSubjectNode(node_data)
        node_id = assert_success(create_response)['id']
        
        # Update weight to create history
        bridge_with_exam.updateSubjectNodeWeight(node_id, 60.0, "First update", "")
        bridge_with_exam.updateSubjectNodeWeight(node_id, 70.0, "Second update", "")
        
        # Get history
        response = bridge_with_exam.getWeightHistory(node_id, 10)
        data = assert_success(response)
        
        assert len(data) >= 2


# ==================== Import/Export Tests ====================

class TestImportExportBridge:
    """Tests for import/export operations via bridge"""
    
    def test_export_subject_hierarchy(self, bridge_with_exam: DatabaseBridge):
        """Test exporting subject hierarchy"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        # Create some nodes
        node_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Export Test",
            "level_type": "System",
            "parent_id": None,
            "weight": 100.0
        })
        bridge_with_exam.createSubjectNode(node_data)
        
        response = bridge_with_exam.exportSubjectHierarchy(exam_id)
        data = assert_success(response)
        
        assert 'root_nodes' in data
        assert len(data['root_nodes']) == 1
    
    def test_import_subject_hierarchy(self, bridge_with_exam: DatabaseBridge):
        """Test importing subject hierarchy"""
        all_response = bridge_with_exam.getAllExamContexts(True)
        exam_id = assert_success(all_response)[0]['id']
        
        hierarchy = {
            "root_nodes": [
                {
                    "name": "Imported System",
                    "level_type": "System",
                    "weight": 50.0,
                    "children": [
                        {
                            "name": "Imported Subsystem",
                            "level_type": "Subsystem",
                            "weight": 100.0,
                            "children": []
                        }
                    ]
                }
            ]
        }
        
        response = bridge_with_exam.importSubjectHierarchy(
            exam_id, json.dumps(hierarchy)
        )
        data = assert_success(response)
        
        assert data['imported_count'] == 2
        
        # Verify import
        hierarchy_response = bridge_with_exam.getSubjectHierarchy(exam_id)
        hierarchy_data = assert_success(hierarchy_response)
        assert len(hierarchy_data['root_nodes']) == 1
        assert hierarchy_data['root_nodes'][0]['name'] == "Imported System"


# ==================== Error Handling Tests ====================

class TestBridgeErrorHandling:
    """Tests for error handling in bridge"""
    
    def test_no_user_database_error(self):
        """Test error when no user database is connected"""
        bridge = DatabaseBridge(master_db=None, user_db=None)
        
        response = bridge.createExamContext("Test", "", "", "", "", "")
        assert_error(response, "No user database connected")
    
    def test_invalid_json_in_weight_rules(self, bridge: DatabaseBridge):
        """Test error with invalid JSON in weight rules"""
        response = bridge.createExamContext(
            exam_name="Test",
            exam_description="",
            exam_date="",
            weight_rules_json="not valid json",
            hierarchy_levels_json="",
            notes=""
        )
        assert_error(response)
    
    def test_invalid_date_format(self, bridge: DatabaseBridge):
        """Test error with invalid date format"""
        response = bridge.createExamContext(
            exam_name="Test",
            exam_description="",
            exam_date="not-a-date",
            weight_rules_json="",
            hierarchy_levels_json="",
            notes=""
        )
        assert_error(response)
    
    def test_get_nonexistent_node(self, bridge_with_exam: DatabaseBridge):
        """Test error when getting non-existent subject node"""
        response = bridge_with_exam.deleteSubjectNode(99999)
        assert_error(response, "not found")


# ==================== Integration Tests ====================

class TestBridgeIntegration:
    """Integration tests for complete workflows via bridge"""
    
    def test_complete_exam_setup_workflow(self, bridge: DatabaseBridge):
        """Test complete exam setup workflow via bridge"""
        # Step 1: Create exam context
        exam_response = bridge.createExamContext(
            exam_name="Integration Test Exam",
            exam_description="Testing complete workflow",
            exam_date="2026-06-15",
            weight_rules_json="",
            hierarchy_levels_json="",
            notes="Test notes"
        )
        exam_data = assert_success(exam_response)
        exam_id = exam_data['id']
        
        # Step 2: Verify hierarchy levels
        levels_response = bridge.getHierarchyLevels(exam_id)
        levels_data = assert_success(levels_response)
        assert len(levels_data) == 5
        
        # Step 3: Create subject hierarchy
        root_data = json.dumps({
            "exam_context_id": exam_id,
            "name": "Root System",
            "level_type": "System",
            "parent_id": None,
            "weight": 100.0
        })
        root_response = bridge.createSubjectNode(root_data)
        root_id = assert_success(root_response)['id']
        
        # Create children
        child_ids = []
        for i in range(3):
            child_data = json.dumps({
                "exam_context_id": exam_id,
                "name": f"Subsystem {i+1}",
                "level_type": "Subsystem",
                "parent_id": root_id,
                "weight": 33.3
            })
            child_response = bridge.createSubjectNode(child_data)
            child_ids.append(assert_success(child_response)['id'])
        
        # Step 4: Update weight
        weight_response = bridge.updateSubjectNodeWeight(
            child_ids[0], 50.0, "Increased priority", ""
        )
        assert_success(weight_response)
        
        # Step 5: Verify hierarchy
        hierarchy_response = bridge.getSubjectHierarchy(exam_id)
        hierarchy_data = assert_success(hierarchy_response)
        
        assert len(hierarchy_data['root_nodes']) == 1
        assert len(hierarchy_data['root_nodes'][0]['children']) == 3
        
        # Step 6: Export
        export_response = bridge.exportSubjectHierarchy(exam_id)
        export_data = assert_success(export_response)
        assert len(export_data['root_nodes']) == 1
        
        # Step 7: Delete a node
        delete_response = bridge.deleteSubjectNode(child_ids[2])
        assert_success(delete_response)
        
        # Verify deletion
        hierarchy_response = bridge.getSubjectHierarchy(exam_id)
        hierarchy_data = assert_success(hierarchy_response)
        assert len(hierarchy_data['root_nodes'][0]['children']) == 2


# ==================== Plural by-subjects (Related from other entries) ====================

class TestGetMediaBySubjectsBridge:
    """Smoke tests for the getMediaBySubjects bridge slot.

    Mirrors the seed pattern used by ``TestGetMediaBySubjects`` in
    ``tests/database/test_user_db_phase4.py``.
    """

    def test_no_user_db_returns_error(self, master_db: MasterDatabase):
        """Slot must guard on missing user_db."""
        bridge = DatabaseBridge(master_db=master_db, user_db=None)
        response = bridge.getMediaBySubjects(json.dumps([42]))
        assert_error(response, "No user database connected")

    def test_invalid_json_returns_error(self, bridge: DatabaseBridge):
        """Malformed JSON for subject_ids should surface as a clean error."""
        response = bridge.getMediaBySubjects("not-json")
        assert_error(response)

    def test_non_list_payload_returns_error(self, bridge: DatabaseBridge):
        """Non-list JSON payload (e.g. an object) is rejected."""
        response = bridge.getMediaBySubjects(json.dumps({"oops": 1}))
        assert_error(response, "JSON array")

    def test_get_media_by_subjects_returns_success_shape(self, bridge: DatabaseBridge):
        """Seed one media item linked to subject 42, then verify slot returns it."""
        user_db = bridge.user_db

        # Build the minimal scaffold the seed needs (exam context, session, entry).
        exam_context = user_db.create_exam_context(
            exam_name="Bridge Plural Test",
            exam_description="getMediaBySubjects smoke test"
        )
        root_node = user_db.create_subject_node(
            exam_context="Bridge Plural Test",
            name="Root",
            level_type="System"
        )
        session = user_db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry = user_db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r",
            explanation="e",
            primary_subject_ids=[root_node.id]
        )
        media = user_db.add_entry_media(
            entry_id=entry.id,
            file_uuid="uuid-bridge-plural",
            original_filename="bp.png",
            linked_subject_ids=[root_node.id]
        )

        response = bridge.getMediaBySubjects(json.dumps([root_node.id]))
        data = assert_success(response)

        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]['id'] == media.id
        assert data[0]['file_uuid'] == "uuid-bridge-plural"

        # exclude_entry_id removes the only match
        response_excl = bridge.getMediaBySubjects(
            json.dumps([root_node.id]), entry.id
        )
        data_excl = assert_success(response_excl)
        assert data_excl == []

    def test_empty_subject_ids_returns_empty(self, bridge: DatabaseBridge):
        """Empty list short-circuits to []."""
        response = bridge.getMediaBySubjects(json.dumps([]))
        data = assert_success(response)
        assert data == []


class TestGetNotesBySubjectsBridge:
    """Smoke tests for the getNotesBySubjects bridge slot."""

    def test_no_user_db_returns_error(self, master_db: MasterDatabase):
        """Slot must guard on missing user_db."""
        bridge = DatabaseBridge(master_db=master_db, user_db=None)
        response = bridge.getNotesBySubjects(json.dumps([42]))
        assert_error(response, "No user database connected")

    def test_invalid_json_returns_error(self, bridge: DatabaseBridge):
        """Malformed JSON for subject_ids should surface as a clean error."""
        response = bridge.getNotesBySubjects("not-json")
        assert_error(response)

    def test_get_notes_by_subjects_returns_success_shape(self, bridge: DatabaseBridge):
        """Seed one note linked to a subject, then verify slot returns it."""
        user_db = bridge.user_db

        exam_context = user_db.create_exam_context(
            exam_name="Bridge Notes Plural Test",
            exam_description="getNotesBySubjects smoke test"
        )
        root_node = user_db.create_subject_node(
            exam_context="Bridge Notes Plural Test",
            name="Root",
            level_type="System"
        )
        session = user_db.create_review_session(
            exam_context_id=exam_context.id,
            total_questions=10,
            total_incorrect=5
        )
        entry = user_db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="B",
            reflection="r",
            explanation="e",
            primary_subject_ids=[root_node.id]
        )
        note = user_db.add_entry_note(
            entry_id=entry.id,
            content_html="<p>linked note</p>",
            linked_subject_ids=[root_node.id]
        )

        response = bridge.getNotesBySubjects(json.dumps([root_node.id]))
        data = assert_success(response)

        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]['id'] == note.id
        assert data[0]['content_html'] == "<p>linked note</p>"
        assert root_node.id in data[0]['linked_subject_ids']

        # exclude_entry_id removes the only match
        response_excl = bridge.getNotesBySubjects(
            json.dumps([root_node.id]), entry.id
        )
        data_excl = assert_success(response_excl)
        assert data_excl == []

    def test_empty_subject_ids_returns_empty(self, bridge: DatabaseBridge):
        """Empty list short-circuits to []."""
        response = bridge.getNotesBySubjects(json.dumps([]))
        data = assert_success(response)
        assert data == []


# ==================== Wave R2C: Attach / detach bridge slots ====================

def _seed_entry_with_note(bridge: DatabaseBridge, *, exam_name: str, note_html: str = "<p>n</p>"):
    """Helper: create an exam_context + root subject + session + entry + note
    through the bridge's user_db and return ``(entry, note, root_node)``.

    Mirrors ``tests/database/test_user_db_phase4.py::_make_entry_with_note``
    but takes a ``DatabaseBridge`` so the test reads naturally next to the
    slot calls below.
    """
    db = bridge.user_db
    exam_context = db.create_exam_context(
        exam_name=exam_name,
        exam_description="attach/detach bridge smoke"
    )
    root_node = db.create_subject_node(
        exam_context=exam_name,
        name="Root",
        level_type="System"
    )
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
        entry_id=entry.id,
        content_html=note_html,
        linked_subject_ids=[root_node.id],
    )
    return entry, note, root_node


def _seed_entry_with_media(bridge: DatabaseBridge, *, exam_name: str, file_uuid: str):
    """Helper: create an exam_context + session + entry + media item and
    return ``(entry, media)``.
    """
    db = bridge.user_db
    exam_context = db.create_exam_context(
        exam_name=exam_name,
        exam_description="attach/detach bridge smoke"
    )
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


class TestAttachExistingNoteToEntryBridge:
    """Smoke tests for the attachExistingNoteToEntry bridge slot."""

    def test_no_user_db_returns_error(self, master_db: MasterDatabase):
        bridge = DatabaseBridge(master_db=master_db, user_db=None)
        response = bridge.attachExistingNoteToEntry(1, 2)
        assert_error(response, "No user database connected")

    def test_attach_happy_path_returns_created_true(self, bridge: DatabaseBridge):
        _, note, root_node = _seed_entry_with_note(bridge, exam_name="Attach Note A")
        # A second entry to reuse the existing note on.
        db = bridge.user_db
        session = db.create_review_session(
            exam_context_id=db.fetchone(
                "SELECT id FROM exam_contexts WHERE exam_name = ?",
                ("Attach Note A",),
            )['id'],
            total_questions=3,
            total_incorrect=1,
        )
        target_entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="C",
            correct_answer="D",
            primary_subject_ids=[root_node.id],
        )

        response = bridge.attachExistingNoteToEntry(note.id, target_entry.id)
        data = assert_success(response)
        assert data == {'created': True}

        # Re-attach is idempotent.
        response2 = bridge.attachExistingNoteToEntry(note.id, target_entry.id)
        data2 = assert_success(response2)
        assert data2 == {'created': False}

    def test_invalid_note_id_returns_error(self, bridge: DatabaseBridge):
        _, _, _ = _seed_entry_with_note(bridge, exam_name="Attach Note B")
        # Any entry id will do for the target; use the one we just created.
        target_id = bridge.user_db.fetchone(
            "SELECT id FROM question_entries ORDER BY id DESC LIMIT 1"
        )['id']
        response = bridge.attachExistingNoteToEntry(99999, target_id)
        result = parse_response(response)
        assert result['success'] is False
        assert result['error']  # non-empty
        assert "99999" in result['error'] or "not found" in result['error'].lower()


class TestDetachNoteFromEntryBridge:
    """Smoke tests for the detachNoteFromEntry bridge slot."""

    def test_no_user_db_returns_error(self, master_db: MasterDatabase):
        bridge = DatabaseBridge(master_db=master_db, user_db=None)
        response = bridge.detachNoteFromEntry(1, 2)
        assert_error(response, "No user database connected")

    def test_detach_happy_path_returns_removed_true(self, bridge: DatabaseBridge):
        entry, note, _ = _seed_entry_with_note(bridge, exam_name="Detach Note A")
        # add_entry_note auto-attaches the originating attachment in
        # m008 (see commit 583fb7a), so a detach against the originating
        # entry is exercising a real junction row.
        response = bridge.detachNoteFromEntry(note.id, entry.id)
        data = assert_success(response)
        assert data == {'removed': True}

        # Second call is a no-op.
        response2 = bridge.detachNoteFromEntry(note.id, entry.id)
        data2 = assert_success(response2)
        assert data2 == {'removed': False}

    def test_detach_unknown_pair_returns_removed_false(self, bridge: DatabaseBridge):
        """Detach does not validate ids — an unknown pair is a no-op,
        not an error. (Mirrors the DB writer contract.)"""
        # No seeding — both ids are bogus.
        response = bridge.detachNoteFromEntry(99999, 88888)
        data = assert_success(response)
        assert data == {'removed': False}


class TestAttachExistingMediaToEntryBridge:
    """Smoke tests for the attachExistingMediaToEntry bridge slot."""

    def test_no_user_db_returns_error(self, master_db: MasterDatabase):
        bridge = DatabaseBridge(master_db=master_db, user_db=None)
        response = bridge.attachExistingMediaToEntry(1, 2)
        assert_error(response, "No user database connected")

    def test_attach_happy_path_returns_created_true(self, bridge: DatabaseBridge):
        _, media = _seed_entry_with_media(
            bridge, exam_name="Attach Media A", file_uuid="uuid-bridge-attach-1"
        )
        # Build a second entry under the same exam context to reuse the
        # media on.
        db = bridge.user_db
        exam_id = db.fetchone(
            "SELECT id FROM exam_contexts WHERE exam_name = ?",
            ("Attach Media A",),
        )['id']
        session = db.create_review_session(
            exam_context_id=exam_id,
            total_questions=3,
            total_incorrect=1,
        )
        target_entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer="C",
            correct_answer="D",
        )

        response = bridge.attachExistingMediaToEntry(media.id, target_entry.id)
        data = assert_success(response)
        assert data == {'created': True}

        # Idempotent for the already-active case.
        response2 = bridge.attachExistingMediaToEntry(media.id, target_entry.id)
        data2 = assert_success(response2)
        assert data2 == {'created': False}

    def test_invalid_media_id_returns_error(self, bridge: DatabaseBridge):
        entry, _ = _seed_entry_with_media(
            bridge, exam_name="Attach Media B", file_uuid="uuid-bridge-attach-2"
        )
        response = bridge.attachExistingMediaToEntry(99999, entry.id)
        result = parse_response(response)
        assert result['success'] is False
        assert result['error']
        assert "99999" in result['error'] or "not found" in result['error'].lower()


class TestDetachMediaFromEntryBridge:
    """Smoke tests for the detachMediaFromEntry bridge slot."""

    def test_no_user_db_returns_error(self, master_db: MasterDatabase):
        bridge = DatabaseBridge(master_db=master_db, user_db=None)
        response = bridge.detachMediaFromEntry(1, 2)
        assert_error(response, "No user database connected")

    def test_detach_happy_path_returns_removed_true(self, bridge: DatabaseBridge):
        entry, media = _seed_entry_with_media(
            bridge, exam_name="Detach Media A", file_uuid="uuid-bridge-detach-1"
        )

        response = bridge.detachMediaFromEntry(media.id, entry.id)
        data = assert_success(response)
        assert data == {'removed': True}

        # Second call is a no-op (mapping is already inactive).
        response2 = bridge.detachMediaFromEntry(media.id, entry.id)
        data2 = assert_success(response2)
        assert data2 == {'removed': False}

    def test_detach_unknown_pair_returns_removed_false(self, bridge: DatabaseBridge):
        """Detach does not validate ids — an unknown pair is a no-op,
        not an error."""
        response = bridge.detachMediaFromEntry(99999, 88888)
        data = assert_success(response)
        assert data == {'removed': False}


class TestLogErrorCapturesTraceback:
    """Regression for the 2026-05-26 logger triage.

    `DatabaseBridge._log_error` is invoked from inside `except` blocks
    in every bridge slot. The original implementation forwarded only
    the rendered message string, so the underlying exception's
    traceback was silently dropped — real-user save failures showed up
    as `"Error updating question entry: UNIQUE constraint failed: ..."`
    with no file/line/function context. Now it must capture
    ``traceback.format_exc()`` automatically when called from an
    ``except`` block.
    """

    def test_log_error_inside_except_attaches_stack_trace(
        self, bridge: DatabaseBridge
    ):
        from unittest.mock import MagicMock

        fake_logger = MagicMock()
        bridge.error_logger = fake_logger

        try:
            raise ValueError("simulated DB failure")
        except ValueError:
            bridge._log_error("Error updating question entry: boom")

        assert fake_logger.error.called
        _, kwargs = fake_logger.error.call_args
        assert kwargs.get('context') is None
        stack = kwargs.get('stack_trace')
        assert stack is not None
        assert 'ValueError' in stack
        assert 'simulated DB failure' in stack

    def test_log_error_outside_except_omits_stack_trace(
        self, bridge: DatabaseBridge
    ):
        """Standalone diagnostic calls (no live exception) skip the
        traceback kwarg — passing one would log a stale or empty trace."""
        from unittest.mock import MagicMock

        fake_logger = MagicMock()
        bridge.error_logger = fake_logger

        bridge._log_error("standalone diagnostic")

        assert fake_logger.error.called
        _, kwargs = fake_logger.error.call_args
        assert 'stack_trace' not in kwargs

    def test_log_error_no_logger_is_safe(self, bridge: DatabaseBridge):
        """Bridge constructed without an error_logger never crashes
        when slots fail."""
        bridge.error_logger = None
        try:
            raise RuntimeError("no logger present")
        except RuntimeError:
            bridge._log_error("safe no-op")
