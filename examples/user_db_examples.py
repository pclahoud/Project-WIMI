"""
UserDatabase Usage Examples - Phase 1
Demonstrates how to use the UserDatabase class for question analysis
"""
from pathlib import Path
from datetime import date
from src.database import MasterDatabase, UserDatabase
from src.app_logging import ErrorLogger

# Example 1: Initialize and Setup
def example_setup():
    """Complete setup for a user with question analysis database"""
    # Initialize error logger
    error_logger = ErrorLogger(app_name="WIMIApp", mode='development')
    
    # Initialize master database
    master_db = MasterDatabase(error_logger=error_logger)
    
    # Create a user
    user = master_db.create_user(
        username="student1",
        display_name="Test Student",
        email="student@example.com",
        user_types=["student"]
    )
    
    # Ensure user database exists
    user_db_path = master_db.ensure_user_database(user.id)
    
    # Open user database
    user_db = UserDatabase(
        db_path=user_db_path,
        user_id=user.id,
        username=user.username,
        error_logger=error_logger
    )
    
    print(f"User database created for: {user.username}")
    print(f"Database path: {user_db_path}")
    
    return master_db, user_db, user


# Example 2: User Preferences
def example_preferences(user_db: UserDatabase):
    """Managing user preferences"""
    print("\n=== User Preferences ===")
    
    # Get default preferences (created automatically)
    prefs = user_db.get_preferences()
    print(f"Default theme: {prefs.theme_name}")
    print(f"Default session duration: {prefs.default_session_duration_minutes} minutes")
    
    # Update preferences
    updated_prefs = user_db.update_preferences(
        theme_name='dark',
        font_size_scale=1.2,
        default_session_duration_minutes=45,
        show_animations=False,
        entry_review_items_per_page=50
    )
    
    print(f"\nUpdated theme: {updated_prefs.theme_name}")
    print(f"Updated font scale: {updated_prefs.font_size_scale}")
    print(f"Updated session duration: {updated_prefs.default_session_duration_minutes} minutes")
    
    return updated_prefs


# Example 3: Subject Hierarchy
def example_subject_hierarchy(user_db: UserDatabase):
    """Creating a subject hierarchy for SAT Math"""
    print("\n=== Subject Hierarchy ===")
    
    # Create root level subjects for SAT
    algebra = user_db.create_subject_node(
        exam_context='SAT',
        name='Heart of Algebra',
        level_type='Domain',
        exam_weight_low=33,
        exam_weight_high=33,
        exam_source='College Board SAT Blueprint 2024',
        sort_order=1
    )
    print(f"Created domain: {algebra.name} (Weight: {algebra.exam_weight_low}%)")
    
    problem_solving = user_db.create_subject_node(
        exam_context='SAT',
        name='Problem Solving and Data Analysis',
        level_type='Domain',
        exam_weight_low=29,
        exam_weight_high=29,
        exam_source='College Board SAT Blueprint 2024',
        sort_order=2
    )
    print(f"Created domain: {problem_solving.name} (Weight: {problem_solving.exam_weight_low}%)")
    
    # Create child topics under algebra
    linear_eq = user_db.create_subject_node(
        exam_context='SAT',
        name='Linear Equations',
        level_type='Topic',
        parent_id=algebra.id,
        exam_weight_low=8,
        exam_weight_high=10,
        sort_order=1
    )
    print(f"  Created topic: {linear_eq.name}")
    
    systems = user_db.create_subject_node(
        exam_context='SAT',
        name='Systems of Equations',
        level_type='Topic',
        parent_id=algebra.id,
        exam_weight_low=7,
        exam_weight_high=9,
        sort_order=2
    )
    print(f"  Created topic: {systems.name}")
    
    # Get full hierarchy
    print("\nFull SAT hierarchy:")
    hierarchy = user_db.get_subject_hierarchy('SAT')
    for domain in hierarchy:
        print(f"- {domain.name} ({domain.exam_weight_low}%-{domain.exam_weight_high}%)")
        for topic in domain.children:
            print(f"  - {topic.name} ({topic.exam_weight_low}%-{topic.exam_weight_high}%)")
    
    return algebra, linear_eq


# Example 4: Question Analysis
def example_question_analysis(user_db: UserDatabase, subject_node_id: int):
    """Creating question analysis entries"""
    print("\n=== Question Analysis ===")
    
    # Create a question analysis
    question = user_db.create_question_analysis(
        exam_context='SAT',
        question_source='Official SAT Practice Test 1',
        question_source_id='Section3_Q15',
        answered_incorrectly_date=date(2024, 12, 1),
        user_selected_answer='B',
        correct_answer='C',
        perceived_difficulty=4,
        metacognitive_reflection="I misread the equation and didn't notice the negative sign. I need to slow down and read more carefully.",
        mistake_category='misread_question',
        confidence_before_answer=4,
        time_spent_on_question=120,
        question_explanation="The key is recognizing that -2x means multiply by -2, not subtract 2.",
        user_notes="Watch for negative signs in front of variables!"
    )
    
    print(f"Created question analysis: {question.question_source_id}")
    print(f"  Mistake category: {question.mistake_category}")
    print(f"  Perceived difficulty: {question.perceived_difficulty}/5")
    print(f"  Confidence before: {question.confidence_before_answer}/5")
    
    # Assign to topic
    user_db.assign_question_to_topics(
        question_id=question.id,
        subject_node_ids=[subject_node_id],
        assignment_type='primary'
    )
    print(f"  Assigned to subject node ID: {subject_node_id}")
    
    # Create another question
    question2 = user_db.create_question_analysis(
        exam_context='SAT',
        question_source='Khan Academy Practice',
        question_source_id='Linear_Systems_Q3',
        answered_incorrectly_date=date(2024, 12, 2),
        user_selected_answer='A',
        correct_answer='D',
        perceived_difficulty=3,
        metacognitive_reflection="I solved for x correctly but made an arithmetic error when substituting back.",
        mistake_category='calculation_error',
        confidence_before_answer=5,
        time_spent_on_question=180
    )
    
    user_db.assign_question_to_topics(
        question_id=question2.id,
        subject_node_ids=[subject_node_id]
    )
    
    return question, question2


# Example 5: Tagging System
def example_tags(user_db: UserDatabase, question_ids: list):
    """Using the tagging system"""
    print("\n=== Tagging System ===")
    
    # Create tags
    tag1 = user_db.create_tag(
        exam_context='SAT',
        tag_name='Needs More Practice',
        tag_category='study_method',
        color_hex='#FF5722',
        description='Questions that require additional practice'
    )
    print(f"Created tag: {tag1.tag_name} ({tag1.color_hex})")
    
    tag2 = user_db.create_tag(
        exam_context='SAT',
        tag_name='Arithmetic Errors',
        tag_category='mistake_type',
        color_hex='#FFC107',
        description='Simple calculation mistakes'
    )
    print(f"Created tag: {tag2.tag_name} ({tag2.color_hex})")
    
    tag3 = user_db.create_tag(
        exam_context='SAT',
        tag_name='Time Pressure',
        tag_category='difficulty',
        color_hex='#9C27B0',
        description='Questions affected by time constraints'
    )
    print(f"Created tag: {tag3.tag_name} ({tag3.color_hex})")
    
    # Tag questions
    user_db.tag_question(
        question_id=question_ids[0],
        tag_ids=[tag1.id, tag3.id]
    )
    print(f"\nTagged question {question_ids[0]} with: {tag1.tag_name}, {tag3.tag_name}")
    
    user_db.tag_question(
        question_id=question_ids[1],
        tag_ids=[tag1.id, tag2.id]
    )
    print(f"Tagged question {question_ids[1]} with: {tag1.tag_name}, {tag2.tag_name}")
    
    # Get all tags
    all_tags = user_db.get_tags_by_exam('SAT')
    print(f"\nAll SAT tags ({len(all_tags)}):")
    for tag in all_tags:
        print(f"  - {tag.tag_name} ({tag.tag_category}): used {tag.usage_count} times")
    
    return tag1, tag2, tag3


# Example 6: Analytics and Search
def example_analytics(user_db: UserDatabase):
    """Analytics and search capabilities"""
    print("\n=== Analytics & Search ===")
    
    # Get recent questions
    recent = user_db.get_recent_questions(exam_context='SAT', days_back=30)
    print(f"Recent questions (last 30 days): {len(recent)}")
    for q in recent:
        print(f"  - {q.question_source_id} ({q.answered_incorrectly_date})")
    
    # Get mistake statistics
    stats = user_db.get_mistake_statistics(exam_context='SAT')
    print(f"\nMistake category statistics:")
    for category, count in stats.items():
        print(f"  - {category}: {count} questions")
    
    # Search questions
    results = user_db.search_questions(
        search_term='negative',
        exam_context='SAT'
    )
    print(f"\nSearch results for 'negative': {len(results)} questions")
    for q in results:
        print(f"  - {q.question_source_id}")
    
    # Get questions by mistake category
    calc_errors = user_db.get_questions_by_mistake_category(
        mistake_category='calculation_error',
        exam_context='SAT'
    )
    print(f"\nQuestions with calculation errors: {len(calc_errors)}")


# Example 7: Complete Workflow
def example_complete_workflow():
    """Complete workflow demonstrating Phase 1 features"""
    print("=" * 60)
    print("Complete UserDatabase Phase 1 Workflow")
    print("=" * 60)
    
    # 1. Setup
    master_db, user_db, user = example_setup()
    
    # 2. Configure preferences
    prefs = example_preferences(user_db)
    
    # 3. Create subject hierarchy
    algebra, linear_eq = example_subject_hierarchy(user_db)
    
    # 4. Add question analyses
    q1, q2 = example_question_analysis(user_db, linear_eq.id)
    
    # 5. Apply tags
    tag1, tag2, tag3 = example_tags(user_db, [q1.id, q2.id])
    
    # 6. Run analytics
    example_analytics(user_db)
    
    # 7. Get questions by topic
    print("\n=== Questions by Topic ===")
    topic_questions = user_db.get_questions_by_topic(
        subject_node_id=linear_eq.id,
        include_children=False
    )
    print(f"Questions in '{linear_eq.name}': {len(topic_questions)}")
    for q in topic_questions:
        print(f"  - {q.question_source_id}: {q.mistake_category}")
    
    # 8. Get questions by tag
    print("\n=== Questions by Tag ===")
    tagged_questions = user_db.get_questions_by_tag(tag1.id)
    print(f"Questions with tag '{tag1.tag_name}': {len(tagged_questions)}")
    for q in tagged_questions:
        print(f"  - {q.question_source_id}")
    
    print("\n" + "=" * 60)
    print("Phase 1 Workflow Complete!")
    print("=" * 60)
    
    return user_db


# Example 8: Bulk Import Questions
def example_bulk_import(user_db: UserDatabase):
    """Example of importing multiple questions"""
    print("\n=== Bulk Import Example ===")
    
    questions_data = [
        {
            'source': 'Official SAT Practice Test 2',
            'source_id': 'Section3_Q1',
            'date': date(2024, 11, 15),
            'selected': 'A',
            'correct': 'B',
            'category': 'knowledge_gap',
            'reflection': 'Did not remember the quadratic formula'
        },
        {
            'source': 'Official SAT Practice Test 2',
            'source_id': 'Section3_Q5',
            'date': date(2024, 11, 15),
            'selected': 'C',
            'correct': 'D',
            'category': 'silly_mistake',
            'reflection': 'Forgot to distribute the negative sign'
        },
        {
            'source': 'Official SAT Practice Test 2',
            'source_id': 'Section3_Q12',
            'date': date(2024, 11, 16),
            'selected': 'B',
            'correct': 'A',
            'category': 'time_pressure',
            'reflection': 'Rushed through without checking work'
        }
    ]
    
    created_questions = []
    for data in questions_data:
        q = user_db.create_question_analysis(
            exam_context='SAT',
            question_source=data['source'],
            question_source_id=data['source_id'],
            answered_incorrectly_date=data['date'],
            user_selected_answer=data['selected'],
            correct_answer=data['correct'],
            mistake_category=data['category'],
            metacognitive_reflection=data['reflection']
        )
        created_questions.append(q)
        print(f"Imported: {q.question_source_id}")
    
    print(f"\nTotal imported: {len(created_questions)} questions")
    return created_questions


if __name__ == "__main__":
    # Run the complete workflow
    user_db = example_complete_workflow()
    
    # Additional examples
    example_bulk_import(user_db)
