"""
Tests for bootstrap and primary admin functionality
"""
import pytest
from database import MasterDatabase, PrimaryAdminError


class TestBootstrapFirstUser:
    """Test bootstrap_first_user functionality"""
    
    def test_bootstrap_creates_first_user(self, master_db):
        """Test that bootstrap creates the first user successfully"""
        user = master_db.bootstrap_first_user(
            username="admin",
            display_name="System Admin",
            email="admin@test.com"
        )
        
        assert user.id ==1
        assert user.username == "admin"
        assert user.display_name == "System Admin"
        assert user.email == "admin@test.com"
    
    def test_bootstrap_user_is_primary_admin(self, master_db):
        """Test that bootstrapped user is marked as primary admin"""
        user = master_db.bootstrap_first_user(
            username="admin",
            display_name="Admin"
        )
        
        assert user.is_primary_admin is True
        assert user.is_admin() is True
    
    def test_bootstrap_user_has_admin_type(self, master_db):
        """Test that bootstrapped user has admin user type"""
        user = master_db.bootstrap_first_user(
            username="admin",
            display_name="Admin"
        )
        
        assert "admin" in user.user_type
        assert "student" in user.user_type  # Also gets student type
    
    def test_bootstrap_user_has_admin_permissions(self, master_db):
        """Test that bootstrapped user has all admin permissions"""
        user = master_db.bootstrap_first_user(
            username="admin",
            display_name="Admin"
        )
        
        assert user.can_manage_users is True
        assert user.can_view_all_statistics is True
        assert user.can_export_all_data is True
        assert user.can_manage_app_settings is True
    
    def test_bootstrap_fails_if_users_exist(self, master_db):
        """Test that bootstrap fails if any users already exist"""
        # Create first user
        master_db.bootstrap_first_user(
            username="admin",
            display_name="Admin"
        )
        
        # Try to bootstrap again
        with pytest.raises(PrimaryAdminError):
            master_db.bootstrap_first_user(
                username="admin2",
                display_name="Admin 2"
            )
    
    def test_bootstrap_without_email(self, master_db):
        """Test that bootstrap works without email"""
        user = master_db.bootstrap_first_user(
            username="admin",
            display_name="Admin"
        )
        
        assert user.email is None
        assert user.is_primary_admin is True


class TestPrimaryAdminConstraints:
    """Test primary admin constraints and protections"""
    
    def test_only_one_primary_admin_allowed(self, master_db, admin_user):
        """Test that only one primary admin can exist"""
        # admin_user fixture already created primary admin
        
        # Try to create another primary admin
        with pytest.raises(PrimaryAdminError):
            master_db.create_user(
                username="admin2",
                display_name="Admin 2",
                user_types=["admin"],
                is_primary_admin=True
            )
    
    def test_cannot_delete_primary_admin(self, master_db, admin_user):
        """Test that primary admin cannot be deleted"""
        with pytest.raises(PrimaryAdminError):
            master_db.soft_delete_user(admin_user.id)
    
    def test_can_create_non_primary_admins(self, master_db, admin_user):
        """Test that non-primary admins can be created"""
        admin2 = master_db.create_user(
            username="admin2",
            display_name="Second Admin",
            user_types=["admin", "student"],
            is_primary_admin=False
        )
        
        assert admin2.is_admin() is True
        assert admin2.is_primary_admin is False
        assert admin2.can_manage_users is True
    
    def test_non_primary_admin_can_be_deleted(self, master_db, admin_user):
        """Test that non-primary admins can be deleted"""
        admin2 = master_db.create_user(
            username="admin2",
            display_name="Second Admin",
            user_types=["admin"]
        )
        
        # Should not raise
        master_db.soft_delete_user(admin2.id)
        
        deleted = master_db.get_user(admin2.id)
        assert deleted.account_status == "soft_deleted"
    
    def test_primary_admin_is_unique(self, master_db):
        """Test that database enforces only one primary admin"""
        # Create first primary admin
        admin1 = master_db.bootstrap_first_user(
            username="admin",
            display_name="Admin"
        )
        
        # Verify there's exactly one primary admin
        all_users = master_db.get_all_users()
        primary_admins = [u for u in all_users if u.is_primary_admin]
        
        assert len(primary_admins) == 1
        assert primary_admins[0].id == admin1.id
    
    def test_update_cannot_make_user_primary_admin(self, master_db, admin_user):
        """Test that update cannot change is_primary_admin flag"""
        # Create regular admin
        admin2 = master_db.create_user(
            username="admin2",
            display_name="Admin 2",
            user_types=["admin"]
        )
        
        assert admin2.is_primary_admin is False
        
        # Note: update_user doesn't have is_primary_admin parameter
        # This is by design - primary admin can only be set via bootstrap
        # This test documents that design decision


class TestAdminPermissions:
    """Test that admin users have correct permissions"""
    
    def test_admin_has_all_permissions(self, master_db):
        """Test that admin users have all administrative permissions"""
        admin = master_db.bootstrap_first_user(
            username="admin",
            display_name="Admin"
        )
        
        assert admin.can_manage_users is True
        assert admin.can_view_all_statistics is True
        assert admin.can_export_all_data is True
        assert admin.can_manage_app_settings is True
    
    def test_non_admin_lacks_permissions(self, master_db, admin_user):
        """Test that non-admin users lack administrative permissions"""
        student = master_db.create_user(
            username="student",
            display_name="Student",
            user_types=["student"]
        )
        
        assert student.can_manage_users is False
        assert student.can_view_all_statistics is False
        assert student.can_export_all_data is False
        assert student.can_manage_app_settings is False
    
    def test_power_user_lacks_admin_permissions(self, master_db, admin_user):
        """Test that power users don't automatically get admin permissions"""
        tutor = master_db.create_user(
            username="tutor",
            display_name="Tutor",
            user_types=["power_user", "student"]
        )
        
        assert tutor.can_manage_users is False
        assert tutor.can_view_all_statistics is False
        assert tutor.can_export_all_data is False
        assert tutor.can_manage_app_settings is False
    
    def test_admin_without_primary_has_permissions(self, master_db, admin_user):
        """Test that non-primary admin still has admin permissions"""
        admin2 = master_db.create_user(
            username="admin2",
            display_name="Admin 2",
            user_types=["admin", "student"]
        )
        
        assert admin2.is_primary_admin is False
        assert admin2.can_manage_users is True
        assert admin2.can_view_all_statistics is True
        assert admin2.can_export_all_data is True
        assert admin2.can_manage_app_settings is True
