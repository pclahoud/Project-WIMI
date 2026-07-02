"""
Tests for Hybrid Weight System
Tests importing official weights, relative weights, sibling rebalancing,
and effective weight calculations.
"""
import pytest
import tempfile
from pathlib import Path
from datetime import date
import json

# Import from database package
from database import MasterDatabase, UserDatabase
from database.exceptions import (
    SubjectNodeError, WeightValidationError, ValidationError
)


# ==============================================================================
# FIXTURES
# ==============================================================================

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
    """Create user database with proper schema initialization."""
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username
    )
    
    # Ensure phase 2 tables exist for exam contexts
    db._ensure_phase2_schema()
    
    # Create a test exam context
    db.create_exam_context(
        exam_name="USMLE Step 1",
        exam_description="Test exam for hybrid weights"
    )
    
    yield db
    db.close()


@pytest.fixture
def user_db_with_subjects(user_db):
    """Create database with sample subject hierarchy."""
    # Create top-level systems with absolute weights
    gi = user_db.create_subject_node_with_weight(
        exam_context="USMLE Step 1",
        name="Gastrointestinal System",
        level_type="System",
        exam_weight_low=20,
        exam_weight_high=25,
        weight_source='official',
        weight_locked=True,
        exam_source="NBME Content Outline 2024"
    )
    
    cardio = user_db.create_subject_node_with_weight(
        exam_context="USMLE Step 1",
        name="Cardiovascular System",
        level_type="System",
        exam_weight_low=10,
        exam_weight_high=15,
        weight_source='official',
        weight_locked=True,
        exam_source="NBME Content Outline 2024"
    )
    
    # Create child topics with relative weights under GI
    esophagus = user_db.create_subject_node_with_weight(
        exam_context="USMLE Step 1",
        name="Esophagus",
        level_type="Topic",
        parent_id=gi.id,
        relative_weight=15,
        weight_source='user_estimate'
    )
    
    stomach = user_db.create_subject_node_with_weight(
        exam_context="USMLE Step 1",
        name="Stomach",
        level_type="Topic",
        parent_id=gi.id,
        relative_weight=25,
        weight_source='user_estimate'
    )
    
    small_intestine = user_db.create_subject_node_with_weight(
        exam_context="USMLE Step 1",
        name="Small Intestine",
        level_type="Topic",
        parent_id=gi.id,
        relative_weight=35,
        weight_source='user_estimate'
    )
    
    colon = user_db.create_subject_node_with_weight(
        exam_context="USMLE Step 1",
        name="Colon",
        level_type="Topic",
        parent_id=gi.id,
        relative_weight=25,
        weight_source='user_estimate'
    )
    
    return user_db


# ==============================================================================
# TESTS: RELATIVE WEIGHT UPDATE WITH REBALANCING
# ==============================================================================

class TestRelativeWeightRebalancing:
    """Tests for relative weight updates and explicit sibling rebalancing.

    Stage 2 of WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md changed
    ``update_subject_relative_weight`` to never auto-mutate siblings;
    callers must invoke ``rebalance_sibling_edge_weights`` explicitly.
    The tests below were updated to assert the new contract — see
    ``test_edge_anchor_semantics.py`` for the canonical edge-level
    coverage.
    """

    def test_update_relative_weight_basic(self, user_db_with_subjects):
        """Basic single-edge update (no implicit rebalance under Stage 2)."""
        db = user_db_with_subjects

        # Get the Esophagus node
        gi = next(s for s in db.get_subject_hierarchy("USMLE Step 1") if s.name == "Gastrointestinal System")
        esophagus = next(c for c in gi.children if c.name == "Esophagus")

        # Update relative weight
        result = db.update_subject_relative_weight(
            node_id=esophagus.id,
            relative_weight=20,
            reason="Test update"
        )

        assert result['old_weight'] == 15
        assert result['new_weight'] == 20
        assert result['updated_node'].relative_weight == 20
        # Stage 2 contract: writer never rebalances. Auto-rebalance is
        # opt-in via ``rebalance_sibling_edge_weights``.
        assert result['rebalanced'] is False
        assert result['affected_siblings'] == []

    def test_explicit_rebalance_distributes_proportionally(self, user_db_with_subjects):
        """Explicit ``rebalance_sibling_edge_weights`` redistributes proportionally.

        Stage 2 moved the proportional-distribution logic to an
        explicit, parent-scoped entry point. This test exercises the
        new method directly: bump Esophagus to 25%, then call rebalance
        on the parent and verify that the remaining 75% is split
        proportionally across the other three children.
        """
        db = user_db_with_subjects

        # Get the GI system and its children
        gi = next(s for s in db.get_subject_hierarchy("USMLE Step 1") if s.name == "Gastrointestinal System")
        esophagus = next(c for c in gi.children if c.name == "Esophagus")

        # Original: Esophagus=15, Stomach=25, Small Intestine=35, Colon=25 (total=100)
        # Step 1: write the new value on Esophagus (no auto-rebalance).
        write_result = db.update_subject_relative_weight(
            node_id=esophagus.id,
            relative_weight=25
        )
        assert write_result['rebalanced'] is False
        assert write_result['affected_siblings'] == []

        # Step 2: anchor Esophagus on its primary edge so the explicit
        # rebalance leaves the user-typed value alone. Without this the
        # rebalancer would still see Esophagus as adjustable.
        esophagus_edge = db.fetchone(
            "SELECT id FROM subject_edges "
            "WHERE child_id = ? AND is_primary = TRUE",
            (esophagus.id,),
        )
        db.execute(
            "UPDATE subject_edges SET is_anchor = TRUE WHERE id = ?",
            (esophagus_edge['id'],),
        )

        # Step 3: explicitly rebalance the parent.
        rebalance_result = db.rebalance_sibling_edge_weights(parent_id=gi.id)
        assert rebalance_result['ok'] is True
        # 3 siblings (Stomach, Small Intestine, Colon) get adjusted;
        # Esophagus is anchored so it is in 'skipped'.
        assert len(rebalance_result['affected_edges']) == 3
        assert any(s['reason'] == 'anchored' for s in rebalance_result['skipped'])

        # Total of the edges (anchored 25% + adjustable budget 75%)
        # should sum to ~100%.
        all_edges = db.get_sibling_edges(gi.id)
        total = sum((e['relative_weight'] or 0.0) for e in all_edges)
        assert abs(total - 100) < 0.1  # Within 0.1% tolerance
    
    def test_cannot_update_locked_weight(self, user_db_with_subjects):
        """Test that locked weights cannot be updated."""
        db = user_db_with_subjects
        
        # Get the GI system (which has locked=True)
        gi = next(s for s in db.get_subject_hierarchy("USMLE Step 1") if s.name == "Gastrointestinal System")
        
        with pytest.raises(SubjectNodeError) as exc_info:
            db.update_subject_relative_weight(
                node_id=gi.id,
                relative_weight=30
            )
        
        assert "locked" in str(exc_info.value).lower()
    
    def test_invalid_relative_weight_rejected(self, user_db_with_subjects):
        """Test that invalid relative weights are rejected."""
        db = user_db_with_subjects
        
        gi = next(s for s in db.get_subject_hierarchy("USMLE Step 1") if s.name == "Gastrointestinal System")
        esophagus = next(c for c in gi.children if c.name == "Esophagus")
        
        # Test negative weight
        with pytest.raises(WeightValidationError):
            db.update_subject_relative_weight(esophagus.id, -5)
        
        # Test weight > 100
        with pytest.raises(WeightValidationError):
            db.update_subject_relative_weight(esophagus.id, 150)


# ==============================================================================
# TESTS: EFFECTIVE WEIGHT CALCULATION
# ==============================================================================

class TestEffectiveWeightCalculation:
    """Tests for effective weight calculation."""
    
    def test_effective_weight_top_level(self, user_db_with_subjects):
        """Test effective weight for top-level subjects with absolute weights."""
        db = user_db_with_subjects
        
        exam_config = db.get_exam_context_by_name("USMLE Step 1")
        subjects = db.get_subjects_with_effective_weights(exam_config.id)
        
        # Find GI system
        gi = next(s for s in subjects if s['name'] == "Gastrointestinal System")
        
        # Effective weight should be midpoint of range
        assert gi['weight']['absolute_low'] == 20
        assert gi['weight']['absolute_high'] == 25
        assert gi['weight']['effective'] == 22.5  # (20 + 25) / 2
        assert gi['weight']['confidence'] == 'high'  # Official source
    
    def test_effective_weight_children(self, user_db_with_subjects):
        """Test effective weight for children with relative weights."""
        db = user_db_with_subjects
        
        exam_config = db.get_exam_context_by_name("USMLE Step 1")
        subjects = db.get_subjects_with_effective_weights(exam_config.id)
        
        # Find GI system and its children
        gi = next(s for s in subjects if s['name'] == "Gastrointestinal System")
        esophagus = next(c for c in gi['children'] if c['name'] == "Esophagus")
        
        # Esophagus has relative_weight=15, parent midpoint=22.5
        # Effective = 22.5 * 0.15 = 3.375
        assert esophagus['weight']['relative'] == 15
        assert abs(esophagus['weight']['effective'] - 3.375) < 0.01
        
        # Effective range should be calculated from parent range
        # effective_low = 20 * 0.15 = 3
        # effective_high = 25 * 0.15 = 3.75
        assert abs(esophagus['weight']['effective_low'] - 3.0) < 0.01
        assert abs(esophagus['weight']['effective_high'] - 3.75) < 0.01
    
    def test_confidence_levels(self, user_db_with_subjects):
        """Test confidence levels based on weight source."""
        db = user_db_with_subjects
        
        exam_config = db.get_exam_context_by_name("USMLE Step 1")
        subjects = db.get_subjects_with_effective_weights(exam_config.id)
        
        # Official weights should have high confidence
        gi = next(s for s in subjects if s['name'] == "Gastrointestinal System")
        assert gi['weight']['confidence'] == 'high'
        assert gi['weight']['locked'] == True
        
        # User estimate weights should have low confidence
        esophagus = next(c for c in gi['children'] if c['name'] == "Esophagus")
        assert esophagus['weight']['confidence'] == 'low'
        assert esophagus['weight']['locked'] == False


# ==============================================================================
# TESTS: WEIGHT CONFIGURATION
# ==============================================================================

class TestWeightConfiguration:
    """Tests for weight configuration retrieval."""
    
    def test_get_weight_config_official(self, user_db_with_subjects):
        """Test weight config with official weights."""
        db = user_db_with_subjects
        
        exam_config = db.get_exam_context_by_name("USMLE Step 1")
        config = db.get_weight_config_for_exam(exam_config.id)
        
        assert config['weight_mode'] == 'official_ranges'
        assert config['has_official_weights'] == True
        assert config['official_weight_count'] >= 2
        assert config['source_name'] == "NBME Content Outline 2024"
    
    def test_get_weight_config_user_defined(self, user_db):
        """Test weight config with only user-defined weights."""
        exam_config = user_db.get_exam_context_by_name("USMLE Step 1")
        
        # Create user-defined weight (not official)
        user_db.create_subject_node_with_weight(
            exam_context="USMLE Step 1",
            name="Custom Topic",
            level_type="System",
            exam_weight_low=30,
            exam_weight_high=30,
            weight_source='user_defined'
        )
        
        config = user_db.get_weight_config_for_exam(exam_config.id)
        
        assert config['weight_mode'] == 'user_defined'
        assert config['has_official_weights'] == False


# ==============================================================================
# TESTS: CREATE SUBJECT WITH WEIGHT
# ==============================================================================

class TestCreateSubjectWithWeight:
    """Tests for creating subjects with full weight configuration."""
    
    def test_create_with_absolute_weight(self, user_db):
        """Test creating subject with absolute weight range."""
        subject = user_db.create_subject_node_with_weight(
            exam_context="USMLE Step 1",
            name="Test System",
            level_type="System",
            exam_weight_low=15,
            exam_weight_high=20,
            weight_source='official',
            weight_locked=True
        )
        
        assert subject.exam_weight_low == 15
        assert subject.exam_weight_high == 20
        assert subject.weight_source == 'official'
        assert subject.weight_locked == True
    
    def test_create_with_relative_weight(self, user_db_with_subjects):
        """Test creating subject with relative weight."""
        db = user_db_with_subjects
        
        gi = next(s for s in db.get_subject_hierarchy("USMLE Step 1") if s.name == "Gastrointestinal System")
        
        subject = db.create_subject_node_with_weight(
            exam_context="USMLE Step 1",
            name="New Topic",
            level_type="Topic",
            parent_id=gi.id,
            relative_weight=10,
            weight_source='user_estimate'
        )
        
        assert subject.relative_weight == 10
        assert subject.weight_source == 'user_estimate'
    
    def test_create_with_invalid_weight_source(self, user_db):
        """Test that invalid weight source is rejected."""
        with pytest.raises(WeightValidationError):
            user_db.create_subject_node_with_weight(
                exam_context="USMLE Step 1",
                name="Test",
                level_type="System",
                weight_source='invalid_source'
            )
    
    def test_create_with_negative_weight(self, user_db):
        """Test that negative weights are rejected."""
        with pytest.raises(WeightValidationError):
            user_db.create_subject_node_with_weight(
                exam_context="USMLE Step 1",
                name="Test",
                level_type="System",
                exam_weight_low=-5
            )


# ==============================================================================
# TESTS: MIGRATION SUPPORT
# ==============================================================================

class TestMigrationSupport:
    """Tests for database migration support."""
    
    def test_ensure_hybrid_weight_columns(self, user_db):
        """Test that migration adds missing columns."""
        # The columns should already exist from schema creation
        # This tests the idempotent nature of ensure_hybrid_weight_columns
        
        added = user_db.ensure_hybrid_weight_columns()
        
        # Should return False since columns already exist
        assert added == False
        
        # Verify columns exist
        columns = user_db.fetchall("PRAGMA table_info(subject_nodes)")
        column_names = {col['name'] for col in columns}
        
        assert 'relative_weight' in column_names
        assert 'weight_source' in column_names
        assert 'weight_locked' in column_names


