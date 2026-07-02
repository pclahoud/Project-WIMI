"""Tests for PluginAPI — scoped facade for plugin database access."""

import pytest
from pathlib import Path

from app.plugin_api import PluginAPI
from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    """Create a temporary UserDatabase with full schema."""
    db_path = tmp_path / "test_user.db"
    user_db = UserDatabase(
        db_path=db_path,
        user_id=1,
        username="test_user"
    )
    # Ensure full schema for read method tests
    user_db._ensure_phase2_schema()
    user_db._ensure_phase4_schema()
    user_db._ensure_phase7_schema()
    yield user_db
    user_db.close()


@pytest.fixture
def plugin_dir(tmp_path):
    """Create a temporary plugin directory."""
    pdir = tmp_path / "plugins" / "test-plugin"
    pdir.mkdir(parents=True)
    return pdir


@pytest.fixture
def read_api(db):
    """PluginAPI with read-only permissions."""
    return PluginAPI("test-plugin", db, ["read"])


@pytest.fixture
def write_api(db):
    """PluginAPI with full write permissions."""
    return PluginAPI("test-plugin", db, [
        "read", "write:entries", "write:sessions", "write:notes", "write:goals"
    ])


@pytest.fixture
def storage_api(db, plugin_dir):
    """PluginAPI with storage permission and a plugin directory."""
    return PluginAPI("test-plugin", db, ["read", "storage"], plugin_dir)


class TestReadMethods:
    """Read methods should always work regardless of permissions."""

    def test_get_entry_nonexistent(self, read_api):
        result = read_api.get_entry(99999)
        assert result is None

    def test_get_sessions_empty(self, read_api):
        result = read_api.get_sessions()
        assert isinstance(result, list)

    def test_get_session_nonexistent(self, read_api):
        result = read_api.get_session(99999)
        assert result is None

    def test_get_exams_empty(self, read_api):
        result = read_api.get_exams()
        assert isinstance(result, list)

    def test_get_exam_nonexistent(self, read_api):
        result = read_api.get_exam(99999)
        assert result is None

    def test_get_overview(self, read_api):
        result = read_api.get_overview()
        assert isinstance(result, dict)

    def test_get_streak(self, read_api):
        result = read_api.get_streak()
        assert isinstance(result, dict)

    def test_get_sources_empty(self, read_api):
        result = read_api.get_sources()
        assert isinstance(result, list)

    def test_search_entries_empty(self, read_api):
        result = read_api.search_entries("test query")
        assert isinstance(result, list)

    def test_get_entry_notes_empty(self, read_api):
        result = read_api.get_entry_notes(99999)
        assert isinstance(result, list)

    def test_get_entry_media_empty(self, read_api):
        result = read_api.get_entry_media(99999)
        assert isinstance(result, list)


class TestWritePermissions:
    """Write methods should require appropriate permissions."""

    def test_create_entry_without_permission(self, read_api):
        with pytest.raises(PermissionError, match="write:entries"):
            read_api.create_entry({"review_session_id": 1})

    def test_update_entry_without_permission(self, read_api):
        with pytest.raises(PermissionError, match="write:entries"):
            read_api.update_entry(1, {"user_answer": "new"})

    def test_create_session_without_permission(self, read_api):
        with pytest.raises(PermissionError, match="write:sessions"):
            read_api.create_session({"exam_context_id": 1})

    def test_add_note_without_permission(self, read_api):
        with pytest.raises(PermissionError, match="write:notes"):
            read_api.add_note(1, {"content_html": "<p>test</p>"})

    def test_update_note_without_permission(self, read_api):
        with pytest.raises(PermissionError, match="write:notes"):
            read_api.update_note(1, {"content_html": "<p>updated</p>"})

    def test_create_goal_without_permission(self, read_api):
        with pytest.raises(PermissionError, match="write:goals"):
            read_api.create_goal(10)


class TestPluginPrivateStorage:
    """Plugin-private key-value storage."""

    def test_set_and_get_data(self, read_api):
        read_api.set_data("counter", 42)
        assert read_api.get_data("counter") == 42

    def test_get_nonexistent_data(self, read_api):
        assert read_api.get_data("nope") is None

    def test_complex_data(self, read_api):
        data = {"list": [1, 2, 3], "nested": {"a": True}}
        read_api.set_data("complex", data)
        assert read_api.get_data("complex") == data

    def test_get_settings_empty(self, read_api):
        assert read_api.get_settings() == {}

    def test_plugin_data_isolation(self, db):
        """Two plugins don't share private storage."""
        api_a = PluginAPI("plugin-a", db, ["read"])
        api_b = PluginAPI("plugin-b", db, ["read"])

        api_a.set_data("key", "a-value")
        api_b.set_data("key", "b-value")

        assert api_a.get_data("key") == "a-value"
        assert api_b.get_data("key") == "b-value"


class TestFileStorage:
    """File storage within the plugin's data/ directory."""

    def test_write_and_read_text(self, storage_api):
        storage_api.write_file("hello.txt", "Hello, World!")
        assert storage_api.read_file("hello.txt") == "Hello, World!"

    def test_write_and_read_binary(self, storage_api):
        data = b"\x00\x01\x02\xff"
        storage_api.write_file("binary.bin", data)
        assert storage_api.read_file("binary.bin", binary=True) == data

    def test_read_nonexistent_returns_none(self, storage_api):
        assert storage_api.read_file("does-not-exist.txt") is None

    def test_write_creates_parent_dirs(self, storage_api):
        storage_api.write_file("a/b/c/deep.txt", "nested")
        assert storage_api.read_file("a/b/c/deep.txt") == "nested"

    def test_delete_file(self, storage_api):
        storage_api.write_file("to-delete.txt", "bye")
        assert storage_api.delete_file("to-delete.txt") is True
        assert storage_api.read_file("to-delete.txt") is None

    def test_delete_nonexistent_returns_false(self, storage_api):
        assert storage_api.delete_file("nope.txt") is False

    def test_list_files_empty(self, storage_api):
        assert storage_api.list_files() == []

    def test_list_files(self, storage_api):
        storage_api.write_file("a.txt", "a")
        storage_api.write_file("sub/b.txt", "b")
        files = storage_api.list_files()
        assert "a.txt" in files
        assert "sub/b.txt" in files

    def test_list_files_subdir(self, storage_api):
        storage_api.write_file("reports/jan.txt", "jan")
        storage_api.write_file("reports/feb.txt", "feb")
        storage_api.write_file("other.txt", "x")
        files = storage_api.list_files("reports")
        assert "reports/jan.txt" in files
        assert "reports/feb.txt" in files
        assert "other.txt" not in files

    def test_file_exists(self, storage_api):
        assert storage_api.file_exists("nope.txt") is False
        storage_api.write_file("exists.txt", "yes")
        assert storage_api.file_exists("exists.txt") is True

    def test_overwrite_file(self, storage_api):
        storage_api.write_file("file.txt", "original")
        storage_api.write_file("file.txt", "updated")
        assert storage_api.read_file("file.txt") == "updated"

    def test_write_returns_byte_count(self, storage_api):
        n = storage_api.write_file("test.txt", "hello")
        assert n == 5

    def test_write_returns_byte_count_unicode(self, storage_api):
        n = storage_api.write_file("emoji.txt", "\u00e9\u00e0\u00fc")
        assert n == len("\u00e9\u00e0\u00fc".encode('utf-8'))


class TestFileStorageSecurity:
    """Security checks for file storage."""

    def test_requires_storage_permission(self, read_api):
        with pytest.raises(PermissionError, match="storage"):
            read_api.read_file("test.txt")

    def test_requires_storage_for_write(self, read_api):
        with pytest.raises(PermissionError, match="storage"):
            read_api.write_file("test.txt", "data")

    def test_requires_storage_for_delete(self, read_api):
        with pytest.raises(PermissionError, match="storage"):
            read_api.delete_file("test.txt")

    def test_requires_storage_for_list(self, read_api):
        with pytest.raises(PermissionError, match="storage"):
            read_api.list_files()

    def test_requires_storage_for_exists(self, read_api):
        with pytest.raises(PermissionError, match="storage"):
            read_api.file_exists("test.txt")

    def test_path_traversal_blocked(self, storage_api):
        with pytest.raises(PermissionError, match="escapes storage"):
            storage_api.read_file("../../etc/passwd")

    def test_path_traversal_blocked_write(self, storage_api):
        with pytest.raises(PermissionError, match="escapes storage"):
            storage_api.write_file("../../../evil.txt", "pwned")

    def test_path_traversal_nested(self, storage_api):
        with pytest.raises(PermissionError, match="escapes storage"):
            storage_api.read_file("sub/../../outside.txt")

    def test_absolute_path_blocked(self, storage_api):
        with pytest.raises((PermissionError, ValueError)):
            storage_api.read_file("/etc/passwd")

    def test_empty_path_rejected(self, storage_api):
        with pytest.raises(ValueError, match="empty"):
            storage_api.read_file("")

    def test_whitespace_path_rejected(self, storage_api):
        with pytest.raises(ValueError, match="empty"):
            storage_api.read_file("   ")

    def test_no_plugin_dir_raises_runtime_error(self, db):
        api = PluginAPI("no-dir", db, ["read", "storage"], plugin_dir=None)
        with pytest.raises(RuntimeError, match="no directory"):
            api.read_file("test.txt")

    def test_files_scoped_to_data_subdir(self, storage_api, plugin_dir):
        """Files are written inside data/ not plugin root."""
        storage_api.write_file("test.txt", "content")
        assert (plugin_dir / "data" / "test.txt").exists()
        assert not (plugin_dir / "test.txt").exists()
