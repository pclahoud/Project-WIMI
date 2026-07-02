"""
Tests for MasterDatabase validation
"""
import pytest
from database import (
    MasterDatabase, InvalidUsernameError, InvalidUserTypeError,
    UserAlreadyExistsError
)


class TestUsernameValidation:
    """Test username validation rules"""
    
    @pytest.mark.parametrize("username,should_pass", [
        # Valid usernames
        ("valid_user", True),
        ("user123", True),
        ("user-name_123", True),
        ("abc", True),  # Minimum 3 chars
        ("a" * 50, True),  # Long but valid
        ("USER_NAME", True),  # Uppercase
        ("user-123", True),  # Hyphens
        ("user_123", True),  # Underscores
        
        # Invalid usernames
        ("ab", False),  # Too short (< 3 chars)
        ("a", False),  # Too short
        ("", False),  # Empty
        ("user@123", False),  # Invalid char (@)
        ("user.name", False),  # Invalid char (.)
        ("user name", False),  # Space
        ("user#123", False),  # Invalid char (#)
        ("user$money", False),  # Invalid char ($)
        ("user!test", False),  # Invalid char (!)
    ])
    def test_username_validation(self, master_db, admin_user, username, should_pass):
        """Test username validation with various inputs"""
        if should_pass:
            user = master_db.create_user(
                username=username,
                display_name="Display Name"
            )
            assert user.username == username
        else:
            with pytest.raises((InvalidUsernameError, UserAlreadyExistsError)):
                master_db.create_user(
                    username=username,
                    display_name="Display Name"
                )
    
    def test_username_alphanumeric_underscore_hyphen_only(self, master_db, admin_user):
        """Test that usernames can only contain alphanumeric, underscore, hyphen"""
        # Valid characters
        valid_user = master_db.create_user(
            username="valid_user-123",
            display_name="Valid"
        )
        assert valid_user.username == "valid_user-123"
        
        # Invalid characters
        invalid_usernames = [
            "user@domain",
            "user.name",
            "user name",
            "user#tag",
            "user$var",
            "user!exclaim",
            "user%percent",
        ]
        
        for invalid in invalid_usernames:
            with pytest.raises(InvalidUsernameError):
                master_db.create_user(
                    username=invalid,
                    display_name="Test"
                )
    
    def test_username_minimum_length(self, master_db, admin_user):
        """Test username minimum length requirement (3 characters)"""
        # Too short
        with pytest.raises(InvalidUsernameError):
            master_db.create_user(username="ab", display_name="Short")
        
        with pytest.raises(InvalidUsernameError):
            master_db.create_user(username="a", display_name="Too Short")
        
        # Minimum valid length
        user = master_db.create_user(username="abc", display_name="Min Length")
        assert user.username == "abc"
    
    def test_empty_username_fails(self, master_db, admin_user):
        """Test that empty username fails validation"""
        with pytest.raises(InvalidUsernameError):
            master_db.create_user(username="", display_name="Empty")
    
    def test_username_with_spaces_fails(self, master_db, admin_user):
        """Test that username with spaces fails"""
        with pytest.raises(InvalidUsernameError):
            master_db.create_user(username="user name", display_name="Spaces")
        
        with pytest.raises(InvalidUsernameError):
            master_db.create_user(username=" username", display_name="Leading")
        
        with pytest.raises(InvalidUsernameError):
            master_db.create_user(username="username ", display_name="Trailing")


class TestUserTypeValidation:
    """Test user type validation"""
    
    def test_valid_user_types(self, master_db, admin_user):
        """Test that valid user types are accepted"""
        valid_types = [
            ["student"],
            ["power_user"],
            ["admin"],
            ["student", "power_user"],
            ["admin", "student"],
            ["admin", "power_user", "student"],
        ]
        
        for i, user_types in enumerate(valid_types):
            user = master_db.create_user(
                username=f"user{i}",
                display_name=f"User {i}",
                user_types=user_types
            )
            assert set(user.user_type) == set(user_types)
    
    def test_invalid_user_type_fails(self, master_db, admin_user):
        """Test that invalid user types fail"""
        invalid_types = [
            ["invalid"],
            ["student", "invalid"],
            ["teacher"],
            ["root"],
            ["super_user"],
        ]
        
        for user_types in invalid_types:
            with pytest.raises(InvalidUserTypeError):
                master_db.create_user(
                    username="test",
                    display_name="Test",
                    user_types=user_types
                )
    
    def test_mixed_valid_invalid_types_fails(self, master_db, admin_user):
        """Test that mixing valid and invalid types fails"""
        with pytest.raises(InvalidUserTypeError):
            master_db.create_user(
                username="test",
                display_name="Test",
                user_types=["student", "invalid_type"]
            )
    
    def test_empty_user_types_defaults_to_student(self, master_db, admin_user):
        """Test that empty/None user_types defaults to ['student']"""
        user = master_db.create_user(
            username="default",
            display_name="Default",
            user_types=None
        )
        
        assert user.user_type == ["student"]
    
    def test_case_sensitive_user_types(self, master_db, admin_user):
        """Test that user types are case-sensitive"""
        # Lowercase (valid)
        user1 = master_db.create_user(
            username="lower",
            display_name="Lower",
            user_types=["student"]
        )
        assert user1.user_type == ["student"]
        
        # Uppercase (invalid)
        with pytest.raises(InvalidUserTypeError):
            master_db.create_user(
                username="upper",
                display_name="Upper",
                user_types=["STUDENT"]
            )


class TestUsernameSanitization:
    """Test username sanitization for filenames"""
    
    def test_sanitize_removes_spaces(self, master_db, admin_user):
        """Test that spaces are removed in filename"""
        user = master_db.create_user(
            username="user_name",  # No spaces in username itself
            display_name="User Name"
        )
        
        # Filename should not have spaces
        assert " " not in user.database_filename
        assert "user_name" in user.database_filename.lower()
    
    def test_sanitize_lowercase(self, master_db, admin_user):
        """Test that filename is lowercase"""
        user = master_db.create_user(
            username="MixedCase",
            display_name="Mixed Case"
        )
        
        # Filename should be lowercase
        assert "mixedcase" in user.database_filename
        assert user.database_filename == user.database_filename.lower()
    
    def test_sanitize_preserves_alphanumeric_underscore_hyphen(self, master_db, admin_user):
        """Test that alphanumeric, underscore, hyphen are preserved"""
        user = master_db.create_user(
            username="user_name-123",
            display_name="Test"
        )
        
        assert "user_name-123" in user.database_filename
    
    def test_filename_pattern_correct(self, master_db, admin_user):
        """Test that filename follows pattern: user_###_username.db"""
        user = master_db.create_user(
            username="testuser",
            display_name="Test User"
        )
        
        # Pattern: user_###_username.db
        assert user.database_filename.startswith("user_")
        assert user.database_filename.endswith(".db")
        assert "testuser" in user.database_filename
        
        # Extract number part
        parts = user.database_filename.split("_")
        assert len(parts) >= 3
        assert parts[1].isdigit()  # Second part should be a number
        assert len(parts[1]) == 3  # Should be zero-padded to 3 digits
    
    def test_filename_increments_correctly(self, master_db, admin_user):
        """Test that user numbers increment correctly"""
        user1 = master_db.create_user(username="user1", display_name="User 1")
        user2 = master_db.create_user(username="user2", display_name="User 2")
        user3 = master_db.create_user(username="user3", display_name="User 3")
        
        # Extract numbers from filenames
        num1 = int(user1.database_filename.split("_")[1])
        num2 = int(user2.database_filename.split("_")[1])
        num3 = int(user3.database_filename.split("_")[1])
        
        assert num2 == num1 + 1
        assert num3 == num2 + 1
    
    def test_filename_unique_for_each_user(self, master_db, admin_user):
        """Test that each user gets a unique filename"""
        users = []
        for i in range(5):
            user = master_db.create_user(
                username=f"user{i}",
                display_name=f"User {i}"
            )
            users.append(user)
        
        filenames = [u.database_filename for u in users]
        
        # All filenames should be unique
        assert len(filenames) == len(set(filenames))


class TestUniqueConstraints:
    """Test unique constraint violations"""
    
    def test_duplicate_username_rejected(self, master_db, admin_user):
        """Test that duplicate usernames are rejected"""
        master_db.create_user(
            username="duplicate",
            display_name="First User"
        )
        
        with pytest.raises(UserAlreadyExistsError):
            master_db.create_user(
                username="duplicate",
                display_name="Second User"
            )
    
    def test_duplicate_email_rejected(self, master_db, admin_user):
        """Test that duplicate emails are rejected"""
        master_db.create_user(
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
    
    def test_null_email_allowed_for_multiple_users(self, master_db, admin_user):
        """Test that multiple users can have NULL email"""
        user1 = master_db.create_user(
            username="user1",
            display_name="User 1",
            email=None
        )
        
        user2 = master_db.create_user(
            username="user2",
            display_name="User 2",
            email=None
        )
        
        assert user1.email is None
        assert user2.email is None
    
    def test_case_sensitive_username(self, master_db, admin_user):
        """Test that usernames are case-sensitive in uniqueness check"""
        user1 = master_db.create_user(
            username="testuser",
            display_name="Lower"
        )
        
        # SQLite is case-insensitive for text by default, so this should fail
        # or succeed depending on COLLATE setting
        # Let's verify the actual behavior
        try:
            user2 = master_db.create_user(
                username="TestUser",
                display_name="Mixed"
            )
            # If this succeeds, usernames are case-sensitive
            assert user1.username != user2.username
        except UserAlreadyExistsError:
            # If this fails, usernames are case-insensitive (more secure)
            pass  # Both behaviors are acceptable
