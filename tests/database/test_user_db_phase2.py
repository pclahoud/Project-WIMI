"""
Phase 2 Tests: Exam Context & Weight Management
Tests for exam_contexts, hierarchy_level_definitions, and subject_node_weights
"""
import pytest
import tempfile
from pathlib import Path
from datetime import date, datetime
from typing import Generator

from database.user_db import UserDatabase
from database.exceptions import (
    ValidationError, SubjectNodeError,
    ExamContextAlreadyExistsError, ExamContextError,
    WeightValidationError, WeightBalancingError,
    HierarchyLevelError
)
from database.models import (
    ExamContextConfig, HierarchyLevelDefinition,
    SubjectNodeWeight, WeightUpdateResult
)


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    # Cleanup
    try:
        Path(f.name).unlink()
    except:
        pass


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
def user_db_with_exam(user_db: UserDatabase) -> UserDatabase:
    """UserDatabase with a precreated exam context"""
    user_db.create_exam_context(
        exam_name="USMLE Step 1",
        exam_description="Medical licensing exam"
    )
    return user_db


@pytest.fixture
def user_db_with_hierarchy(user_db_with_exam: UserDatabase) -> UserDatabase:
    """UserDatabase with exam context and subject hierarchy"""
    db = user_db_with_exam
    
    # Create root node
    root = db.create_subject_node(
        exam_context="USMLE Step 1",
        name="Root",
        level_type="Root",
        exam_weight_low=100.0,
        exam_weight_high=100.0
    )
    
    # Create 3 children with equal weights
    db.create_subject_node(
        exam_context="USMLE Step 1",
        name="Cardiovascular",
        parent_id=root.id,
        level_type="System",
        exam_weight_low=33.3,
        exam_weight_high=33.3
    )
    
    db.create_subject_node(
        exam_context="USMLE Step 1",
        name="Respiratory",
        parent_id=root.id,
        level_type="System",
        exam_weight_low=33.3,
        exam_weight_high=33.3
    )
    
    db.create_subject_node(
        exam_context="USMLE Step 1",
        name="Neurology",
        parent_id=root.id,
        level_type="System",
        exam_weight_low=33.4,
        exam_weight_high=33.4
    )
    
    return db


# ==================== Exam Context Tests ====================

class TestExamContextCreation:
    """Tests for creating exam contexts"""
    
    def test_create_exam_context_basic(self, user_db: UserDatabase):
        """Test creating a basic exam context"""
        exam = user_db.create_exam_context(
            exam_name="SAT",
            exam_description="College entrance exam"
        )
        
        assert exam is not None
        assert exam.exam_name == "SAT"
        assert exam.exam_description == "College entrance exam"
        assert exam.is_active is True
        assert exam.user_id == 1
    
    def test_create_exam_context_with_date(self, user_db: UserDatabase):
        """Test creating exam context with exam date"""
        exam_date = date(2026, 6, 15)
        exam = user_db.create_exam_context(
            exam_name="GRE",
            exam_date=exam_date
        )
        
        assert exam.exam_date == exam_date
    
    def test_create_exam_context_default_hierarchy_levels(self, user_db: UserDatabase):
        """Test that default hierarchy levels are created"""
        exam = user_db.create_exam_context(exam_name="MCAT")
        
        assert exam.default_hierarchy_levels == ["System", "Subsystem", "Topic", "Subtopic", "Child"]
        
        # Check hierarchy level definitions were created
        levels = user_db.get_hierarchy_levels(exam.id)
        assert len(levels) == 5
        assert levels[0].level_name == "System"
        assert levels[0].is_required is True
        assert levels[4].level_name == "Child"
        assert levels[4].is_required is False
    
    def test_create_exam_context_custom_hierarchy_levels(self, user_db: UserDatabase):
        """Test creating exam context with custom hierarchy levels"""
        custom_levels = ["Domain", "Topic", "Subtopic"]
        exam = user_db.create_exam_context(
            exam_name="CPA",
            hierarchy_levels=custom_levels
        )
        
        assert exam.default_hierarchy_levels == custom_levels
        
        levels = user_db.get_hierarchy_levels(exam.id)
        assert len(levels) == 3
        assert levels[0].level_name == "Domain"
    
    def test_create_exam_context_default_weight_rules(self, user_db: UserDatabase):
        """Test default weight validation rules"""
        exam = user_db.create_exam_context(exam_name="LSAT")
        
        rules = exam.weight_validation_rules
        assert rules['autonomous_weight_balancing'] is True
        assert rules['allow_absolute_weight_editing'] is False
        assert rules['precision_decimal_places'] == 1
        assert rules['require_exact_100'] is True
        assert rules['balancing_algorithm'] == 'proportional'
    
    def test_create_exam_context_custom_weight_rules(self, user_db: UserDatabase):
        """Test creating exam context with custom weight rules"""
        custom_rules = {
            "autonomous_weight_balancing": False,
            "allow_absolute_weight_editing": True,
            "precision_decimal_places": 2,
            "require_exact_100": False,
            "balancing_algorithm": "even"
        }
        exam = user_db.create_exam_context(
            exam_name="BAR",
            weight_validation_rules=custom_rules
        )
        
        assert exam.weight_validation_rules == custom_rules
        assert exam.autonomous_balancing is False
        assert exam.precision == 2
        assert exam.balancing_algorithm == "even"
    
    def test_create_duplicate_exam_context_raises_error(self, user_db: UserDatabase):
        """Test that creating duplicate exam context raises error"""
        user_db.create_exam_context(exam_name="SAT")
        
        with pytest.raises(ExamContextAlreadyExistsError):
            user_db.create_exam_context(exam_name="SAT")
    
    def test_create_exam_context_with_notes(self, user_db: UserDatabase):
        """Test creating exam context with notes"""
        exam = user_db.create_exam_context(
            exam_name="ACT",
            notes="Preparing for Fall 2026 admission"
        )
        
        assert exam.notes == "Preparing for Fall 2026 admission"


class TestExamContextRetrieval:
    """Tests for retrieving exam contexts"""
    
    def test_get_exam_context_by_id(self, user_db: UserDatabase):
        """Test getting exam context by ID"""
        created = user_db.create_exam_context(exam_name="SAT")
        
        retrieved = user_db.get_exam_context_config(created.id)
        
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.exam_name == "SAT"
    
    def test_get_exam_context_by_name(self, user_db: UserDatabase):
        """Test getting exam context by name"""
        user_db.create_exam_context(exam_name="GRE")
        
        retrieved = user_db.get_exam_context_by_name("GRE")
        
        assert retrieved is not None
        assert retrieved.exam_name == "GRE"
    
    def test_get_exam_context_not_found(self, user_db: UserDatabase):
        """Test getting non-existent exam context returns None"""
        # First ensure the schema exists by creating an exam
        user_db.create_exam_context(exam_name="Dummy")
        
        # Now test with non-existent ID
        result = user_db.get_exam_context_config(999)
        assert result is None
        
        result = user_db.get_exam_context_by_name("NonExistent")
        assert result is None
    
    def test_get_all_exam_contexts(self, user_db: UserDatabase):
        """Test getting all exam contexts"""
        user_db.create_exam_context(exam_name="SAT")
        user_db.create_exam_context(exam_name="GRE")
        user_db.create_exam_context(exam_name="MCAT")
        
        exams = user_db.get_all_exam_contexts()
        
        assert len(exams) == 3
    
    def test_get_all_exam_contexts_active_only(self, user_db: UserDatabase):
        """Test filtering for active exam contexts only"""
        exam1 = user_db.create_exam_context(exam_name="SAT")
        exam2 = user_db.create_exam_context(exam_name="GRE")
        
        # Deactivate one exam
        user_db.update_exam_context_settings(exam2.id, is_active=False)
        
        active_exams = user_db.get_all_exam_contexts(active_only=True)
        all_exams = user_db.get_all_exam_contexts(active_only=False)
        
        assert len(active_exams) == 1
        assert len(all_exams) == 2


class TestExamContextUpdate:
    """Tests for updating exam contexts"""
    
    def test_update_weight_validation_rules(self, user_db: UserDatabase):
        """Test updating weight validation rules"""
        exam = user_db.create_exam_context(exam_name="SAT")
        
        new_rules = {
            "autonomous_weight_balancing": False,
            "allow_absolute_weight_editing": True,
            "precision_decimal_places": 0,
            "require_exact_100": True,
            "balancing_algorithm": "even"
        }
        
        updated = user_db.update_exam_context_settings(
            exam.id,
            weight_validation_rules=new_rules
        )
        
        assert updated.weight_validation_rules == new_rules
    
    def test_update_exam_description(self, user_db: UserDatabase):
        """Test updating exam description"""
        exam = user_db.create_exam_context(exam_name="SAT")
        
        updated = user_db.update_exam_context_settings(
            exam.id,
            exam_description="New description"
        )
        
        assert updated.exam_description == "New description"
    
    def test_update_exam_date(self, user_db: UserDatabase):
        """Test updating exam date"""
        exam = user_db.create_exam_context(exam_name="SAT")
        
        new_date = date(2026, 12, 15)
        updated = user_db.update_exam_context_settings(
            exam.id,
            exam_date=new_date
        )
        
        assert updated.exam_date == new_date
    
    def test_update_is_active(self, user_db: UserDatabase):
        """Test deactivating exam context"""
        exam = user_db.create_exam_context(exam_name="SAT")
        
        updated = user_db.update_exam_context_settings(
            exam.id,
            is_active=False
        )
        
        assert updated.is_active is False


# ==================== Hierarchy Level Tests ====================

class TestHierarchyLevels:
    """Tests for hierarchy level definitions"""
    
    def test_get_hierarchy_levels(self, user_db_with_exam: UserDatabase):
        """Test getting hierarchy levels for an exam"""
        exam = user_db_with_exam.get_exam_context_by_name("USMLE Step 1")
        levels = user_db_with_exam.get_hierarchy_levels(exam.id)
        
        assert len(levels) == 5
        assert levels[0].level_order == 1
        assert levels[4].level_order == 5
    
    def test_hierarchy_level_is_required(self, user_db_with_exam: UserDatabase):
        """Test that first 3 levels are marked as required"""
        exam = user_db_with_exam.get_exam_context_by_name("USMLE Step 1")
        levels = user_db_with_exam.get_hierarchy_levels(exam.id)
        
        assert levels[0].is_required is True
        assert levels[1].is_required is True
        assert levels[2].is_required is True
        assert levels[3].is_required is False
        assert levels[4].is_required is False
    
    def test_add_custom_hierarchy_level(self, user_db_with_exam: UserDatabase):
        """Test adding a custom hierarchy level beyond default 5"""
        exam = user_db_with_exam.get_exam_context_by_name("USMLE Step 1")
        
        new_level = user_db_with_exam.add_custom_hierarchy_level(
            exam_context_id=exam.id,
            level_name="Sub-Child"
        )
        
        assert new_level.level_name == "Sub-Child"
        assert new_level.level_order == 6
        assert new_level.is_custom_level is True
        assert new_level.is_required is False
    
    def test_add_custom_level_default_name(self, user_db_with_exam: UserDatabase):
        """Test adding custom level with default name"""
        exam = user_db_with_exam.get_exam_context_by_name("USMLE Step 1")
        
        new_level = user_db_with_exam.add_custom_hierarchy_level(exam_context_id=exam.id)
        
        assert new_level.level_name == "Level 6"
    
    def test_add_custom_level_with_template(self, user_db_with_exam: UserDatabase):
        """Test adding custom level with display name template"""
        exam = user_db_with_exam.get_exam_context_by_name("USMLE Step 1")
        
        new_level = user_db_with_exam.add_custom_hierarchy_level(
            exam_context_id=exam.id,
            level_name="Detail",
            display_name_template="Detail of {parent_name}"
        )
        
        assert new_level.display_name_template == "Detail of {parent_name}"
        assert new_level.get_display_name("Cardiology") == "Detail of Cardiology"
    
    def test_update_hierarchy_level(self, user_db_with_exam: UserDatabase):
        """Test updating a hierarchy level"""
        exam = user_db_with_exam.get_exam_context_by_name("USMLE Step 1")
        levels = user_db_with_exam.get_hierarchy_levels(exam.id)
        
        updated = user_db_with_exam.update_hierarchy_level(
            level_id=levels[0].id,
            level_name="Body System",
            display_name_template="{name}"
        )
        
        assert updated.level_name == "Body System"
        assert updated.display_name_template == "{name}"


# ==================== Weight Management Tests ====================

class TestWeightValidation:
    """Tests for weight validation"""
    
    def test_validate_weight_in_range(self, user_db_with_hierarchy: UserDatabase):
        """Test that valid weights pass validation"""
        db = user_db_with_hierarchy
        # Get Cardiovascular node
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = [n.children[0] for n in nodes][0]
        
        # Update to valid weight - should not raise
        result = db.update_subject_node_weight(cardio.id, 50.0)
        assert result.updated_node.exam_weight_low == 50.0
    
    def test_validate_weight_negative_raises_error(self, user_db_with_hierarchy: UserDatabase):
        """Test that negative weight raises error"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = [n.children[0] for n in nodes][0]
        
        with pytest.raises(WeightValidationError) as exc_info:
            db.update_subject_node_weight(cardio.id, -5.0)
        assert "between 0% and 100%" in str(exc_info.value)
    
    def test_validate_weight_over_100_raises_error(self, user_db_with_hierarchy: UserDatabase):
        """Test that weight over 100 raises error"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = [n.children[0] for n in nodes][0]
        
        with pytest.raises(WeightValidationError):
            db.update_subject_node_weight(cardio.id, 105.0)
    
    def test_validate_weight_precision(self, user_db_with_hierarchy: UserDatabase):
        """Test weight precision validation"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = [n.children[0] for n in nodes][0]
        
        # One decimal place should be fine with default settings
        result = db.update_subject_node_weight(cardio.id, 50.5)
        assert result.updated_node.exam_weight_low == 50.5


class TestProportionalWeightBalancing:
    """Tests for proportional weight distribution algorithm"""
    
    def test_proportional_balancing_basic(self, user_db_with_hierarchy: UserDatabase):
        """Test basic proportional weight balancing"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        root = nodes[0]
        
        # Get children IDs
        cardio = root.children[0]
        resp = root.children[1]
        neuro = root.children[2]
        
        # Update Cardiovascular from 33.3% to 50%
        result = db.update_subject_node_weight(
            cardio.id,
            50.0,
            reason="Test proportional balancing"
        )
        
        # Check main node was updated
        assert result.updated_node.exam_weight_low == 50.0
        
        # Check siblings were adjusted
        assert len(result.affected_siblings) == 2
        assert result.total_updates == 3
        
        # Verify total still equals 100%
        updated_children = db.get_subject_hierarchy("USMLE Step 1")[0].children
        total = sum(c.exam_weight_low for c in updated_children)
        assert abs(total - 100.0) < 0.1
    
    def test_proportional_balancing_preserves_ratios(self, user_db_with_hierarchy: UserDatabase):
        """Test that proportional balancing preserves sibling ratios"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        root = nodes[0]
        
        # First, set unequal weights: Resp=40%, Neuro=20% (Cardio remains at 33.3 + diff)
        db.update_subject_node_weight(root.children[1].id, 40.0)
        
        # Now get fresh state
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        root = nodes[0]
        
        resp_before = root.children[1].exam_weight_low
        neuro_before = root.children[2].exam_weight_low
        
        # Skip if weights are too close to zero
        if neuro_before > 1.0:
            ratio_before = resp_before / neuro_before
            
            # Update Cardio to trigger rebalancing
            db.update_subject_node_weight(root.children[0].id, 60.0)
            
            # Check that ratio is approximately preserved
            nodes = db.get_subject_hierarchy("USMLE Step 1")
            root = nodes[0]
            resp_after = root.children[1].exam_weight_low
            neuro_after = root.children[2].exam_weight_low
            
            if neuro_after > 0.1:  # Avoid division by near-zero
                ratio_after = resp_after / neuro_after
                # Allow some tolerance due to rounding
                assert abs(ratio_before - ratio_after) < 0.5


class TestEvenWeightBalancing:
    """Tests for even weight distribution algorithm"""
    
    def test_even_balancing(self, user_db: UserDatabase):
        """Test even weight distribution"""
        # Create exam with even balancing algorithm
        exam = user_db.create_exam_context(
            exam_name="Test Exam",
            weight_validation_rules={
                "autonomous_weight_balancing": True,
                "allow_absolute_weight_editing": False,
                "precision_decimal_places": 1,
                "require_exact_100": True,
                "balancing_algorithm": "even"
            }
        )
        
        # Create hierarchy
        root = user_db.create_subject_node(
            exam_context="Test Exam",
            name="Root",
            level_type="Root",
            exam_weight_low=100.0,
            exam_weight_high=100.0
        )
        
        # Create 2 children with equal weights
        child1 = user_db.create_subject_node(
            exam_context="Test Exam",
            name="Child 1",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=50.0,
            exam_weight_high=50.0
        )
        
        child2 = user_db.create_subject_node(
            exam_context="Test Exam",
            name="Child 2",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=50.0,
            exam_weight_high=50.0
        )
        
        # Update child1 to 70% - child2 should get 30%
        result = user_db.update_subject_node_weight(child1.id, 70.0)
        
        assert result.updated_node.exam_weight_low == 70.0
        assert len(result.affected_siblings) == 1
        assert result.affected_siblings[0].exam_weight_low == 30.0


class TestWeightHistory:
    """Tests for weight change history tracking"""
    
    def test_weight_history_created(self, user_db_with_hierarchy: UserDatabase):
        """Test that weight history records are created"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        
        # Update weight
        db.update_subject_node_weight(cardio.id, 50.0, reason="Test reason")
        
        # Check history
        history = db.get_weight_history(cardio.id)
        
        assert len(history) >= 1
        assert history[0].weight_value == 50.0
        assert history[0].change_type == 'manual_edit'
        assert history[0].edited_by == 'user'
        assert history[0].edited_reason == 'Test reason'
    
    def test_weight_history_tracks_previous_weight(self, user_db_with_hierarchy: UserDatabase):
        """Test that previous weight is tracked"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        
        original_weight = cardio.exam_weight_low
        
        db.update_subject_node_weight(cardio.id, 50.0)
        
        history = db.get_weight_history(cardio.id)
        assert history[0].previous_weight == original_weight
    
    def test_weight_history_tracks_affected_siblings(self, user_db_with_hierarchy: UserDatabase):
        """Test that affected siblings are tracked"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        
        db.update_subject_node_weight(cardio.id, 50.0)
        
        history = db.get_weight_history(cardio.id)
        assert len(history[0].affected_siblings) == 2  # Two other siblings
    
    def test_sibling_weight_history_auto_recalculate(self, user_db_with_hierarchy: UserDatabase):
        """Test that siblings have auto_recalculate history entries"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        resp = nodes[0].children[1]
        
        db.update_subject_node_weight(cardio.id, 50.0)
        
        # Check respiratory's history
        history = db.get_weight_history(resp.id)
        
        # Should have an auto_recalculate entry
        auto_entries = [h for h in history if h.change_type == 'auto_recalculate']
        assert len(auto_entries) >= 1
        assert auto_entries[0].edited_by == 'system'
    
    def test_get_recent_weight_changes(self, user_db_with_hierarchy: UserDatabase):
        """Test getting recent weight changes across all nodes"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        
        # Make some changes
        db.update_subject_node_weight(cardio.id, 50.0)
        
        # Get recent changes
        changes = db.get_recent_weight_changes(days_back=1)
        
        assert len(changes) >= 1
    
    def test_get_weight_statistics(self, user_db_with_hierarchy: UserDatabase):
        """Test getting weight change statistics"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        
        # Make a change
        db.update_subject_node_weight(cardio.id, 50.0)
        
        # Get statistics
        stats = db.get_weight_statistics()
        
        assert stats['total_changes'] >= 1
        assert stats['manual_edits'] >= 1


class TestWeightUpdateResult:
    """Tests for WeightUpdateResult dataclass"""
    
    def test_weight_update_result_properties(self, user_db_with_hierarchy: UserDatabase):
        """Test WeightUpdateResult properties"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        
        result = db.update_subject_node_weight(cardio.id, 50.0)
        
        assert result.had_side_effects is True
        assert result.total_updates == 3
        assert len(result.weight_history_ids) == 3
    
    def test_weight_update_no_side_effects_for_single_child(self, user_db: UserDatabase):
        """Test that single child update has no side effects"""
        # Create exam with single child
        user_db.create_exam_context(exam_name="Test")
        
        root = user_db.create_subject_node(
            exam_context="Test",
            name="Root",
            level_type="Root",
            exam_weight_low=100.0,
            exam_weight_high=100.0
        )
        
        child = user_db.create_subject_node(
            exam_context="Test",
            name="Only Child",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=100.0,
            exam_weight_high=100.0
        )
        
        result = user_db.update_subject_node_weight(child.id, 100.0)
        
        assert result.had_side_effects is False
        assert result.total_updates == 1


class TestEdgeCases:
    """Tests for edge cases and error handling"""
    
    def test_update_weight_node_not_found(self, user_db: UserDatabase):
        """Test updating weight for non-existent node"""
        user_db.create_exam_context(exam_name="Test")
        user_db._ensure_phase2_schema()
        
        with pytest.raises(SubjectNodeError):
            user_db.update_subject_node_weight(999, 50.0)
    
    def test_update_weight_without_exam_context(self, user_db: UserDatabase):
        """Test updating weight when no exam context is configured"""
        # Create subject node without corresponding exam_contexts entry
        root = user_db.create_subject_node(
            exam_context="Unconfigured",
            name="Root",
            level_type="Root",
            exam_weight_low=100.0,
            exam_weight_high=100.0
        )
        
        child = user_db.create_subject_node(
            exam_context="Unconfigured",
            name="Child",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=100.0,
            exam_weight_high=100.0
        )
        
        # Should use default settings
        result = user_db.update_subject_node_weight(child.id, 100.0)
        assert result.updated_node.exam_weight_low == 100.0
    
    def test_weight_history_with_user_notes(self, user_db_with_hierarchy: UserDatabase):
        """Test weight history with user notes"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        
        db.update_subject_node_weight(
            cardio.id,
            50.0,
            reason="More focus needed",
            user_notes="Based on practice exam performance"
        )
        
        history = db.get_weight_history(cardio.id)
        assert history[0].user_notes == "Based on practice exam performance"
    
    def test_multiple_weight_updates_history(self, user_db_with_hierarchy: UserDatabase):
        """Test multiple weight updates create multiple history entries"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        
        # First update
        db.update_subject_node_weight(cardio.id, 40.0)
        
        # Second update
        db.update_subject_node_weight(cardio.id, 50.0)
        
        # Third update
        db.update_subject_node_weight(cardio.id, 45.0)
        
        history = db.get_weight_history(cardio.id)
        
        # Should have 3 manual_edit entries
        manual_entries = [h for h in history if h.change_type == 'manual_edit']
        assert len(manual_entries) == 3
        
        # Most recent should be 45.0
        assert history[0].weight_value == 45.0


class TestSubjectNodeWeightModel:
    """Tests for SubjectNodeWeight model"""
    
    def test_weight_delta_property(self, user_db_with_hierarchy: UserDatabase):
        """Test weight_delta property calculation"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        
        db.update_subject_node_weight(cardio.id, 50.0)
        
        history = db.get_weight_history(cardio.id)
        
        assert history[0].weight_delta is not None
        assert abs(history[0].weight_delta - (50.0 - 33.3)) < 0.1
    
    def test_is_user_edit_property(self, user_db_with_hierarchy: UserDatabase):
        """Test is_user_edit property"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        
        db.update_subject_node_weight(cardio.id, 50.0)
        
        history = db.get_weight_history(cardio.id)
        
        assert history[0].is_user_edit is True
        assert history[0].is_auto_adjustment is False
    
    def test_is_auto_adjustment_property(self, user_db_with_hierarchy: UserDatabase):
        """Test is_auto_adjustment property for sibling updates"""
        db = user_db_with_hierarchy
        nodes = db.get_subject_hierarchy("USMLE Step 1")
        cardio = nodes[0].children[0]
        resp = nodes[0].children[1]
        
        db.update_subject_node_weight(cardio.id, 50.0)
        
        # Check respiratory's history
        history = db.get_weight_history(resp.id)
        auto_entry = [h for h in history if h.change_type == 'auto_recalculate'][0]
        
        assert auto_entry.is_auto_adjustment is True
        assert auto_entry.is_user_edit is False


# ==================== Integration Tests ====================

class TestPhase2Integration:
    """Integration tests combining multiple Phase 2 features"""
    
    def test_complete_exam_setup_workflow(self, user_db: UserDatabase):
        """Test complete exam setup workflow"""
        # Step 1: Create exam context
        exam = user_db.create_exam_context(
            exam_name="Medical Boards",
            exam_description="Comprehensive medical exam",
            exam_date=date(2026, 6, 1)
        )
        
        assert exam.exam_name == "Medical Boards"
        
        # Step 2: Verify hierarchy levels
        levels = user_db.get_hierarchy_levels(exam.id)
        assert len(levels) == 5
        
        # Step 3: Add a custom level
        custom_level = user_db.add_custom_hierarchy_level(
            exam_context_id=exam.id,
            level_name="Micro-Topic"
        )
        
        levels = user_db.get_hierarchy_levels(exam.id)
        assert len(levels) == 6
        
        # Step 4: Create subject hierarchy
        root = user_db.create_subject_node(
            exam_context="Medical Boards",
            name="All Systems",
            level_type="Root",
            exam_weight_low=100.0,
            exam_weight_high=100.0
        )
        
        cardio = user_db.create_subject_node(
            exam_context="Medical Boards",
            name="Cardiovascular",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=50.0,
            exam_weight_high=50.0
        )
        
        resp = user_db.create_subject_node(
            exam_context="Medical Boards",
            name="Respiratory",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=50.0,
            exam_weight_high=50.0
        )
        
        # Step 5: Update weights with balancing
        result = user_db.update_subject_node_weight(
            cardio.id,
            60.0,
            reason="Cardio more heavily weighted on this exam"
        )
        
        assert result.updated_node.exam_weight_low == 60.0
        assert result.affected_siblings[0].exam_weight_low == 40.0
        
        # Step 6: Verify history
        history = user_db.get_weight_history(cardio.id)
        assert len(history) >= 1
        
        # Step 7: Get statistics
        stats = user_db.get_weight_statistics("Medical Boards")
        assert stats['total_changes'] >= 1
    
    def test_schema_auto_creation(self, user_db: UserDatabase):
        """Test that Phase 2 schema is eagerly created at UserDatabase init.

        Contract: Phase 2 tables exist immediately after UserDatabase construction
        (eager init), not lazily on first method call. This avoids "no such table"
        errors when bridge methods or analytics queries run before any exam context
        has been created by the user.
        """
        # Phase 2 tables should exist right after init, before any exam is created
        tables = user_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = {row['name'] for row in tables}

        assert 'exam_contexts' in table_names
        assert 'hierarchy_level_definitions' in table_names
        assert 'subject_node_weights' in table_names

        # Sanity: creating an exam context still works (idempotent re-init)
        exam = user_db.create_exam_context(exam_name="Test")
        assert exam is not None
