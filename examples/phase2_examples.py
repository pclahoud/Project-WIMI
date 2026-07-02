"""
Phase 2 Examples: Exam Context & Weight Management
Demonstrates the new Phase 2 functionality for Project WIMI
"""
import tempfile
from pathlib import Path
from datetime import date

from src.database import (
    UserDatabase,
    ExamContextConfig,
    HierarchyLevelDefinition,
    SubjectNodeWeight,
    WeightUpdateResult
)


def demonstrate_exam_context_creation():
    """Example: Creating and configuring exam contexts"""
    print("\n" + "="*60)
    print("Example 1: Creating Exam Contexts")
    print("="*60)
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)
    
    try:
        # Initialize user database
        db = UserDatabase(db_path, user_id=1, username="student1")
        
        # Create exam context with defaults
        exam = db.create_exam_context(
            exam_name="USMLE Step 1",
            exam_description="United States Medical Licensing Examination - Step 1",
            exam_date=date(2026, 6, 15)
        )
        
        print(f"\n✅ Created exam context:")
        print(f"   Name: {exam.exam_name}")
        print(f"   Description: {exam.exam_description}")
        print(f"   Exam Date: {exam.exam_date}")
        print(f"   Active: {exam.is_active}")
        print(f"   Hierarchy Levels: {exam.default_hierarchy_levels}")
        
        # Show weight validation rules
        print(f"\n   Weight Rules:")
        for key, value in exam.weight_validation_rules.items():
            print(f"     - {key}: {value}")
        
        # Create another exam with custom settings
        custom_rules = {
            "autonomous_weight_balancing": False,
            "allow_absolute_weight_editing": True,
            "precision_decimal_places": 2,
            "require_exact_100": True,
            "balancing_algorithm": "even"
        }
        
        exam2 = db.create_exam_context(
            exam_name="SAT",
            exam_description="College admission test",
            weight_validation_rules=custom_rules,
            hierarchy_levels=["Section", "Topic", "Subtopic"]
        )
        
        print(f"\n✅ Created custom exam context:")
        print(f"   Name: {exam2.exam_name}")
        print(f"   Custom Levels: {exam2.default_hierarchy_levels}")
        print(f"   Balancing Algorithm: {exam2.balancing_algorithm}")
        
        # List all exams
        all_exams = db.get_all_exam_contexts()
        print(f"\n📋 Total exam contexts: {len(all_exams)}")
        
        db.close()
        
    finally:
        db_path.unlink(missing_ok=True)


def demonstrate_hierarchy_levels():
    """Example: Working with hierarchy levels"""
    print("\n" + "="*60)
    print("Example 2: Hierarchy Level Management")
    print("="*60)
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)
    
    try:
        db = UserDatabase(db_path, user_id=1, username="student1")
        
        # Create exam
        exam = db.create_exam_context(exam_name="MCAT")
        
        # Get hierarchy levels
        levels = db.get_hierarchy_levels(exam.id)
        
        print(f"\n📊 Default Hierarchy Levels for {exam.exam_name}:")
        for level in levels:
            required = "✓ Required" if level.is_required else "○ Optional"
            custom = " (Custom)" if level.is_custom_level else ""
            print(f"   Level {level.level_order}: {level.level_name} [{required}]{custom}")
        
        # Add custom levels
        level6 = db.add_custom_hierarchy_level(
            exam_context_id=exam.id,
            level_name="Sub-Child",
            display_name_template="Sub-topic of {parent_name}"
        )
        
        level7 = db.add_custom_hierarchy_level(
            exam_context_id=exam.id,
            level_name="Detail"
        )
        
        print(f"\n✅ Added custom levels:")
        print(f"   Level {level6.level_order}: {level6.level_name}")
        print(f"     Display template: {level6.display_name_template}")
        print(f"     Example: {level6.get_display_name('Cardiology')}")
        print(f"   Level {level7.level_order}: {level7.level_name}")
        
        # Get updated levels
        all_levels = db.get_hierarchy_levels(exam.id)
        print(f"\n📊 Total hierarchy levels: {len(all_levels)}")
        
        db.close()
        
    finally:
        db_path.unlink(missing_ok=True)


def demonstrate_weight_balancing():
    """Example: Weight management with auto-balancing"""
    print("\n" + "="*60)
    print("Example 3: Weight Balancing")
    print("="*60)
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)
    
    try:
        db = UserDatabase(db_path, user_id=1, username="student1")
        
        # Create exam with proportional balancing
        exam = db.create_exam_context(exam_name="USMLE Step 1")
        
        # Create subject hierarchy
        root = db.create_subject_node(
            exam_context="USMLE Step 1",
            name="All Systems",
            level_type="Root",
            exam_weight_low=100.0,
            exam_weight_high=100.0
        )
        
        cardio = db.create_subject_node(
            exam_context="USMLE Step 1",
            name="Cardiovascular",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=33.3,
            exam_weight_high=33.3
        )
        
        resp = db.create_subject_node(
            exam_context="USMLE Step 1",
            name="Respiratory",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=33.3,
            exam_weight_high=33.3
        )
        
        neuro = db.create_subject_node(
            exam_context="USMLE Step 1",
            name="Neurology",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=33.4,
            exam_weight_high=33.4
        )
        
        print(f"\n📊 Initial Subject Hierarchy:")
        print(f"   {root.name} (100%)")
        children = db.get_subject_hierarchy("USMLE Step 1")[0].children
        for child in children:
            print(f"   ├── {child.name}: {child.exam_weight_low}%")
        
        # Update Cardiovascular weight - triggers auto-balancing
        print(f"\n🔄 Updating Cardiovascular from 33.3% to 50%...")
        
        result = db.update_subject_node_weight(
            node_id=cardio.id,
            new_weight=50.0,
            reason="High-yield topic for exam",
            user_notes="Based on practice exam analysis"
        )
        
        print(f"\n✅ Weight Update Result:")
        print(f"   Updated node: {result.updated_node.name} → {result.updated_node.exam_weight_low}%")
        print(f"   Total nodes affected: {result.total_updates}")
        print(f"   Siblings adjusted:")
        for sibling in result.affected_siblings:
            print(f"     - {sibling.name}: {sibling.exam_weight_low}%")
        
        # Show updated hierarchy
        print(f"\n📊 Updated Subject Hierarchy:")
        children = db.get_subject_hierarchy("USMLE Step 1")[0].children
        total = sum(c.exam_weight_low for c in children)
        for child in children:
            print(f"   ├── {child.name}: {child.exam_weight_low}%")
        print(f"   Total: {total}%")
        
        db.close()
        
    finally:
        db_path.unlink(missing_ok=True)


def demonstrate_weight_history():
    """Example: Weight change history and analytics"""
    print("\n" + "="*60)
    print("Example 4: Weight History & Analytics")
    print("="*60)
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)
    
    try:
        db = UserDatabase(db_path, user_id=1, username="student1")
        
        # Create exam and hierarchy
        db.create_exam_context(exam_name="Test Exam")
        
        root = db.create_subject_node(
            exam_context="Test Exam",
            name="Root",
            level_type="Root",
            exam_weight_low=100.0,
            exam_weight_high=100.0
        )
        
        child1 = db.create_subject_node(
            exam_context="Test Exam",
            name="Topic A",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=50.0,
            exam_weight_high=50.0
        )
        
        child2 = db.create_subject_node(
            exam_context="Test Exam",
            name="Topic B",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=50.0,
            exam_weight_high=50.0
        )
        
        # Make multiple weight changes
        db.update_subject_node_weight(child1.id, 60.0, reason="First adjustment")
        db.update_subject_node_weight(child1.id, 55.0, reason="Fine tuning")
        db.update_subject_node_weight(child1.id, 70.0, reason="Final weight")
        
        # Get weight history
        history = db.get_weight_history(child1.id)
        
        print(f"\n📜 Weight History for Topic A:")
        print(f"   Total changes: {len(history)}")
        print()
        for entry in history[:5]:  # Show last 5
            delta = entry.weight_delta
            delta_str = f"({'+' if delta > 0 else ''}{delta:.1f}%)" if delta else ""
            print(f"   {entry.edited_date}: {entry.previous_weight}% → {entry.weight_value}% {delta_str}")
            print(f"      Type: {entry.change_type}")
            print(f"      By: {entry.edited_by}")
            if entry.edited_reason:
                print(f"      Reason: {entry.edited_reason}")
            print()
        
        # Get statistics
        stats = db.get_weight_statistics("Test Exam")
        
        print(f"\n📊 Weight Change Statistics:")
        print(f"   Total changes: {stats['total_changes']}")
        print(f"   Manual edits: {stats['manual_edits']}")
        print(f"   Auto adjustments: {stats['auto_adjustments']}")
        print(f"   Nodes changed: {stats['nodes_changed']}")
        
        db.close()
        
    finally:
        db_path.unlink(missing_ok=True)


def demonstrate_even_vs_proportional():
    """Example: Comparing even vs proportional balancing"""
    print("\n" + "="*60)
    print("Example 5: Even vs Proportional Balancing")
    print("="*60)
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)
    
    try:
        db = UserDatabase(db_path, user_id=1, username="student1")
        
        # Create exam with PROPORTIONAL balancing
        db.create_exam_context(
            exam_name="Proportional Test",
            weight_validation_rules={
                "autonomous_weight_balancing": True,
                "precision_decimal_places": 1,
                "require_exact_100": True,
                "balancing_algorithm": "proportional"
            }
        )
        
        root = db.create_subject_node(
            exam_context="Proportional Test",
            name="Root",
            level_type="Root",
            exam_weight_low=100.0,
            exam_weight_high=100.0
        )
        
        # Create children with UNEQUAL initial weights
        a = db.create_subject_node(
            exam_context="Proportional Test",
            name="A",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=20.0,  # Small
            exam_weight_high=20.0
        )
        
        b = db.create_subject_node(
            exam_context="Proportional Test",
            name="B",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=30.0,  # Medium
            exam_weight_high=30.0
        )
        
        c = db.create_subject_node(
            exam_context="Proportional Test",
            name="C",
            parent_id=root.id,
            level_type="System",
            exam_weight_low=50.0,  # Large
            exam_weight_high=50.0
        )
        
        print(f"\n📊 Initial Weights (Unequal):")
        print(f"   A: 20%, B: 30%, C: 50%")
        print(f"   Total: 100%")
        
        # Update A to 40% - B and C will absorb change proportionally
        result = db.update_subject_node_weight(a.id, 40.0)
        
        print(f"\n🔄 PROPORTIONAL Balancing (A increased by 20%):")
        children = db.get_subject_hierarchy("Proportional Test")[0].children
        for child in children:
            print(f"   {child.name}: {child.exam_weight_low}%")
        
        print(f"\n   Note: B (30%) lost more than C (50%) proportionally")
        print(f"   B had 30/80 = 37.5% of remaining weight")
        print(f"   C had 50/80 = 62.5% of remaining weight")
        
        db.close()
        
        # Now demonstrate EVEN balancing
        db = UserDatabase(db_path, user_id=2, username="student2")
        
        db.create_exam_context(
            exam_name="Even Test",
            weight_validation_rules={
                "autonomous_weight_balancing": True,
                "precision_decimal_places": 1,
                "require_exact_100": True,
                "balancing_algorithm": "even"
            }
        )
        
        root2 = db.create_subject_node(
            exam_context="Even Test",
            name="Root",
            level_type="Root",
            exam_weight_low=100.0,
            exam_weight_high=100.0
        )
        
        a2 = db.create_subject_node(
            exam_context="Even Test",
            name="A",
            parent_id=root2.id,
            level_type="System",
            exam_weight_low=20.0,
            exam_weight_high=20.0
        )
        
        b2 = db.create_subject_node(
            exam_context="Even Test",
            name="B",
            parent_id=root2.id,
            level_type="System",
            exam_weight_low=30.0,
            exam_weight_high=30.0
        )
        
        c2 = db.create_subject_node(
            exam_context="Even Test",
            name="C",
            parent_id=root2.id,
            level_type="System",
            exam_weight_low=50.0,
            exam_weight_high=50.0
        )
        
        # Update A to 40%
        result = db.update_subject_node_weight(a2.id, 40.0)
        
        print(f"\n🔄 EVEN Balancing (A increased by 20%):")
        children = db.get_subject_hierarchy("Even Test")[0].children
        for child in children:
            print(f"   {child.name}: {child.exam_weight_low}%")
        
        print(f"\n   Note: Both B and C lost the same amount (10% each)")
        print(f"   20% change / 2 siblings = 10% each")
        
        db.close()
        
    finally:
        db_path.unlink(missing_ok=True)


def main():
    """Run all Phase 2 examples"""
    print("="*60)
    print("  WIMI Phase 2: Exam Context & Weight Management Examples")
    print("="*60)
    
    demonstrate_exam_context_creation()
    demonstrate_hierarchy_levels()
    demonstrate_weight_balancing()
    demonstrate_weight_history()
    demonstrate_even_vs_proportional()
    
    print("\n" + "="*60)
    print("  All Phase 2 Examples Complete!")
    print("="*60)


if __name__ == "__main__":
    main()
