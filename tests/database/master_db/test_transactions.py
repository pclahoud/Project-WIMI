"""
Tests for transaction handling and rollback
"""
import pytest
from database import (
    MasterDatabase, UserAlreadyExistsError, InvalidUsernameError,
    UserNotFoundError
)


class TestTransactionCommit:
    """Test that successful operations commit properly"""
    
    def test_user_creation_commits(self, master_db, admin_user):
        """Test that user creation commits to database"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Verify user persists after creation
        retrieved = master_db.get_user(user.id)
        assert retrieved is not None
        assert retrieved.username == "test"
    
    def test_user_update_commits(self, master_db, admin_user):
        """Test that user updates commit to database"""
        user = master_db.create_user(
            username="test",
            display_name="Original"
        )
        
        master_db.update_user(user.id, display_name="Updated")
        
        # Verify update persists
        retrieved = master_db.get_user(user.id)
        assert retrieved.display_name == "Updated"
    
    def test_multiple_operations_in_transaction(self, master_db, admin_user):
        """Test that multiple operations in one transaction commit together"""
        # Create multiple users (each in its own transaction)
        user1 = master_db.create_user(username="user1", display_name="User 1")
        user2 = master_db.create_user(username="user2", display_name="User 2")
        user3 = master_db.create_user(username="user3", display_name="User 3")
        
        # All should be persisted
        all_users = master_db.get_all_users()
        assert len(all_users) >= 3  # At least these 3 (plus admin)
        
        usernames = [u.username for u in all_users]
        assert "user1" in usernames
        assert "user2" in usernames
        assert "user3" in usernames


class TestTransactionRollback:
    """Test that failed operations rollback properly"""
    
    def test_duplicate_username_rolls_back(self, master_db, admin_user):
        """Test that duplicate username attempt doesn't create partial state"""
        # Create first user
        user1 = master_db.create_user(
            username="duplicate",
            display_name="First User"
        )
        
        # Try to create duplicate
        with pytest.raises(UserAlreadyExistsError):
            master_db.create_user(
                username="duplicate",
                display_name="Second User"
            )
        
        # Verify only one user with this username exists
        all_users = master_db.get_all_users()
        duplicate_users = [u for u in all_users if u.username == "duplicate"]
        assert len(duplicate_users) == 1
        
        # Verify it's the first user
        assert duplicate_users[0].display_name == "First User"
    
    def test_duplicate_email_rolls_back(self, master_db, admin_user):
        """Test that duplicate email attempt doesn't create partial state"""
        user1 = master_db.create_user(
            username="user1",
            display_name="User 1",
            email="same@test.com"
        )
        
        with pytest.raises(UserAlreadyExistsError):
            master_db.create_user(
                username="user2",
                display_name="User 2",
                email="same@test.com"
            )
        
        # Verify only one user with this email
        all_users = master_db.get_all_users()
        same_email_users = [u for u in all_users if u.email == "same@test.com"]
        assert len(same_email_users) == 1
        assert same_email_users[0].username == "user1"
    
    def test_invalid_update_rolls_back(self, master_db, admin_user):
        """Test that invalid update doesn't modify data"""
        user = master_db.create_user(
            username="test",
            display_name="Original",
            email="original@test.com"
        )
        
        original_display = user.display_name
        original_email = user.email
        
        # Try invalid update (invalid account_status)
        with pytest.raises(ValueError):
            master_db.update_user(
                user_id=user.id,
                display_name="Updated",
                account_status="invalid_status"
            )
        
        # Verify user data unchanged
        retrieved = master_db.get_user(user.id)
        assert retrieved.display_name == original_display
        assert retrieved.email == original_email
    
    def test_update_nonexistent_user_no_side_effects(self, master_db, admin_user):
        """Test that updating non-existent user has no side effects"""
        # Get user count before
        users_before = master_db.get_all_users()
        count_before = len(users_before)
        
        # Try to update non-existent user
        with pytest.raises(UserNotFoundError):
            master_db.update_user(
                user_id=99999,
                display_name="New Name"
            )
        
        # Verify no users added or modified
        users_after = master_db.get_all_users()
        count_after = len(users_after)
        
        assert count_after == count_before
    
    def test_validation_failure_rolls_back(self, master_db, admin_user):
        """Test that validation failure doesn't create partial user"""
        users_before = master_db.get_all_users()
        count_before = len(users_before)
        
        # Try to create user with invalid username
        with pytest.raises(InvalidUsernameError):
            master_db.create_user(
                username="ab",  # Too short
                display_name="Invalid"
            )
        
        # Verify no new user created
        users_after = master_db.get_all_users()
        count_after = len(users_after)
        
        assert count_after == count_before


class TestTransactionIsolation:
    """Test transaction isolation between operations"""
    
    def test_failed_operation_doesnt_affect_next(self, master_db, admin_user):
        """Test that failed operation doesn't affect subsequent operations"""
        # Try to create user with duplicate username
        user1 = master_db.create_user(
            username="test",
            display_name="First"
        )
        
        with pytest.raises(UserAlreadyExistsError):
            master_db.create_user(
                username="test",
                display_name="Duplicate"
            )
        
        # Next operation should work fine
        user2 = master_db.create_user(
            username="test2",
            display_name="Second"
        )
        
        assert user2.username == "test2"
    
    def test_partial_failure_in_batch_operations(self, master_db, admin_user):
        """Test that one failure doesn't affect other operations"""
        # Create first user successfully
        user1 = master_db.create_user(username="user1", display_name="User 1")
        assert user1 is not None
        
        # Try to create duplicate (fails)
        with pytest.raises(UserAlreadyExistsError):
            master_db.create_user(username="user1", display_name="Duplicate")
        
        # Create third user successfully
        user3 = master_db.create_user(username="user3", display_name="User 3")
        assert user3 is not None
        
        # Verify both successful users exist
        all_users = master_db.get_all_users()
        usernames = [u.username for u in all_users]
        assert "user1" in usernames
        assert "user3" in usernames


class TestContextManagerTransactions:
    """Test transaction context manager behavior"""
    
    def test_transaction_context_commits_on_success(self, master_db, admin_user):
        """Test that transaction context commits on successful completion"""
        user = master_db.create_user(username="test", display_name="Test")
        
        with master_db.transaction():
            master_db.execute(
                "UPDATE users SET display_name = ? WHERE id = ?",
                ("Updated", user.id)
            )
        
        # Should be committed
        retrieved = master_db.get_user(user.id)
        assert retrieved.display_name == "Updated"
    
    def test_transaction_context_rolls_back_on_error(self, master_db, admin_user):
        """Test that transaction context rolls back on exception"""
        user = master_db.create_user(
            username="test",
            display_name="Original"
        )
        
        original_display = user.display_name
        
        try:
            with master_db.transaction():
                master_db.execute(
                    "UPDATE users SET display_name = ? WHERE id = ?",
                    ("Updated", user.id)
                )
                # Force an error
                raise Exception("Simulated error")
        except Exception:
            pass
        
        # Should be rolled back
        retrieved = master_db.get_user(user.id)
        assert retrieved.display_name == original_display


class TestDatabaseIntegrity:
    """Test database integrity after operations"""
    
    def test_user_count_consistent(self, master_db, admin_user):
        """Test that user count remains consistent after failed operations"""
        initial_count = len(master_db.get_all_users())
        
        # Create a valid user
        master_db.create_user(username="valid", display_name="Valid")
        assert len(master_db.get_all_users()) == initial_count + 1
        
        # Try to create invalid user
        with pytest.raises(InvalidUsernameError):
            master_db.create_user(username="ab", display_name="Invalid")
        
        # Count should not have changed
        assert len(master_db.get_all_users()) == initial_count + 1
    
    def test_foreign_key_integrity_maintained(self, master_db, admin_user):
        """Test that foreign key relationships remain valid"""
        user = master_db.create_user(username="test", display_name="Test")
        
        # user_database_schemas should have entry for this user
        schema_entry = master_db.fetchone(
            "SELECT * FROM user_database_schemas WHERE user_id = ?",
            (user.id,)
        )
        
        assert schema_entry is not None
        assert schema_entry['user_id'] == user.id
    
    def test_no_orphaned_records(self, master_db, admin_user):
        """Test that failed user creation doesn't leave orphaned records"""
        initial_schemas = master_db.fetchall(
            "SELECT * FROM user_database_schemas"
        )
        initial_count = len(initial_schemas)
        
        # Try to create duplicate user (should fail)
        user1 = master_db.create_user(username="test", display_name="First")
        
        with pytest.raises(UserAlreadyExistsError):
            master_db.create_user(username="test", display_name="Second")
        
        # Check that we don't have orphaned schema records
        final_schemas = master_db.fetchall(
            "SELECT * FROM user_database_schemas"
        )
        
        # Should only have one additional schema record (for user1)
        assert len(final_schemas) == initial_count + 1


class TestConcurrentTransactions:
    """Test behavior with multiple database instances"""
    
    def test_multiple_connections_to_same_database(self, temp_dir):
        """Test that multiple connections handle transactions properly"""
        # Create two separate connections to same database
        db1 = MasterDatabase(data_dir=temp_dir, error_logger=None)
        db2 = MasterDatabase(data_dir=temp_dir, error_logger=None)
        
        try:
            # Bootstrap with first connection
            admin = db1.bootstrap_first_user(
                username="admin",
                display_name="Admin"
            )
            
            # Create user with first connection
            user1 = db1.create_user(username="user1", display_name="User 1")
            
            # Verify visible from second connection
            user1_from_db2 = db2.get_user(user1.id)
            assert user1_from_db2 is not None
            assert user1_from_db2.username == "user1"
            
            # Create user with second connection
            user2 = db2.create_user(username="user2", display_name="User 2")
            
            # Verify visible from first connection
            user2_from_db1 = db1.get_user(user2.id)
            assert user2_from_db1 is not None
            assert user2_from_db1.username == "user2"
            
        finally:
            db1.close()
            db2.close()
