"""
Tests for MasterDatabase user CRUD operations
"""
import pytest
from database import (
    MasterDatabase, User, UserAlreadyExistsError, UserNotFoundError,
    InvalidUsernameError, InvalidUserTypeError
)


class TestUserCreation:
    """Test user creation functionality"""
    
    def test_create_basic_student(self, master_db, admin_user):
        """Test creating a basic student user"""
        user = master_db.create_user(
            username="john_doe",
            display_name="John Doe",
            email="john@test.com",
            user_types=["student"]
        )
        
        assert user.id > 0
        assert user.username == "john_doe"
        assert user.display_name == "John Doe"
        assert user.email == "john@test.com"
        assert user.user_type == ["student"]
        assert user.account_status == "active"
        assert user.is_primary_admin is False
        assert user.database_filename.startswith("user_")
        assert user.database_filename.endswith("_john_doe.db")
    
    def test_create_user_without_email(self, master_db, admin_user):
        """Test creating user without email (optional field)"""
        user = master_db.create_user(
            username="nomail",
            display_name="No Email",
            user_types=["student"]
        )
        
        assert user.email is None
        assert user.username == "nomail"
    
    def test_create_power_user(self, master_db, admin_user):
        """Test creating a power user (tutor/parent)"""
        user = master_db.create_user(
            username="tutor",
            display_name="Jane Tutor",
            email="tutor@test.com",
            user_types=["power_user", "student"]
        )
        
        assert "power_user" in user.user_type
        assert "student" in user.user_type
        assert user.is_power_user() is True
    
    def test_create_admin_user(self, master_db, admin_user):
        """Test creating an admin user (not primary)"""
        user = master_db.create_user(
            username="admin2",
            display_name="Second Admin",
            email="admin2@test.com",
            user_types=["admin", "student"]
        )
        
        assert "admin" in user.user_type
        assert user.is_admin() is True
        assert user.is_primary_admin is False
        assert user.can_manage_users is True
        assert user.can_view_all_statistics is True
    
    def test_create_user_with_multiple_types(self, master_db, admin_user):
        """Test creating user with multiple user types"""
        user = master_db.create_user(
            username="multi",
            display_name="Multi Type",
            user_types=["student", "power_user"]
        )
        
        assert len(user.user_type) == 2
        assert "student" in user.user_type
        assert "power_user" in user.user_type
    
    def test_default_user_type_is_student(self, master_db, admin_user):
        """Test that user_types defaults to ['student'] if not specified"""
        user = master_db.create_user(
            username="default",
            display_name="Default Type"
        )
        
        assert user.user_type == ["student"]
    
    def test_duplicate_username_fails(self, master_db, admin_user):
        """Test that creating user with duplicate username fails"""
        master_db.create_user(
            username="duplicate",
            display_name="First User"
        )
        
        with pytest.raises(UserAlreadyExistsError):
            master_db.create_user(
                username="duplicate",
                display_name="Second User"
            )
    
    def test_duplicate_email_fails(self, master_db, admin_user):
        """Test that creating user with duplicate email fails"""
        master_db.create_user(
            username="user1",
            display_name="User One",
            email="same@test.com"
        )
        
        with pytest.raises(UserAlreadyExistsError):
            master_db.create_user(
                username="user2",
                display_name="User Two",
                email="same@test.com"
            )


class TestUserRetrieval:
    """Test user retrieval functionality"""
    
    def test_get_user_by_id(self, master_db, admin_user):
        """Test retrieving user by ID"""
        created = master_db.create_user(
            username="test",
            display_name="Test User"
        )
        
        retrieved = master_db.get_user(user_id=created.id)
        
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.username == created.username
        assert retrieved.display_name == created.display_name
    
    def test_get_user_by_username(self, master_db, admin_user):
        """Test retrieving user by username"""
        created = master_db.create_user(
            username="findme",
            display_name="Find Me"
        )
        
        retrieved = master_db.get_user(username="findme")
        
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.username == "findme"
    
    def test_get_nonexistent_user_returns_none(self, master_db):
        """Test that getting non-existent user returns None"""
        user_by_id = master_db.get_user(user_id=99999)
        user_by_name = master_db.get_user(username="doesnotexist")
        
        assert user_by_id is None
        assert user_by_name is None
    
    def test_get_user_requires_id_or_username(self, master_db):
        """Test that get_user requires either user_id or username"""
        with pytest.raises(ValueError):
            master_db.get_user()
    
    def test_get_all_users_returns_list(self, master_db_with_users):
        """Test getting all users returns correct list"""
        master_db, admin, student, tutor = master_db_with_users
        
        all_users = master_db.get_all_users()
        
        assert len(all_users) == 3
        assert all(isinstance(u, User) for u in all_users)
        
        usernames = [u.username for u in all_users]
        assert "admin" in usernames
        assert "student" in usernames
        assert "tutor" in usernames
    
    def test_get_all_users_excludes_deleted_by_default(self, master_db_with_users):
        """Test that get_all_users excludes soft-deleted users by default"""
        master_db, admin, student, tutor = master_db_with_users
        
        # Soft delete a user
        master_db.soft_delete_user(student.id)
        
        # Get all users (should exclude deleted)
        all_users = master_db.get_all_users(include_deleted=False)
        
        assert len(all_users) == 2
        usernames = [u.username for u in all_users]
        assert "student" not in usernames
    
    def test_get_all_users_includes_deleted_when_requested(self, master_db_with_users):
        """Test that get_all_users can include deleted users"""
        master_db, admin, student, tutor = master_db_with_users
        
        # Soft delete a user
        master_db.soft_delete_user(student.id)
        
        # Get all users including deleted
        all_users = master_db.get_all_users(include_deleted=True)
        
        assert len(all_users) == 3
        usernames = [u.username for u in all_users]
        assert "student" in usernames
    
    def test_get_all_users_filter_by_status(self, master_db_with_users):
        """Test filtering users by account status"""
        master_db, admin, student, tutor = master_db_with_users
        
        # Suspend a user
        master_db.update_user(student.id, account_status="suspended")
        
        # Get only active users
        active_users = master_db.get_all_users(account_status="active")
        
        assert len(active_users) == 2
        usernames = [u.username for u in active_users]
        assert "student" not in usernames
        
        # Get suspended users
        suspended_users = master_db.get_all_users(account_status="suspended")
        
        assert len(suspended_users) == 1
        assert suspended_users[0].username == "student"


class TestUserUpdate:
    """Test user update functionality"""
    
    def test_update_display_name(self, master_db, admin_user):
        """Test updating user's display name"""
        user = master_db.create_user(
            username="test",
            display_name="Original Name"
        )
        
        updated = master_db.update_user(
            user_id=user.id,
            display_name="Updated Name"
        )
        
        assert updated.display_name == "Updated Name"
        assert updated.username == "test"  # Unchanged
    
    def test_update_email(self, master_db, admin_user):
        """Test updating user's email"""
        user = master_db.create_user(
            username="test",
            display_name="Test",
            email="old@test.com"
        )
        
        updated = master_db.update_user(
            user_id=user.id,
            email="new@test.com"
        )
        
        assert updated.email == "new@test.com"
    
    def test_update_user_types(self, master_db, admin_user):
        """Test updating user's types"""
        user = master_db.create_user(
            username="test",
            display_name="Test",
            user_types=["student"]
        )
        
        updated = master_db.update_user(
            user_id=user.id,
            user_types=["student", "power_user"]
        )
        
        assert "student" in updated.user_type
        assert "power_user" in updated.user_type
    
    def test_update_account_status(self, master_db, admin_user):
        """Test updating user's account status"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        updated = master_db.update_user(
            user_id=user.id,
            account_status="suspended"
        )
        
        assert updated.account_status == "suspended"
        assert updated.is_active() is False
    
    def test_update_multiple_fields(self, master_db, admin_user):
        """Test updating multiple fields at once"""
        user = master_db.create_user(
            username="test",
            display_name="Original",
            email="old@test.com"
        )
        
        updated = master_db.update_user(
            user_id=user.id,
            display_name="New Name",
            email="new@test.com",
            user_types=["student", "power_user"],
            account_status="suspended"
        )
        
        assert updated.display_name == "New Name"
        assert updated.email == "new@test.com"
        assert "power_user" in updated.user_type
        assert updated.account_status == "suspended"
    
    def test_update_nonexistent_user_fails(self, master_db):
        """Test that updating non-existent user fails"""
        with pytest.raises(UserNotFoundError):
            master_db.update_user(
                user_id=99999,
                display_name="New Name"
            )
    
    def test_update_with_no_changes_returns_user(self, master_db, admin_user):
        """Test that update with no changes returns existing user"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Update with no parameters
        updated = master_db.update_user(user_id=user.id)
        
        assert updated.id == user.id
        assert updated.display_name == user.display_name
    
    def test_update_with_invalid_status_fails(self, master_db, admin_user):
        """Test that updating with invalid status fails"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )

        with pytest.raises(ValueError):
            master_db.update_user(
                user_id=user.id,
                account_status="invalid_status"
            )


class TestTouchUserLastActive:
    """Test touch_user_last_active functionality"""

    def test_touch_sets_last_active(self, master_db, admin_user):
        """Test that touching a user sets last_active_at in the DB"""
        master_db.touch_user_last_active(admin_user.id)

        row = master_db.fetchone(
            "SELECT last_active_at FROM users WHERE id = ?",
            (admin_user.id,)
        )
        assert row['last_active_at'] is not None

    def test_touch_updates_existing_value(self, master_db, admin_user):
        """Test that touching replaces a stale last_active_at value"""
        # Plant a stale sentinel timestamp
        with master_db.transaction():
            master_db.execute(
                "UPDATE users SET last_active_at = '2020-01-01 00:00:00' WHERE id = ?",
                (admin_user.id,)
            )

        master_db.touch_user_last_active(admin_user.id)

        row = master_db.fetchone(
            "SELECT last_active_at FROM users WHERE id = ?",
            (admin_user.id,)
        )
        assert row['last_active_at'] != '2020-01-01 00:00:00'

    def test_touch_nonexistent_user_is_noop(self, master_db):
        """Test that touching a non-existent user does not raise"""
        master_db.touch_user_last_active(99999)
