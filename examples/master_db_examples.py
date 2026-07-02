"""
MasterDatabase Usage Examples
Demonstrates how to use the MasterDatabase class
"""
from pathlib import Path
from src.database import MasterDatabase
from src.app_logging import ErrorLogger

# Example 1: Initialize Master Database
def example_initialize():
    """Initialize master database with error logging"""
    # Set up error logger
    error_logger = ErrorLogger(app_name="WIMIApp", mode='development')
    
    # Initialize master database (will be created at ~/.wimi/users.db)
    master_db = MasterDatabase(error_logger=error_logger)
    
    print(f"Master database initialized at: {master_db.db_path}")
    print(f"User databases directory: {master_db.users_dir}")
    print(f"Archive directory: {master_db.archive_dir}")
    
    return master_db


# Example 2: Bootstrap First User
def example_bootstrap_first_user():
    """Create the first user (primary admin) during setup"""
    error_logger = ErrorLogger(mode='development')
    master_db = MasterDatabase(error_logger=error_logger)
    
    # Create first user - automatically becomes primary admin
    admin = master_db.bootstrap_first_user(
        username="admin",
        display_name="System Administrator",
        email="admin@example.com"
    )
    
    print(f"Created primary admin: {admin.username}")
    print(f"User ID: {admin.id}")
    print(f"User types: {admin.user_type}")
    print(f"Is primary admin: {admin.is_primary_admin}")
    print(f"Database file: {admin.database_filename}")
    
    return master_db, admin


# Example 3: Create Regular Users
def example_create_users():
    """Create various types of users"""
    error_logger = ErrorLogger(mode='development')
    master_db = MasterDatabase(error_logger=error_logger)
    
    # Create a student
    student = master_db.create_user(
        username="john_doe",
        display_name="John Doe",
        email="john@example.com",
        user_types=["student"]
    )
    print(f"Created student: {student.username} (ID: {student.id})")
    
    # Create a power user (tutor/parent)
    tutor = master_db.create_user(
        username="jane_tutor",
        display_name="Jane Smith",
        email="jane@example.com",
        user_types=["power_user", "student"]
    )
    print(f"Created power user: {tutor.username} (ID: {tutor.id})")
    
    # Create an additional admin
    admin = master_db.create_user(
        username="backup_admin",
        display_name="Backup Admin",
        email="backup@example.com",
        user_types=["admin", "student"]
    )
    print(f"Created admin: {admin.username} (ID: {admin.id})")
    print(f"Is primary admin: {admin.is_primary_admin}")  # False
    
    return master_db


# Example 4: Retrieve Users
def example_get_users():
    """Retrieve users from database"""
    error_logger = ErrorLogger(mode='development')
    master_db = MasterDatabase(error_logger=error_logger)
    
    # Get user by ID
    user = master_db.get_user(user_id=1)
    if user:
        print(f"User by ID: {user.username}")
    
    # Get user by username
    user = master_db.get_user(username="john_doe")
    if user:
        print(f"User by username: {user.username}")
    
    # Get all active users
    active_users = master_db.get_all_users(include_deleted=False)
    print(f"\nActive users: {len(active_users)}")
    for user in active_users:
        print(f"  - {user.username} ({', '.join(user.user_type)})")
    
    return master_db


# Example 5: Update User
def example_update_user():
    """Update user information"""
    error_logger = ErrorLogger(mode='development')
    master_db = MasterDatabase(error_logger=error_logger)
    
    # Get existing user
    user = master_db.get_user(username="john_doe")
    if not user:
        print("User not found")
        return
    
    # Update user
    updated_user = master_db.update_user(
        user_id=user.id,
        display_name="John M. Doe",
        email="john.doe@example.com"
    )
    
    print(f"Updated user: {updated_user.username}")
    print(f"New display name: {updated_user.display_name}")
    print(f"New email: {updated_user.email}")
    
    return master_db


# Example 6: Lazy User Database Creation
def example_lazy_database_creation():
    """Demonstrate lazy creation of user database files"""
    error_logger = ErrorLogger(mode='development')
    master_db = MasterDatabase(error_logger=error_logger)
    
    # Create user (database file NOT created yet)
    user = master_db.create_user(
        username="test_user",
        display_name="Test User",
        user_types=["student"]
    )
    
    print(f"User created: {user.username}")
    print(f"Expected database file: {user.database_filename}")
    
    user_db_path = master_db.users_dir / user.database_filename
    print(f"Database exists: {user_db_path.exists()}")  # False
    
    # Now create the database file (lazy creation)
    db_path = master_db.ensure_user_database(user.id)
    
    print(f"Database created at: {db_path}")
    print(f"Database exists: {db_path.exists()}")  # True
    
    return master_db


# Example 7: Soft Delete User
def example_soft_delete_user():
    """Soft delete a user with grace period"""
    error_logger = ErrorLogger(mode='development')
    master_db = MasterDatabase(error_logger=error_logger)
    
    # Create a user
    user = master_db.create_user(
        username="temp_user",
        display_name="Temporary User",
        user_types=["student"]
    )
    
    print(f"Created user: {user.username}")
    print(f"Account status: {user.account_status}")
    
    # Soft delete the user
    master_db.soft_delete_user(user.id)
    
    # Check status
    deleted_user = master_db.get_user(user.id)
    print(f"\nAfter soft delete:")
    print(f"Account status: {deleted_user.account_status}")
    print(f"Deleted at: {deleted_user.soft_deleted_at}")
    print(f"Database file moved to archive")
    
    return master_db


# Example 8: Restore Deleted User
def example_restore_user():
    """Restore a soft-deleted user within grace period"""
    error_logger = ErrorLogger(mode='development')
    master_db = MasterDatabase(error_logger=error_logger)
    
    # Assume user was soft-deleted
    deleted_user = master_db.get_user(username="temp_user")
    
    if deleted_user and deleted_user.account_status == 'soft_deleted':
        print(f"Found deleted user: {deleted_user.username}")
        
        # Restore the user
        restored_user = master_db.restore_user(deleted_user.id)
        
        print(f"\nRestored user: {restored_user.username}")
        print(f"Account status: {restored_user.account_status}")
        print(f"Database file restored from archive")
    
    return master_db


# Example 9: App Settings
def example_app_settings():
    """Manage application settings"""
    error_logger = ErrorLogger(mode='development')
    master_db = MasterDatabase(error_logger=error_logger)
    
    # Set various settings
    master_db.set_setting(
        setting_key="app_version",
        setting_value="1.0.0",
        setting_type="string",
        description="Current application version"
    )
    
    master_db.set_setting(
        setting_key="max_sessions",
        setting_value="5",
        setting_type="integer",
        description="Maximum concurrent sessions"
    )
    
    master_db.set_setting(
        setting_key="enable_analytics",
        setting_value="true",
        setting_type="boolean",
        description="Enable anonymous analytics"
    )
    
    # Retrieve settings
    version = master_db.get_setting("app_version")
    print(f"App version: {version.get_typed_value()}")
    
    max_sessions = master_db.get_setting("max_sessions")
    print(f"Max sessions: {max_sessions.get_typed_value()}")
    
    analytics = master_db.get_setting("enable_analytics")
    print(f"Analytics enabled: {analytics.get_typed_value()}")
    
    return master_db


# Example 10: Complete Workflow
def example_complete_workflow():
    """Complete workflow from setup to user management"""
    print("=" * 60)
    print("Complete MasterDatabase Workflow")
    print("=" * 60)
    
    # Initialize
    error_logger = ErrorLogger(mode='development')
    master_db = MasterDatabase(error_logger=error_logger)
    
    # Bootstrap first user
    print("\n1. Bootstrap first user (primary admin)")
    admin = master_db.bootstrap_first_user(
        username="admin",
        display_name="System Admin",
        email="admin@wimi.app"
    )
    print(f"   Created: {admin.username} (Primary Admin: {admin.is_primary_admin})")
    
    # Create students
    print("\n2. Create students")
    student1 = master_db.create_user(
        username="alice",
        display_name="Alice Johnson",
        email="alice@example.com",
        user_types=["student"]
    )
    print(f"   Created: {student1.username}")
    
    student2 = master_db.create_user(
        username="bob",
        display_name="Bob Smith",
        user_types=["student"]
    )
    print(f"   Created: {student2.username}")
    
    # Create power user
    print("\n3. Create power user (tutor)")
    tutor = master_db.create_user(
        username="tutor_jane",
        display_name="Jane Tutor",
        email="jane@example.com",
        user_types=["power_user", "student"]
    )
    print(f"   Created: {tutor.username}")
    
    # List all users
    print("\n4. List all users")
    all_users = master_db.get_all_users()
    for user in all_users:
        print(f"   - {user.username}: {', '.join(user.user_type)}")
    
    # Create user databases (lazy)
    print("\n5. Create user databases")
    for user in all_users:
        db_path = master_db.ensure_user_database(user.id)
        print(f"   Database for {user.username}: {db_path.name}")
    
    # Set app settings
    print("\n6. Configure app settings")
    master_db.set_setting("app_version", "1.0.0", "string")
    master_db.set_setting("enable_cloud_sync", "false", "boolean")
    print("   Settings configured")
    
    print("\n" + "=" * 60)
    print("Workflow complete!")
    print("=" * 60)
    
    return master_db


if __name__ == "__main__":
    # Run the complete workflow example
    example_complete_workflow()
