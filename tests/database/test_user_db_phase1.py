"""
Test UserDatabase Phase 1 Implementation
"""
import pytest
import tempfile
from pathlib import Path
from datetime import date
from database import MasterDatabase, UserDatabase
from database.exceptions import (
    ValidationError, SubjectNodeError, QuestionAnalysisError, TagError
)


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
    # Ensure database connection is properly closed
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
    # Ensure database connection is properly closed
    db.close()


class TestUserPreferences:
    """Test user preferences functionality"""
    
    def test_default_preferences_created(self, user_db):
        """Test that default preferences are created automatically"""
        prefs = user_db.get_preferences()
        assert prefs is not None
        assert prefs.user_id == user_db.user_id
        assert prefs.theme_name == 'default'
        assert prefs.default_session_duration_minutes == 60
    
    def test_update_preferences(self, user_db):
        """Test updating preferences"""
        updated = user_db.update_preferences(
            theme_name='dark',
            font_size_scale=1.5,
            default_session_duration_minutes=45
        )
        
        assert updated.theme_name == 'dark'
        assert updated.font_size_scale == 1.5
        assert updated.default_session_duration_minutes == 45
    
    def test_preference_validation(self, user_db):
        """Test preference validation"""
        with pytest.raises(ValidationError):
            # Font size scale out of range
            user_db.update_preferences(font_size_scale=5.0)
        
        with pytest.raises(ValidationError):
            # Session duration too short
            user_db.update_preferences(default_session_duration_minutes=10)
        
        with pytest.raises(ValidationError):
            # Invalid calendar time slot
            user_db.update_preferences(calendar_time_slot_minutes=45)


class TestSubjectHierarchy:
    """Test subject hierarchy functionality"""
    
    def test_create_subject_node(self, user_db):
        """Test creating subject nodes"""
        node = user_db.create_subject_node(
            exam_context='SAT',
            name='Mathematics',
            level_type='Domain',
            exam_weight_low=50,
            exam_weight_high=60
        )
        
        assert node.id is not None
        assert node.name == 'Mathematics'
        assert node.exam_weight_low == 50
        assert node.exam_weight_high == 60
    
    def test_create_hierarchy(self, user_db):
        """Test creating hierarchical structure"""
        # Create parent
        parent = user_db.create_subject_node(
            exam_context='SAT',
            name='Algebra',
            level_type='Domain'
        )
        
        # Create children
        child1 = user_db.create_subject_node(
            exam_context='SAT',
            name='Linear Equations',
            level_type='Topic',
            parent_id=parent.id
        )
        
        child2 = user_db.create_subject_node(
            exam_context='SAT',
            name='Quadratic Equations',
            level_type='Topic',
            parent_id=parent.id
        )
        
        # Get hierarchy
        hierarchy = user_db.get_subject_hierarchy('SAT')
        assert len(hierarchy) == 1
        assert hierarchy[0].name == 'Algebra'
        assert len(hierarchy[0].children) == 2
        assert hierarchy[0].children[0].name == 'Linear Equations'
    
    def test_duplicate_node_error(self, user_db):
        """Test that duplicate nodes raise error"""
        user_db.create_subject_node(
            exam_context='SAT',
            name='TestNode',
            level_type='Domain'
        )
        
        with pytest.raises(SubjectNodeError):
            user_db.create_subject_node(
                exam_context='SAT',
                name='TestNode',
                level_type='Domain'
            )
    
    def test_update_weights(self, user_db):
        """Test updating subject weights"""
        node = user_db.create_subject_node(
            exam_context='SAT',
            name='Geometry',
            level_type='Domain',
            exam_weight_low=10,
            exam_weight_high=15
        )
        
        updated = user_db.update_subject_weights(
            node_id=node.id,
            exam_weight_low=12,
            exam_weight_high=18,
            exam_source='Updated Blueprint 2024'
        )
        
        assert updated.exam_weight_low == 12
        assert updated.exam_weight_high == 18
        assert updated.exam_source == 'Updated Blueprint 2024'


class TestQuestionAnalysis:
    """Test question analysis functionality"""
    
    def test_create_question_analysis(self, user_db):
        """Test creating question analysis"""
        question = user_db.create_question_analysis(
            exam_context='SAT',
            question_source='Practice Test 1',
            question_source_id='Q1',
            answered_incorrectly_date=date(2024, 12, 1),
            user_selected_answer='A',
            correct_answer='B',
            perceived_difficulty=3,
            mistake_category='knowledge_gap'
        )
        
        assert question.id is not None
        assert question.question_source_id == 'Q1'
        assert question.mistake_category == 'knowledge_gap'
        assert question.review_status == 'pending_review'
    
    def test_metacognitive_reflection(self, user_db):
        """Test metacognitive reflection storage"""
        reflection = "I confused the order of operations and multiplied before adding"
        
        question = user_db.create_question_analysis(
            exam_context='SAT',
            question_source='Test',
            question_source_id='Q2',
            answered_incorrectly_date=date.today(),
            metacognitive_reflection=reflection,
            mistake_category='misunderstanding'
        )
        
        assert question.metacognitive_reflection == reflection
    
    def test_invalid_mistake_category(self, user_db):
        """Test that invalid mistake categories are rejected"""
        with pytest.raises(ValidationError):
            user_db.create_question_analysis(
                exam_context='SAT',
                question_source='Test',
                question_source_id='Q3',
                answered_incorrectly_date=date.today(),
                mistake_category='invalid_category'
            )
    
    def test_assign_to_topics(self, user_db):
        """Test assigning questions to topics"""
        # Create topic
        topic = user_db.create_subject_node(
            exam_context='SAT',
            name='Algebra',
            level_type='Domain'
        )
        
        # Create question
        question = user_db.create_question_analysis(
            exam_context='SAT',
            question_source='Test',
            question_source_id='Q4',
            answered_incorrectly_date=date.today()
        )
        
        # Assign to topic
        user_db.assign_question_to_topics(
            question_id=question.id,
            subject_node_ids=[topic.id]
        )
        
        # Get questions by topic
        questions = user_db.get_questions_by_topic(topic.id)
        assert len(questions) == 1
        assert questions[0].id == question.id


class TestTagging:
    """Test tagging system"""
    
    def test_create_tag(self, user_db):
        """Test creating tags"""
        tag = user_db.create_tag(
            exam_context='SAT',
            tag_name='Review Later',
            tag_category='study_method',
            color_hex='#FF5722',
            description='Questions to review in next session'
        )
        
        assert tag.id is not None
        assert tag.tag_name == 'Review Later'
        assert tag.color_hex == '#FF5722'
        assert tag.is_active is True
    
    def test_invalid_tag_category(self, user_db):
        """Test invalid tag category"""
        with pytest.raises(ValidationError):
            user_db.create_tag(
                exam_context='SAT',
                tag_name='Test',
                tag_category='invalid'
            )
    
    def test_invalid_color_hex(self, user_db):
        """Test invalid hex color"""
        with pytest.raises(ValidationError):
            user_db.create_tag(
                exam_context='SAT',
                tag_name='Test',
                color_hex='not-a-color'
            )
    
    def test_tag_question(self, user_db):
        """Test tagging questions"""
        # Create tag
        tag = user_db.create_tag(
            exam_context='SAT',
            tag_name='Difficult',
            tag_category='difficulty'
        )
        
        # Create question
        question = user_db.create_question_analysis(
            exam_context='SAT',
            question_source='Test',
            question_source_id='Q5',
            answered_incorrectly_date=date.today()
        )
        
        # Apply tag
        user_db.tag_question(
            question_id=question.id,
            tag_ids=[tag.id]
        )
        
        # Verify usage count increased
        updated_tag = user_db.get_tag(tag.id)
        assert updated_tag.usage_count == 1
        
        # Get questions by tag
        questions = user_db.get_questions_by_tag(tag.id)
        assert len(questions) == 1
        assert questions[0].id == question.id


class TestAnalytics:
    """Test analytics and search functionality"""
    
    def test_get_recent_questions(self, user_db):
        """Test getting recent questions"""
        # Create questions
        for i in range(3):
            user_db.create_question_analysis(
                exam_context='SAT',
                question_source='Test',
                question_source_id=f'Q{i}',
                answered_incorrectly_date=date.today()
            )
        
        recent = user_db.get_recent_questions(exam_context='SAT', days_back=7)
        assert len(recent) == 3
    
    def test_mistake_statistics(self, user_db):
        """Test mistake category statistics"""
        # Create questions with different mistakes
        categories = ['knowledge_gap', 'knowledge_gap', 'calculation_error']
        for i, category in enumerate(categories):
            user_db.create_question_analysis(
                exam_context='SAT',
                question_source='Test',
                question_source_id=f'Q{i}',
                answered_incorrectly_date=date.today(),
                mistake_category=category
            )
        
        stats = user_db.get_mistake_statistics(exam_context='SAT')
        assert stats['knowledge_gap'] == 2
        assert stats['calculation_error'] == 1
    
    def test_search_questions(self, user_db):
        """Test searching questions"""
        # Create questions with searchable content
        user_db.create_question_analysis(
            exam_context='SAT',
            question_source='Test',
            question_source_id='Q1',
            answered_incorrectly_date=date.today(),
            user_notes='Remember to check negative values'
        )
        
        user_db.create_question_analysis(
            exam_context='SAT',
            question_source='Test',
            question_source_id='Q2',
            answered_incorrectly_date=date.today(),
            metacognitive_reflection='I forgot about negative numbers'
        )
        
        results = user_db.search_questions('negative', exam_context='SAT')
        assert len(results) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
