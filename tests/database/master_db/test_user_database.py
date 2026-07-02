"""
Tests for user database file operations
"""
import pytest
import sqlite3
from pathlib import Path
from database import (
    MasterDatabase, UserNotFoundError, DatabaseCreationError
)


class TestLazyDatabaseCreation:
    """Test lazy creation of user databases"""
    
    def test_database_not_created_on_user_creation(self, master_db, admin_user):
        """Test that user database is NOT created when user is created"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        db_path = master_db.users_dir / user.database_filename
        assert not db_path.exists()
    
    def test_database_created_on_ensure(self, master_db, admin_user):
        """Test that database is created when ensure_user_database is called"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        db_path = master_db.ensure_user_database(user.id)
        
        assert db_path.exists()
        assert db_path == master_db.users_dir / user.database_filename
    
    def test_ensure_idempotent(self, master_db, admin_user):
        """Test that calling ensure_user_database multiple times is safe"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        # Call multiple times
        db_path1 = master_db.ensure_user_database(user.id)
        db_path2 = master_db.ensure_user_database(user.id)
        db_path3 = master_db.ensure_user_database(user.id)
        
        # Should return same path
        assert db_path1 == db_path2 == db_path3
        
        # File should exist
        assert db_path1.exists()
    
    def test_ensure_for_nonexistent_user_fails(self, master_db):
        """Test that ensuring database for non-existent user fails"""
        with pytest.raises(UserNotFoundError):
            master_db.ensure_user_database(99999)
    
    def test_database_creation_verified(self, master_db, admin_user):
        """Test that database creation is verified before returning"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        db_path = master_db.ensure_user_database(user.id)
        
        # Should have verified existence
        assert db_path.exists()
        
        # Should be a valid SQLite database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        assert len(tables) > 0  # Has tables


class TestDatabaseFileLocation:
    """Test database file location and naming"""
    
    def test_database_in_users_directory(self, master_db, admin_user):
        """Test that user databases are created in users/ directory"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        db_path = master_db.ensure_user_database(user.id)
        
        assert db_path.parent == master_db.users_dir
    
    def test_database_filename_matches_user(self, master_db, admin_user):
        """Test that database filename matches user.database_filename"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        db_path = master_db.ensure_user_database(user.id)
        
        assert db_path.name == user.database_filename
    
    def test_database_filename_pattern(self, master_db, admin_user):
        """Test database filename follows pattern: user_###_username.db"""
        user = master_db.create_user(
            username="testuser",
            display_name="Test"
        )
        
        db_path = master_db.ensure_user_database(user.id)
        filename = db_path.name
        
        assert filename.startswith("user_")
        assert filename.endswith(".db")
        assert "testuser" in filename
        
        # Check number format (3 digits, zero-padded)
        parts = filename.replace(".db", "").split("_")
        assert len(parts) >= 3
        number_part = parts[1]
        assert number_part.isdigit()
        assert len(number_part) == 3
    
    def test_users_directory_created_automatically(self, temp_dir):
        """Test that users/ directory is created automatically"""
        # Create master DB in fresh temp dir
        master_db = MasterDatabase(data_dir=temp_dir, error_logger=None)
        
        assert master_db.users_dir.exists()
        assert master_db.users_dir.is_dir()
        
        master_db.close()
    
    def test_archive_directory_created_automatically(self, temp_dir):
        """Test that archive/ directory is created automatically"""
        master_db = MasterDatabase(data_dir=temp_dir, error_logger=None)
        
        assert master_db.archive_dir.exists()
        assert master_db.archive_dir.is_dir()
        
        master_db.close()


class TestDatabaseSchema:
    """Test that created databases have correct schema"""
    
    def test_database_has_phase1_tables(self, master_db, admin_user):
        """Test that created database has Phase 1 tables"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        db_path = master_db.ensure_user_database(user.id)
        
        # Connect and check tables
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        # Phase 1 tables (current schema)
        expected_tables = [
            'user_preferences',
            'subject_nodes',
            'question_analyses',
            'tags'
        ]
        
        for table in expected_tables:
            assert table in tables, f"Missing table: {table}"
    
    def test_user_preferences_table_structure(self, master_db, admin_user):
        """Test user_preferences table has correct structure"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        db_path = master_db.ensure_user_database(user.id)
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA table_info(user_preferences)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}  # name: type
        conn.close()
        
        # Check key columns exist (using current schema column names)
        assert 'id' in columns
        assert 'theme_name' in columns or 'theme' in columns  # Support both
        assert 'language_code' in columns or 'language' in columns
        assert 'default_session_duration_minutes' in columns
    
    @pytest.mark.skip(reason="exam_contexts table is created lazily in Phase 2")
    def test_exam_contexts_table_structure(self, master_db, admin_user):
        """Test exam_contexts table has correct structure"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        db_path = master_db.ensure_user_database(user.id)
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA table_info(exam_contexts)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        conn.close()
        
        assert 'id' in columns
        assert 'exam_name' in columns
        assert 'exam_source' in columns
        assert 'is_active' in columns
    
    def test_subject_nodes_table_structure(self, master_db, admin_user):
        """Test subject_nodes table has correct structure"""
        user = master_db.create_user(
            username="test",
            display_name="Test"
        )
        
        db_path = master_db.ensure_user_database(user.id)
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA table_info(subject_nodes)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        conn.close()
        
        # Check current schema columns
        assert 'id' in columns
        assert 'parent_id' in columns
        assert 'name' in columns
        assert 'level_type' in columns


class TestDatabaseFileSanitization:
    """Test filename sanitization for database files"""
    
    def test_spaces_removed_from_filename(self, master_db, admin_user):
        """Test that spaces in username don't appear in filename"""
        user = master_db.create_user(
            username="test_user",
            display_name="Test User With Spaces"
        )
        
        assert " " not in user.database_filename
    
    def test_filename_lowercase(self, master_db, admin_user):
        """Test that filename is lowercase"""
        user = master_db.create_user(
            username="TestUser",
            display_name="Test"
        )
        
        filename = user.database_filename
        assert filename == filename.lower()
    
    def test_filename_length_reasonable(self, master_db, admin_user):
        """Test that filename length is reasonable"""
        user = master_db.create_user(
            username="a" * 50,  # Long username
            display_name="Test"
        )
        
        # Filename should not be excessively long
        assert len(user.database_filename) < 100


class TestMultipleUserDatabases:
    """Test handling multiple user databases"""
    
    def test_multiple_users_get_separate_databases(self, master_db, admin_user):
        """Test that multiple users get separate database files"""
        users = []
        for i in range(3):
            user = master_db.create_user(
                username=f"user{i}",
                display_name=f"User {i}"
            )
            users.append(user)
        
        # Create all databases
        db_paths = [master_db.ensure_user_database(u.id) for u in users]
        
        # All should exist
        assert all(p.exists() for p in db_paths)
        
        # All should be unique
        assert len(set(db_paths)) == len(db_paths)
    
    def test_database_files_dont_interfere(self, master_db, admin_user):
        """Test that multiple user databases don't interfere with each other"""
        user1 = master_db.create_user(username="user1", display_name="User 1")
        user2 = master_db.create_user(username="user2", display_name="User 2")
        
        db1 = master_db.ensure_user_database(user1.id)
        db2 = master_db.ensure_user_database(user2.id)
        
        # Write to user1's database (using subject_nodes which exists in base schema)
        conn1 = sqlite3.connect(str(db1))
        conn1.execute("""
            INSERT INTO subject_nodes (exam_context, name, level_type, sort_order)
            VALUES ('Test Exam 1', 'Node 1', 'System', 1)
        """)
        conn1.commit()
        conn1.close()
        
        # Write to user2's database
        conn2 = sqlite3.connect(str(db2))
        conn2.execute("""
            INSERT INTO subject_nodes (exam_context, name, level_type, sort_order)
            VALUES ('Test Exam 2', 'Node 2', 'System', 1)
        """)
        conn2.commit()
        conn2.close()
        
        # Verify isolation - user1's DB has only their data
        conn1 = sqlite3.connect(str(db1))
        cursor1 = conn1.execute("SELECT name FROM subject_nodes")
        nodes1 = [row[0] for row in cursor1.fetchall()]
        conn1.close()
        
        # Verify isolation - user2's DB has only their data
        conn2 = sqlite3.connect(str(db2))
        cursor2 = conn2.execute("SELECT name FROM subject_nodes")
        nodes2 = [row[0] for row in cursor2.fetchall()]
        conn2.close()
        
        assert nodes1 == ['Node 1']
        assert nodes2 == ['Node 2']
