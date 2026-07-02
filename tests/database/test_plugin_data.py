"""Tests for PluginDataMixin — plugin key-value storage."""

import pytest
from pathlib import Path
from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    """Create a temporary UserDatabase with plugin_data table."""
    db_path = tmp_path / "test_user.db"
    user_db = UserDatabase(
        db_path=db_path,
        user_id=1,
        username="test_user"
    )
    yield user_db
    user_db.close()


class TestPluginDataMixin:
    """Tests for plugin data CRUD operations."""

    def test_set_and_get_string(self, db):
        db.set_plugin_data("my-plugin", "greeting", "hello")
        assert db.get_plugin_data("my-plugin", "greeting") == "hello"

    def test_set_and_get_number(self, db):
        db.set_plugin_data("my-plugin", "count", 42)
        assert db.get_plugin_data("my-plugin", "count") == 42

    def test_set_and_get_dict(self, db):
        data = {"key": "value", "nested": [1, 2, 3]}
        db.set_plugin_data("my-plugin", "config", data)
        assert db.get_plugin_data("my-plugin", "config") == data

    def test_set_and_get_bool(self, db):
        db.set_plugin_data("my-plugin", "flag", True)
        assert db.get_plugin_data("my-plugin", "flag") is True

    def test_set_and_get_null(self, db):
        db.set_plugin_data("my-plugin", "empty", None)
        assert db.get_plugin_data("my-plugin", "empty") is None

    def test_get_nonexistent_key(self, db):
        assert db.get_plugin_data("my-plugin", "nonexistent") is None

    def test_upsert_overwrites(self, db):
        db.set_plugin_data("my-plugin", "key", "first")
        db.set_plugin_data("my-plugin", "key", "second")
        assert db.get_plugin_data("my-plugin", "key") == "second"

    def test_get_all_plugin_data(self, db):
        db.set_plugin_data("my-plugin", "a", 1)
        db.set_plugin_data("my-plugin", "b", "two")
        db.set_plugin_data("other-plugin", "c", 3)

        data = db.get_all_plugin_data("my-plugin")
        assert data == {"a": 1, "b": "two"}

    def test_get_all_empty(self, db):
        assert db.get_all_plugin_data("nonexistent") == {}

    def test_delete_plugin_data(self, db):
        db.set_plugin_data("my-plugin", "key", "value")
        assert db.delete_plugin_data("my-plugin", "key") is True
        assert db.get_plugin_data("my-plugin", "key") is None

    def test_delete_nonexistent(self, db):
        assert db.delete_plugin_data("my-plugin", "nope") is False

    def test_clear_plugin_data(self, db):
        db.set_plugin_data("my-plugin", "a", 1)
        db.set_plugin_data("my-plugin", "b", 2)
        db.set_plugin_data("other-plugin", "c", 3)

        count = db.clear_plugin_data("my-plugin")
        assert count == 2
        assert db.get_all_plugin_data("my-plugin") == {}
        # Other plugin data untouched
        assert db.get_plugin_data("other-plugin", "c") == 3

    def test_clear_empty(self, db):
        assert db.clear_plugin_data("nonexistent") == 0

    def test_plugin_isolation(self, db):
        """Different plugins don't see each other's data."""
        db.set_plugin_data("plugin-a", "key", "a-value")
        db.set_plugin_data("plugin-b", "key", "b-value")
        assert db.get_plugin_data("plugin-a", "key") == "a-value"
        assert db.get_plugin_data("plugin-b", "key") == "b-value"


class TestPluginEnabled:
    """Tests for plugin enabled/disabled state."""

    def test_default_enabled(self, db):
        """Plugins are enabled by default."""
        assert db.get_plugin_enabled("new-plugin") is True

    def test_disable_plugin(self, db):
        db.set_plugin_enabled("my-plugin", False)
        assert db.get_plugin_enabled("my-plugin") is False

    def test_enable_plugin(self, db):
        db.set_plugin_enabled("my-plugin", False)
        db.set_plugin_enabled("my-plugin", True)
        assert db.get_plugin_enabled("my-plugin") is True


class TestPluginSettings:
    """Tests for plugin settings JSON blob storage."""

    def test_empty_settings(self, db):
        assert db.get_plugin_settings("my-plugin") == {}

    def test_set_and_get_settings(self, db):
        settings = {"theme": "dark", "limit": 10, "enabled": True}
        db.set_plugin_settings("my-plugin", settings)
        assert db.get_plugin_settings("my-plugin") == settings

    def test_settings_roundtrip(self, db):
        """Settings survive write then read."""
        original = {"nested": {"a": [1, 2]}, "flag": False}
        db.set_plugin_settings("my-plugin", original)
        loaded = db.get_plugin_settings("my-plugin")
        assert loaded == original

    def test_settings_overwrite(self, db):
        db.set_plugin_settings("my-plugin", {"v": 1})
        db.set_plugin_settings("my-plugin", {"v": 2, "new": "field"})
        assert db.get_plugin_settings("my-plugin") == {"v": 2, "new": "field"}
