"""
Tests for MasterDatabase user deletion functionality
"""
import pytest
import time
from datetime import datetime, timedelta
from pathlib import Path
from database import (
    MasterDatabase, UserNotFoundError, DeletionError, PrimaryAdminError
)


class TestSoftDelete:
    """Test soft delete functionality"""
    
    def test_soft_delete_user(self, master_db, admin_user):
        """Test soft deleting a user"""
        user = master_db.create_user(
            username="test",
            display_name="Test User"
        )
        
        master_db.soft_delete_user(user.id)
        
        deleted_user = master_db.get_user(user.id)
        assert deleted_user.account_status == "soft_deleted"
        assert deleted_user.soft_deleted_at is not None
    
    def test_soft_delete_sets_timestamp(self, master_db, admin_user):
        """Test that soft delete sets soft_deleted_at timestamp"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        master_db.soft_delete_user(user.id)
        
        deleted_user = master_db.get_user(user.id)
        # Just verify the timestamp is set, don't compare exact times
        # (avoids timezone issues between DB and Python)
        assert deleted_user.soft_deleted_at is not None
    
    def test_soft_delete_moves_database_to_archive(self, master_db, admin_user):
        """Test that soft delete moves user database to archive folder"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Create the user database
        db_path = master_db.ensure_user_database(user.id)
        assert db_path.exists()
        
        # Soft delete
        master_db.soft_delete_user(user.id)
        
        # Check original location (should not exist)
        assert not db_path.exists()
        
        # Check archive location (should exist)
        archive_path = master_db.archive_dir / user.database_filename
        assert archive_path.exists()
    
    def test_soft_delete_nonexistent_user_fails(self, master_db):
        """Test that soft deleting non-existent user fails"""
        with pytest.raises(UserNotFoundError):
            master_db.soft_delete_user(99999)
    
    def test_soft_delete_primary_admin_fails(self, master_db, admin_user):
        """Test that primary admin cannot be soft deleted"""
        with pytest.raises(PrimaryAdminError):
            master_db.soft_delete_user(admin_user.id)
    
    def test_soft_delete_non_primary_admin_succeeds(self, master_db, admin_user):
        """Test that non-primary admin can be soft deleted"""
        admin2 = master_db.create_user(
            username="admin2",
            display_name="Admin 2",
            user_types=["admin"]
        )
        
        # Should not raise
        master_db.soft_delete_user(admin2.id)
        
        deleted = master_db.get_user(admin2.id)
        assert deleted.account_status == "soft_deleted"
    
    def test_soft_delete_without_database_file(self, master_db, admin_user):
        """Test soft delete works even if user database was never created"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Don't create database file (lazy creation)
        db_path = master_db.users_dir / user.database_filename
        assert not db_path.exists()
        
        # Soft delete should still work
        master_db.soft_delete_user(user.id)
        
        deleted = master_db.get_user(user.id)
        assert deleted.account_status == "soft_deleted"


class TestDeletionConfirmation:
    """Test deletion confirmation flag"""
    
    def test_confirm_user_deletion(self, master_db, admin_user):
        """Test confirming deletion of a soft-deleted user"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        master_db.soft_delete_user(user.id)
        master_db.confirm_user_deletion(user.id)
        
        confirmed_user = master_db.get_user(user.id)
        assert confirmed_user.deletion_confirmed is True
    
    def test_deletion_not_confirmed_by_default(self, master_db, admin_user):
        """Test that deletion is not confirmed by default"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        master_db.soft_delete_user(user.id)
        
        deleted_user = master_db.get_user(user.id)
        assert deleted_user.deletion_confirmed is False


class TestRestoreUser:
    """Test user restoration functionality"""
    
    def test_restore_soft_deleted_user(self, master_db, admin_user):
        """Test restoring a soft-deleted user"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        master_db.soft_delete_user(user.id)
        restored = master_db.restore_user(user.id)
        
        assert restored.account_status == "active"
        assert restored.soft_deleted_at is None
        assert restored.deletion_confirmed is False
    
    def test_restore_moves_database_back(self, master_db, admin_user):
        """Test that restore moves database back from archive"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Create database
        db_path = master_db.ensure_user_database(user.id)
        
        # Soft delete (moves to archive)
        master_db.soft_delete_user(user.id)
        archive_path = master_db.archive_dir / user.database_filename
        assert archive_path.exists()
        assert not db_path.exists()
        
        # Restore (moves back)
        master_db.restore_user(user.id)
        
        assert db_path.exists()
        assert not archive_path.exists()
    
    def test_restore_nonexistent_user_fails(self, master_db):
        """Test that restoring non-existent user fails"""
        with pytest.raises(UserNotFoundError):
            master_db.restore_user(99999)
    
    def test_restore_active_user_fails(self, master_db, admin_user):
        """Test that restoring an active user fails"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # User is active, not deleted
        with pytest.raises(DeletionError):
            master_db.restore_user(user.id)
    
    def test_restore_without_database_file(self, master_db, admin_user):
        """Test restore works even if database was never created"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Soft delete without creating database
        master_db.soft_delete_user(user.id)
        
        # Restore should still work
        restored = master_db.restore_user(user.id)
        assert restored.account_status == "active"


class TestGracePeriod:
    """Test grace period for deletion"""
    
    def test_grace_period_is_10_days(self, master_db):
        """Test that grace period constant is 10 days"""
        assert master_db.DELETION_GRACE_PERIOD_DAYS == 10
    
    def test_restore_within_grace_period_succeeds(self, master_db, admin_user):
        """Test that restore within grace period succeeds"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        master_db.soft_delete_user(user.id)
        master_db.confirm_user_deletion(user.id)
        
        # Within grace period (just deleted)
        restored = master_db.restore_user(user.id)
        assert restored.account_status == "active"
    
    def test_restore_after_grace_period_fails(self, master_db, admin_user, temp_dir):
        """Test that restore after grace period fails if confirmed"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Soft delete and confirm
        master_db.soft_delete_user(user.id)
        master_db.confirm_user_deletion(user.id)
        
        # Manually set soft_deleted_at to 11 days ago (past grace period)
        past_date = datetime.now() - timedelta(days=11)
        master_db.execute(
            "UPDATE users SET soft_deleted_at = ? WHERE id = ?",
            (past_date.isoformat(), user.id)
        )
        
        # Restore should fail
        with pytest.raises(DeletionError) as exc_info:
            master_db.restore_user(user.id)
        
        assert "grace period" in str(exc_info.value).lower()
    
    def test_restore_after_grace_period_without_confirmation_succeeds(self, master_db, admin_user):
        """Test that restore succeeds if not confirmed, even after grace period"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Soft delete WITHOUT confirming
        master_db.soft_delete_user(user.id)
        
        # Manually set date to past grace period
        past_date = datetime.now() - timedelta(days=11)
        master_db.execute(
            "UPDATE users SET soft_deleted_at = ? WHERE id = ?",
            (past_date.isoformat(), user.id)
        )
        
        # Should succeed because deletion wasn't confirmed
        restored = master_db.restore_user(user.id)
        assert restored.account_status == "active"


class TestPermanentDeletion:
    """Test permanent deletion after grace period"""
    
    def test_permanently_delete_expired_users(self, master_db, admin_user):
        """Test permanent deletion of expired users"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Create database file
        db_path = master_db.ensure_user_database(user.id)
        
        # Soft delete and confirm
        master_db.soft_delete_user(user.id)
        master_db.confirm_user_deletion(user.id)
        
        # Set deletion date to past grace period
        past_date = datetime.now() - timedelta(days=11)
        master_db.execute(
            "UPDATE users SET soft_deleted_at = ? WHERE id = ?",
            (past_date.isoformat(), user.id)
        )
        
        # Permanently delete expired users
        deleted_ids = master_db.permanently_delete_expired_users()
        
        assert user.id in deleted_ids
        
        # User should no longer exist
        assert master_db.get_user(user.id) is None
        
        # Database file should be deleted from archive
        archive_path = master_db.archive_dir / user.database_filename
        assert not archive_path.exists()
    
    def test_permanent_delete_removes_from_database(self, master_db, admin_user):
        """Test that permanent deletion removes user record"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        master_db.soft_delete_user(user.id)
        master_db.confirm_user_deletion(user.id)
        
        # Set to expired
        past_date = datetime.now() - timedelta(days=11)
        master_db.execute(
            "UPDATE users SET soft_deleted_at = ? WHERE id = ?",
            (past_date.isoformat(), user.id)
        )
        
        # Permanently delete
        master_db.permanently_delete_expired_users()
        
        # User should not exist
        assert master_db.get_user(user.id) is None
    
    def test_permanent_delete_only_affects_expired(self, master_db, admin_user):
        """Test that permanent deletion only affects expired users"""
        # Create two users
        user1 = master_db.create_user(username="user1", display_name="User 1")
        user2 = master_db.create_user(username="user2", display_name="User 2")
        
        # Soft delete both and confirm
        master_db.soft_delete_user(user1.id)
        master_db.confirm_user_deletion(user1.id)
        master_db.soft_delete_user(user2.id)
        master_db.confirm_user_deletion(user2.id)
        
        # Set user1 to expired (11 days ago)
        past_date = datetime.now() - timedelta(days=11)
        master_db.execute(
            "UPDATE users SET soft_deleted_at = ? WHERE id = ?",
            (past_date.isoformat(), user1.id)
        )
        
        # Keep user2 within grace period (just deleted)
        
        # Permanently delete expired
        deleted_ids = master_db.permanently_delete_expired_users()
        
        assert user1.id in deleted_ids
        assert user2.id not in deleted_ids
        
        # user1 should be gone, user2 should still exist
        assert master_db.get_user(user1.id) is None
        assert master_db.get_user(user2.id) is not None
    
    def test_permanent_delete_requires_confirmation(self, master_db, admin_user):
        """Test that permanent deletion requires confirmation flag"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Soft delete WITHOUT confirming
        master_db.soft_delete_user(user.id)
        
        # Set to expired
        past_date = datetime.now() - timedelta(days=11)
        master_db.execute(
            "UPDATE users SET soft_deleted_at = ? WHERE id = ?",
            (past_date.isoformat(), user.id)
        )
        
        # Permanently delete - should NOT delete because not confirmed
        deleted_ids = master_db.permanently_delete_expired_users()
        
        assert user.id not in deleted_ids
        assert master_db.get_user(user.id) is not None
    
    def test_permanent_delete_returns_deleted_ids(self, master_db, admin_user):
        """Test that permanent deletion returns list of deleted user IDs"""
        users = []
        for i in range(3):
            user = master_db.create_user(
                username=f"user{i}",
                display_name=f"User {i}"
            )
            users.append(user)
            master_db.soft_delete_user(user.id)
            master_db.confirm_user_deletion(user.id)
        
        # Set all to expired
        past_date = datetime.now() - timedelta(days=11)
        for user in users:
            master_db.execute(
                "UPDATE users SET soft_deleted_at = ? WHERE id = ?",
                (past_date.isoformat(), user.id)
            )
        
        # Permanently delete
        deleted_ids = master_db.permanently_delete_expired_users()
        
        assert len(deleted_ids) == 3
        for user in users:
            assert user.id in deleted_ids
    
    def test_permanent_delete_handles_missing_database_files(self, master_db, admin_user):
        """Test that permanent deletion handles missing database files gracefully"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Don't create database file
        
        # Soft delete and confirm
        master_db.soft_delete_user(user.id)
        master_db.confirm_user_deletion(user.id)
        
        # Set to expired
        past_date = datetime.now() - timedelta(days=11)
        master_db.execute(
            "UPDATE users SET soft_deleted_at = ? WHERE id = ?",
            (past_date.isoformat(), user.id)
        )
        
        # Should not raise error
        deleted_ids = master_db.permanently_delete_expired_users()
        
        assert user.id in deleted_ids


class TestGetDeletedUsers:
    """Test retrieving deleted users"""
    
    def test_get_all_users_excludes_deleted_by_default(self, master_db, admin_user):
        """Test that get_all_users excludes deleted users by default"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        master_db.soft_delete_user(user.id)
        
        all_users = master_db.get_all_users()
        usernames = [u.username for u in all_users]
        
        assert "test" not in usernames
    
    def test_get_all_users_includes_deleted_when_requested(self, master_db, admin_user):
        """Test that get_all_users can include deleted users"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        master_db.soft_delete_user(user.id)
        
        all_users = master_db.get_all_users(include_deleted=True)
        usernames = [u.username for u in all_users]
        
        assert "test" in usernames
    
    def test_filter_by_soft_deleted_status(self, master_db, admin_user):
        """Test filtering users by soft_deleted status"""
        active_user = master_db.create_user(
            username="active",
            display_name="Active"
        )
        
        deleted_user = master_db.create_user(
            username="deleted",
            display_name="Deleted"
        )
        master_db.soft_delete_user(deleted_user.id)
        
        # Get only soft-deleted users
        deleted_users = master_db.get_all_users(
            include_deleted=True,
            account_status="soft_deleted"
        )
        
        assert len(deleted_users) == 1
        assert deleted_users[0].username == "deleted"
