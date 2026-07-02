"""
Debug script for tag seeding issue
Run from project root: python debug_tags.py
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from database import UserDatabase
from pathlib import Path

def main():
    # Find user database
    data_dir = Path(__file__).parent / 'app_data' / 'users'
    
    print("Looking for user databases in:", data_dir)
    
    if not data_dir.exists():
        print("ERROR: data/users directory not found")
        return
    
    # List all .db files
    db_files = list(data_dir.glob('*.db'))
    print(f"Found {len(db_files)} database files:")
    for db in db_files:
        print(f"  - {db.name}")
    
    if not db_files:
        print("No user databases found!")
        return
    
    # Use first database found
    db_path = db_files[0]
    print(f"\nUsing database: {db_path}")
    
    # Extract user info from filename (user_001_demo_user.db)
    # Format: user_{id}_{username}.db
    filename = db_path.stem  # user_001_demo_user
    parts = filename.split('_', 2)  # ['user', '001', 'demo_user']
    user_id = int(parts[1]) if len(parts) > 1 else 1
    username = parts[2] if len(parts) > 2 else 'demo_user'
    
    print(f"User ID: {user_id}, Username: {username}")
    
    # Connect to user database
    user_db = UserDatabase(db_path, user_id, username)
    
    # Check tags table schema
    print("\n--- Tags Table Schema ---")
    try:
        columns = user_db.fetchall("PRAGMA table_info(tags)")
        if columns:
            for col in columns:
                print(f"  {col['name']}: {col['type']} (nullable: {not col['notnull']})")
        else:
            print("  Tags table does not exist!")
    except Exception as e:
        print(f"  Error checking schema: {e}")
    
    # Check existing tags
    print("\n--- Existing Tags ---")
    try:
        tags = user_db.fetchall("SELECT * FROM tags LIMIT 20")
        if tags:
            for tag in tags:
                print(f"  ID={tag['id']}, name={tag['tag_name']}, exam={tag['exam_context']}, is_group={tag.get('is_group', 'N/A')}")
        else:
            print("  No tags found in database")
    except Exception as e:
        print(f"  Error fetching tags: {e}")
    
    # Try to seed default tags
    exam_context = "USMLE Step 1"
    print(f"\n--- Attempting to seed tags for '{exam_context}' ---")
    
    try:
        user_db.seed_default_tags(exam_context)
        print("  seed_default_tags() completed without error")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    
    # Check tags after seeding
    print("\n--- Tags After Seeding ---")
    try:
        tags = user_db.fetchall("SELECT * FROM tags WHERE exam_context = ?", (exam_context,))
        if tags:
            for tag in tags:
                print(f"  ID={tag['id']}, name={tag['tag_name']}, is_group={tag.get('is_group', 'N/A')}, parent={tag.get('parent_id', 'N/A')}")
        else:
            print("  Still no tags found after seeding!")
    except Exception as e:
        print(f"  Error fetching tags: {e}")
    
    # Test get_tag_hierarchy
    print("\n--- Testing get_tag_hierarchy ---")
    try:
        hierarchy = user_db.get_tag_hierarchy(exam_context)
        print(f"  Returned {len(hierarchy)} top-level items")
        for item in hierarchy:
            print(f"    - {item['name']} (is_group={item.get('is_group')}, children={len(item.get('children', []))})")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
