"""
Tests for app settings functionality
"""
import pytest
import json
from database import MasterDatabase, AppSetting


class TestAppSettingsCRUD:
    """Test basic CRUD operations for app settings"""
    
    def test_set_string_setting(self, master_db):
        """Test setting a string value"""
        setting = master_db.set_setting(
            setting_key="app_name",
            setting_value="WIMI App",
            setting_type="string",
            description="Application name"
        )
        
        assert setting.setting_key == "app_name"
        assert setting.setting_value == "WIMI App"
        assert setting.setting_type == "string"
    
    def test_get_existing_setting(self, master_db):
        """Test retrieving an existing setting"""
        master_db.set_setting(
            setting_key="test_key",
            setting_value="test_value",
            setting_type="string"
        )
        
        retrieved = master_db.get_setting("test_key")
        
        assert retrieved is not None
        assert retrieved.setting_key == "test_key"
    
    def test_get_nonexistent_setting_returns_none(self, master_db):
        """Test that getting non-existent setting returns None"""
        setting = master_db.get_setting("nonexistent_key")
        assert setting is None


class TestSettingTypeConversion:
    """Test type conversion for different setting types"""
    
    def test_integer_type_conversion(self, master_db):
        """Test getting typed value for integer setting"""
        setting = master_db.set_setting(
            setting_key="count",
            setting_value="42",
            setting_type="integer"
        )
        
        value = setting.get_typed_value()
        assert isinstance(value, int)
        assert value == 42
    
    def test_boolean_type_conversion(self, master_db):
        """Test getting typed value for boolean setting"""
        setting = master_db.set_setting(
            setting_key="enabled",
            setting_value="true",
            setting_type="boolean"
        )
        
        value = setting.get_typed_value()
        assert isinstance(value, bool)
        assert value is True
