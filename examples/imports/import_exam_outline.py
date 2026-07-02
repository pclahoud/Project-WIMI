"""
USMLE Content Outline Import Utility
Imports hierarchical subject structures from JSON files into Project WIMI

Usage:
    python import_exam_outline.py <json_file> [--user-id <id>] [--db-path <path>]
    
Example:
    python import_exam_outline.py usmle_cardiovascular.json --user-id 1
"""
import json
import argparse
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import date
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.database import UserDatabase
from src.database.models import SubjectNode, NodeAlias


class ExamOutlineImporter:
    """
    Imports exam content outlines from JSON files into the WIMI database.
    
    Handles:
    - Hierarchical subject node creation
    - Alias creation for abbreviations/synonyms
    - Exam context configuration
    - Depth limiting (caps at max_depth levels)
    """
    
    def __init__(
        self,
        db: UserDatabase,
        max_depth: int = 5,
        verbose: bool = True
    ):
        """
        Initialize the importer.
        
        Args:
            db: UserDatabase instance
            max_depth: Maximum hierarchy depth (default 5)
            verbose: Print progress messages
        """
        self.db = db
        self.max_depth = max_depth
        self.verbose = verbose
        self.stats = {
            'nodes_created': 0,
            'aliases_created': 0,
            'skipped_depth': 0,
            'errors': []
        }
    
    def log(self, message: str) -> None:
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(message)
    
    def import_from_json(self, json_path: Path) -> Dict[str, Any]:
        """
        Import exam outline from JSON file.
        
        Args:
            json_path: Path to JSON file
            
        Returns:
            Import statistics dictionary
        """
        self.log(f"\n{'='*60}")
        self.log(f"Importing: {json_path.name}")
        self.log(f"{'='*60}")
        
        # Load JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Extract metadata
        metadata = data.get('exam_metadata', {})
        exam_name = metadata.get('exam_name', 'Unknown Exam')
        exam_source = metadata.get('exam_source', 'Import')
        hierarchy_levels = metadata.get('hierarchy_levels', 
            ['System', 'Category', 'Subcategory', 'Topic', 'Subtopic'])
        
        self.log(f"\nExam: {exam_name}")
        self.log(f"Source: {exam_source}")
        self.log(f"Hierarchy Levels: {' → '.join(hierarchy_levels)}")
        self.log(f"Max Depth: {self.max_depth}")
        
        # Check if exam context exists, create if needed
        existing_contexts = self.db.get_all_exam_contexts() if hasattr(self.db, 'get_all_exam_contexts') else []
        exam_exists = any(ec.exam_name == exam_name for ec in existing_contexts)
        
        if not exam_exists and hasattr(self.db, 'create_exam_context'):
            self.log(f"\nCreating exam context: {exam_name}")
            self.db.create_exam_context(
                exam_name=exam_name,
                exam_description=metadata.get('notes', ''),
                hierarchy_levels=hierarchy_levels
            )
        
        # Import subjects
        subjects = data.get('subjects', [])
        self.log(f"\nImporting {len(subjects)} top-level subject(s)...")
        
        for subject in subjects:
            self._import_subject_recursive(
                subject=subject,
                exam_context=exam_name,
                exam_source=exam_source,
                parent_id=None,
                current_depth=1
            )
        
        # Print summary
        self.log(f"\n{'='*60}")
        self.log("Import Summary:")
        self.log(f"{'='*60}")
        self.log(f"  Nodes created: {self.stats['nodes_created']}")
        self.log(f"  Aliases created: {self.stats['aliases_created']}")
        self.log(f"  Skipped (depth limit): {self.stats['skipped_depth']}")
        if self.stats['errors']:
            self.log(f"  Errors: {len(self.stats['errors'])}")
            for err in self.stats['errors'][:5]:
                self.log(f"    - {err}")
        
        return self.stats
    
    def _import_subject_recursive(
        self,
        subject: Dict[str, Any],
        exam_context: str,
        exam_source: str,
        parent_id: Optional[int],
        current_depth: int
    ) -> Optional[int]:
        """
        Recursively import a subject and its children.
        
        Args:
            subject: Subject dictionary from JSON
            exam_context: Exam context name
            exam_source: Source document name
            parent_id: Parent node ID (None for root)
            current_depth: Current depth in hierarchy
            
        Returns:
            Created node ID or None if skipped
        """
        # Check depth limit
        if current_depth > self.max_depth:
            self.stats['skipped_depth'] += 1
            name = subject.get('name', 'Unknown')
            self.log(f"    {'  ' * current_depth}[SKIPPED - depth limit] {name}")
            return None
        
        # Extract subject data
        name = subject.get('name', 'Unknown')
        level_type = subject.get('level_type', f'Level{current_depth}')
        sort_order = subject.get('sort_order', 1)
        aliases = subject.get('aliases', [])
        children = subject.get('children', [])
        
        # Create the subject node
        try:
            node = self.db.create_subject_node(
                exam_context=exam_context,
                name=name,
                parent_id=parent_id,
                level_type=level_type,
                sort_order=sort_order,
                exam_source=exam_source
            )
            
            self.stats['nodes_created'] += 1
            indent = '  ' * current_depth
            self.log(f"  {indent}✓ {name} (ID: {node.id})")
            
            # Create aliases if the database supports it
            if aliases and hasattr(self.db, 'create_node_alias'):
                for alias in aliases:
                    try:
                        self.db.create_node_alias(
                            subject_node_id=node.id,
                            alias_name=alias,
                            alias_type='abbreviation' if len(alias) <= 5 else 'synonym'
                        )
                        self.stats['aliases_created'] += 1
                    except Exception as e:
                        # Alias creation is optional, don't fail the import
                        pass
            elif aliases:
                # Store aliases in a note or log them
                self.log(f"  {indent}  → Aliases: {', '.join(aliases)}")
            
            # Import children recursively
            for child in children:
                self._import_subject_recursive(
                    subject=child,
                    exam_context=exam_context,
                    exam_source=exam_source,
                    parent_id=node.id,
                    current_depth=current_depth + 1
                )
            
            return node.id
            
        except Exception as e:
            self.stats['errors'].append(f"{name}: {str(e)}")
            self.log(f"  {'  ' * current_depth}✗ {name} - ERROR: {e}")
            return None


def validate_json_structure(json_path: Path) -> bool:
    """
    Validate that a JSON file has the expected structure.
    
    Args:
        json_path: Path to JSON file
        
    Returns:
        True if valid, False otherwise
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Check required top-level keys
        if 'subjects' not in data:
            print(f"ERROR: Missing 'subjects' key in JSON")
            return False
        
        if not isinstance(data['subjects'], list):
            print(f"ERROR: 'subjects' must be a list")
            return False
        
        # Check metadata (optional but recommended)
        if 'exam_metadata' not in data:
            print(f"WARNING: No 'exam_metadata' found, using defaults")
        
        return True
        
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON - {e}")
        return False
    except Exception as e:
        print(f"ERROR: Could not read file - {e}")
        return False


def demo_import():
    """
    Demonstrate the import functionality with a temporary database.
    """
    print("\n" + "="*60)
    print("  WIMI Exam Outline Import - Demo Mode")
    print("="*60)
    
    # Find the JSON file
    json_path = Path(__file__).parent / 'usmle_cardiovascular.json'
    
    if not json_path.exists():
        print(f"ERROR: Could not find {json_path}")
        return
    
    # Validate structure
    if not validate_json_structure(json_path):
        return
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)
    
    try:
        # Initialize database
        db = UserDatabase(db_path, user_id=1, username="demo_user")
        
        # Run import
        importer = ExamOutlineImporter(db, max_depth=5, verbose=True)
        stats = importer.import_from_json(json_path)
        
        # Show what was created
        print("\n" + "="*60)
        print("Verifying Import - Subject Hierarchy:")
        print("="*60)
        
        hierarchy = db.get_subject_hierarchy("USMLE Step 1")
        
        def print_tree(nodes: List[SubjectNode], indent: int = 0):
            for node in nodes:
                prefix = "  " * indent + ("├── " if indent > 0 else "")
                print(f"{prefix}{node.name} [{node.level_type}]")
                if node.children:
                    print_tree(node.children, indent + 1)
        
        print_tree(hierarchy)
        
        db.close()
        
    finally:
        # Cleanup
        db_path.unlink(missing_ok=True)


def main():
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description='Import exam content outlines into Project WIMI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Demo mode (uses temporary database)
  python import_exam_outline.py --demo
  
  # Import to specific database
  python import_exam_outline.py usmle_cardiovascular.json --db-path ./user1.db --user-id 1
  
  # Validate JSON without importing
  python import_exam_outline.py usmle_cardiovascular.json --validate-only
        """
    )
    
    parser.add_argument('json_file', nargs='?', help='JSON file to import')
    parser.add_argument('--demo', action='store_true', help='Run demo with temporary database')
    parser.add_argument('--validate-only', action='store_true', help='Only validate JSON structure')
    parser.add_argument('--db-path', type=Path, help='Path to user database')
    parser.add_argument('--user-id', type=int, default=1, help='User ID (default: 1)')
    parser.add_argument('--username', type=str, default='import_user', help='Username (default: import_user)')
    parser.add_argument('--max-depth', type=int, default=5, help='Maximum hierarchy depth (default: 5)')
    parser.add_argument('--quiet', action='store_true', help='Suppress progress messages')
    
    args = parser.parse_args()
    
    # Demo mode
    if args.demo:
        demo_import()
        return
    
    # Require JSON file for non-demo modes
    if not args.json_file:
        parser.print_help()
        return
    
    json_path = Path(args.json_file)
    if not json_path.exists():
        print(f"ERROR: File not found: {json_path}")
        return
    
    # Validate only mode
    if args.validate_only:
        if validate_json_structure(json_path):
            print("✓ JSON structure is valid")
        return
    
    # Full import mode
    if not args.db_path:
        print("ERROR: --db-path is required for import (or use --demo)")
        return
    
    if not validate_json_structure(json_path):
        return
    
    # Initialize database and import
    db = UserDatabase(
        args.db_path,
        user_id=args.user_id,
        username=args.username
    )
    
    try:
        importer = ExamOutlineImporter(
            db,
            max_depth=args.max_depth,
            verbose=not args.quiet
        )
        importer.import_from_json(json_path)
    finally:
        db.close()


if __name__ == '__main__':
    main()
