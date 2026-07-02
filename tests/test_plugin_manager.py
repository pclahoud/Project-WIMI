"""Tests for PluginManager — discovery, loading, lifecycle."""

import json
import zipfile
import pytest
from pathlib import Path

from app.plugin_manager import PluginManager
from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    """Create a temporary UserDatabase."""
    db_path = tmp_path / "test_user.db"
    user_db = UserDatabase(
        db_path=db_path,
        user_id=1,
        username="test_user"
    )
    yield user_db
    user_db.close()


@pytest.fixture
def plugins_dir(tmp_path):
    """Create a temporary plugins directory."""
    d = tmp_path / "plugins"
    d.mkdir()
    return d


def create_plugin_dir(plugins_dir, plugin_id, manifest_data, backend_code=None):
    """Helper to create a plugin directory with manifest and optional backend."""
    plugin_dir = plugins_dir / plugin_id
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest_data))
    if backend_code:
        (plugin_dir / "backend.py").write_text(backend_code)
    return plugin_dir


@pytest.fixture
def valid_manifest():
    return {
        "id": "test-plugin",
        "name": "Test Plugin",
        "version": "1.0.0",
        "description": "A test plugin",
        "permissions": ["read"],
        "settings": [
            {"key": "greeting", "type": "text", "label": "Greeting", "default": "Hello"}
        ]
    }


class TestDiscovery:
    """Tests for plugin discovery."""

    def test_empty_directory(self, plugins_dir, db):
        pm = PluginManager(plugins_dir, db)
        manifests = pm.discover_plugins()
        assert manifests == []

    def test_nonexistent_directory(self, tmp_path, db):
        pm = PluginManager(tmp_path / "nonexistent", db)
        manifests = pm.discover_plugins()
        assert manifests == []

    def test_discover_valid_plugin(self, plugins_dir, db, valid_manifest):
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest)
        pm = PluginManager(plugins_dir, db)
        manifests = pm.discover_plugins()
        assert len(manifests) == 1
        assert manifests[0].id == "test-plugin"

    def test_skip_invalid_manifest(self, plugins_dir, db):
        """Invalid manifests are skipped, not cause errors."""
        create_plugin_dir(plugins_dir, "bad-plugin", {"id": "bad plugin!"})
        pm = PluginManager(plugins_dir, db)
        manifests = pm.discover_plugins()
        assert len(manifests) == 0

    def test_skip_dirs_without_manifest(self, plugins_dir, db):
        (plugins_dir / "no-manifest").mkdir()
        pm = PluginManager(plugins_dir, db)
        manifests = pm.discover_plugins()
        assert len(manifests) == 0

    def test_multiple_plugins(self, plugins_dir, db):
        create_plugin_dir(plugins_dir, "plugin-a", {
            "id": "plugin-a", "name": "A", "version": "1.0.0"
        })
        create_plugin_dir(plugins_dir, "plugin-b", {
            "id": "plugin-b", "name": "B", "version": "2.0.0"
        })
        pm = PluginManager(plugins_dir, db)
        manifests = pm.discover_plugins()
        assert len(manifests) == 2


class TestLoading:
    """Tests for plugin loading."""

    def test_load_frontend_only_plugin(self, plugins_dir, db, valid_manifest):
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest)
        pm = PluginManager(plugins_dir, db)
        pm.discover_plugins()
        assert pm.load_plugin("test-plugin") is True

    def test_load_backend_plugin(self, plugins_dir, db, valid_manifest):
        valid_manifest['backend'] = 'backend.py'
        backend_code = '''
class MyPlugin:
    def __init__(self, api):
        self.api = api
    def hello(self):
        return "world"

def create_plugin(api):
    return MyPlugin(api)
'''
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest, backend_code)
        pm = PluginManager(plugins_dir, db)
        pm.discover_plugins()
        assert pm.load_plugin("test-plugin") is True

        # Backend instance should be in registry
        registry = pm.get_plugin_registry()
        assert "test-plugin" in registry
        assert registry["test-plugin"].hello() == "world"

    def test_load_nonexistent_plugin(self, plugins_dir, db):
        pm = PluginManager(plugins_dir, db)
        assert pm.load_plugin("nonexistent") is False

    def test_disabled_plugin_not_loaded(self, plugins_dir, db, valid_manifest):
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest)
        db.set_plugin_enabled("test-plugin", False)

        pm = PluginManager(plugins_dir, db)
        pm.discover_plugins()
        assert pm.load_plugin("test-plugin") is False

    def test_load_all(self, plugins_dir, db):
        create_plugin_dir(plugins_dir, "plugin-a", {
            "id": "plugin-a", "name": "A", "version": "1.0.0"
        })
        create_plugin_dir(plugins_dir, "plugin-b", {
            "id": "plugin-b", "name": "B", "version": "1.0.0"
        })
        pm = PluginManager(plugins_dir, db)
        results = pm.load_all()
        assert results == {"plugin-a": True, "plugin-b": True}

    def test_backend_missing_create_plugin(self, plugins_dir, db, valid_manifest):
        valid_manifest['backend'] = 'backend.py'
        backend_code = 'x = 1\n'
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest, backend_code)
        pm = PluginManager(plugins_dir, db)
        pm.discover_plugins()
        assert pm.load_plugin("test-plugin") is False


class TestLifecycle:
    """Tests for enable/disable and unload."""

    def test_set_plugin_enabled(self, plugins_dir, db, valid_manifest):
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest)
        pm = PluginManager(plugins_dir, db)
        pm.load_all()

        pm.set_plugin_enabled("test-plugin", False)
        assert db.get_plugin_enabled("test-plugin") is False

    def test_unload_plugin(self, plugins_dir, db, valid_manifest):
        valid_manifest['backend'] = 'backend.py'
        backend_code = 'def create_plugin(api): return type("P", (), {"on_unload": lambda self: None})()\n'
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest, backend_code)
        pm = PluginManager(plugins_dir, db)
        pm.load_all()

        assert pm.unload_plugin("test-plugin") is True
        assert "test-plugin" not in pm.get_plugin_registry()


class TestInstalledPlugins:
    """Tests for get_installed_plugins."""

    def test_returns_frontend_dict(self, plugins_dir, db, valid_manifest):
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest)
        pm = PluginManager(plugins_dir, db)
        pm.load_all()

        plugins = pm.get_installed_plugins()
        assert len(plugins) == 1
        p = plugins[0]
        assert p['id'] == 'test-plugin'
        assert p['name'] == 'Test Plugin'
        assert p['enabled'] is True
        assert 'settings' in p


class TestPluginSettings:
    """Tests for plugin settings management."""

    def test_settings_with_defaults(self, plugins_dir, db, valid_manifest):
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest)
        pm = PluginManager(plugins_dir, db)
        pm.discover_plugins()

        settings = pm.get_plugin_settings("test-plugin")
        assert settings == {"greeting": "Hello"}

    def test_update_settings(self, plugins_dir, db, valid_manifest):
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest)
        pm = PluginManager(plugins_dir, db)
        pm.discover_plugins()

        merged = pm.update_plugin_settings("test-plugin", {"greeting": "Hi"})
        assert merged == {"greeting": "Hi"}

    def test_settings_merge_defaults(self, plugins_dir, db, valid_manifest):
        """Saved settings override defaults, missing keys use defaults."""
        valid_manifest['settings'].append(
            {"key": "color", "type": "text", "label": "Color", "default": "blue"}
        )
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest)
        pm = PluginManager(plugins_dir, db)
        pm.discover_plugins()

        pm.update_plugin_settings("test-plugin", {"greeting": "Hey"})
        settings = pm.get_plugin_settings("test-plugin")
        assert settings == {"greeting": "Hey", "color": "blue"}


def create_plugin_zip(tmp_path, manifest_data, nested=False, extra_files=None):
    """Helper to create a .zip file containing a plugin."""
    zip_path = tmp_path / "plugin.zip"
    with zipfile.ZipFile(str(zip_path), 'w') as zf:
        prefix = manifest_data['id'] + '/' if nested else ''
        zf.writestr(prefix + 'manifest.json', json.dumps(manifest_data))
        if extra_files:
            for name, content in extra_files.items():
                zf.writestr(prefix + name, content)
    return zip_path


class TestInstallUninstall:
    """Tests for plugin install from zip and uninstall."""

    def test_install_from_zip_root_manifest(self, tmp_path, plugins_dir, db, valid_manifest):
        zip_path = create_plugin_zip(tmp_path, valid_manifest, nested=False)
        pm = PluginManager(plugins_dir, db)
        result = pm.install_plugin(str(zip_path))

        assert result['plugin_id'] == 'test-plugin'
        assert result['name'] == 'Test Plugin'
        assert result['version'] == '1.0.0'
        assert result['replaced'] is False
        assert (plugins_dir / 'test-plugin' / 'manifest.json').exists()

    def test_install_from_zip_nested_manifest(self, tmp_path, plugins_dir, db, valid_manifest):
        zip_path = create_plugin_zip(tmp_path, valid_manifest, nested=True)
        pm = PluginManager(plugins_dir, db)
        result = pm.install_plugin(str(zip_path))

        assert result['plugin_id'] == 'test-plugin'
        assert (plugins_dir / 'test-plugin' / 'manifest.json').exists()

    def test_install_replaces_existing(self, tmp_path, plugins_dir, db, valid_manifest):
        # Install first version
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest)
        pm = PluginManager(plugins_dir, db)
        pm.discover_plugins()

        # Install replacement via zip
        valid_manifest['version'] = '2.0.0'
        zip_path = create_plugin_zip(tmp_path, valid_manifest)
        result = pm.install_plugin(str(zip_path))

        assert result['replaced'] is True
        assert result['version'] == '2.0.0'

    def test_install_invalid_zip(self, tmp_path, plugins_dir, db):
        bad_file = tmp_path / "not_a_zip.zip"
        bad_file.write_text("this is not a zip")
        pm = PluginManager(plugins_dir, db)

        with pytest.raises(ValueError, match="Not a valid zip"):
            pm.install_plugin(str(bad_file))

    def test_install_no_manifest(self, tmp_path, plugins_dir, db):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr("readme.txt", "no manifest here")
        pm = PluginManager(plugins_dir, db)

        with pytest.raises(ValueError, match="does not contain a manifest"):
            pm.install_plugin(str(zip_path))

    def test_install_path_traversal_rejected(self, tmp_path, plugins_dir, db):
        zip_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr("../../../etc/passwd", "evil content")
        pm = PluginManager(plugins_dir, db)

        with pytest.raises(ValueError, match="path traversal"):
            pm.install_plugin(str(zip_path))

    def test_install_invalid_manifest_in_zip(self, tmp_path, plugins_dir, db):
        bad_manifest = {"id": "bad plugin!", "name": "", "version": "nope"}
        zip_path = tmp_path / "bad.zip"
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr("manifest.json", json.dumps(bad_manifest))
        pm = PluginManager(plugins_dir, db)

        with pytest.raises(ValueError, match="Invalid manifest"):
            pm.install_plugin(str(zip_path))

    def test_uninstall_removes_directory(self, plugins_dir, db, valid_manifest):
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest)
        pm = PluginManager(plugins_dir, db)
        pm.discover_plugins()

        assert pm.uninstall_plugin("test-plugin") is True
        assert not (plugins_dir / "test-plugin").exists()

    def test_uninstall_clears_db_data(self, plugins_dir, db, valid_manifest):
        create_plugin_dir(plugins_dir, "test-plugin", valid_manifest)
        pm = PluginManager(plugins_dir, db)
        pm.discover_plugins()

        # Save some data first
        db.set_plugin_data("test-plugin", "key1", "value1")
        assert db.get_plugin_data("test-plugin", "key1") == "value1"

        pm.uninstall_plugin("test-plugin")
        assert db.get_plugin_data("test-plugin", "key1") is None

    def test_uninstall_unknown_plugin_raises(self, plugins_dir, db):
        pm = PluginManager(plugins_dir, db)
        with pytest.raises(ValueError, match="Plugin not found"):
            pm.uninstall_plugin("nonexistent")
