"""Tests for plugin manifest parsing and validation."""

import json
import pytest
from pathlib import Path

from app.plugin_manifest import PluginManifest, PluginSettingDef, VALID_PERMISSIONS


@pytest.fixture
def valid_manifest_data():
    return {
        "id": "test-plugin",
        "name": "Test Plugin",
        "version": "1.0.0",
        "description": "A test plugin",
        "author": "Test Author",
        "permissions": ["read"],
        "settings": [
            {"key": "greeting", "type": "text", "label": "Greeting", "default": "Hello"},
            {"key": "count", "type": "number", "label": "Count", "default": 5, "min": 0, "max": 100},
            {"key": "enabled", "type": "toggle", "label": "Enable Feature", "default": True},
            {"key": "mode", "type": "select", "label": "Mode", "options": [
                {"value": "fast", "label": "Fast"},
                {"value": "slow", "label": "Slow"}
            ], "default": "fast"}
        ]
    }


@pytest.fixture
def manifest_file(tmp_path, valid_manifest_data):
    manifest_path = tmp_path / "test-plugin" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text(json.dumps(valid_manifest_data))
    return manifest_path


class TestManifestValidation:
    """Tests for PluginManifest.validate()."""

    def test_valid_manifest(self, valid_manifest_data):
        errors = PluginManifest.validate(valid_manifest_data)
        assert errors == []

    def test_missing_id(self, valid_manifest_data):
        del valid_manifest_data['id']
        errors = PluginManifest.validate(valid_manifest_data)
        assert any('id' in e for e in errors)

    def test_missing_name(self, valid_manifest_data):
        del valid_manifest_data['name']
        errors = PluginManifest.validate(valid_manifest_data)
        assert any('name' in e for e in errors)

    def test_missing_version(self, valid_manifest_data):
        del valid_manifest_data['version']
        errors = PluginManifest.validate(valid_manifest_data)
        assert any('version' in e for e in errors)

    def test_invalid_id_chars(self):
        errors = PluginManifest.validate({
            "id": "bad plugin!", "name": "X", "version": "1.0.0"
        })
        assert any('Invalid plugin id' in e for e in errors)

    def test_id_too_long(self):
        errors = PluginManifest.validate({
            "id": "a" * 65, "name": "X", "version": "1.0.0"
        })
        assert any('Invalid plugin id' in e for e in errors)

    def test_name_too_long(self):
        errors = PluginManifest.validate({
            "id": "ok", "name": "X" * 129, "version": "1.0.0"
        })
        assert any('128' in e for e in errors)

    def test_invalid_version_format(self):
        errors = PluginManifest.validate({
            "id": "ok", "name": "X", "version": "1.0"
        })
        assert any('version' in e.lower() for e in errors)

    def test_invalid_permission(self, valid_manifest_data):
        valid_manifest_data['permissions'] = ['read', 'write:everything']
        errors = PluginManifest.validate(valid_manifest_data)
        assert any('Invalid permission' in e for e in errors)

    def test_invalid_setting_type(self, valid_manifest_data):
        valid_manifest_data['settings'] = [
            {"key": "x", "type": "color", "label": "Color"}
        ]
        errors = PluginManifest.validate(valid_manifest_data)
        assert any('invalid type' in e for e in errors)

    def test_setting_missing_key(self, valid_manifest_data):
        valid_manifest_data['settings'] = [
            {"type": "text", "label": "No Key"}
        ]
        errors = PluginManifest.validate(valid_manifest_data)
        assert any('missing key' in e for e in errors)

    def test_setting_missing_label(self, valid_manifest_data):
        valid_manifest_data['settings'] = [
            {"key": "x", "type": "text"}
        ]
        errors = PluginManifest.validate(valid_manifest_data)
        assert any('missing label' in e for e in errors)

    def test_minimal_valid_manifest(self):
        """Minimum required fields only."""
        errors = PluginManifest.validate({
            "id": "minimal",
            "name": "Minimal",
            "version": "0.1.0"
        })
        assert errors == []


class TestManifestFromFile:
    """Tests for PluginManifest.from_file()."""

    def test_load_valid_manifest(self, manifest_file):
        manifest = PluginManifest.from_file(manifest_file)
        assert manifest.id == "test-plugin"
        assert manifest.name == "Test Plugin"
        assert manifest.version == "1.0.0"
        assert manifest.description == "A test plugin"
        assert manifest.author == "Test Author"
        assert manifest.permissions == ["read"]
        assert len(manifest.settings) == 4
        assert manifest.plugin_dir == manifest_file.parent

    def test_settings_parsed(self, manifest_file):
        manifest = PluginManifest.from_file(manifest_file)
        s0 = manifest.settings[0]
        assert isinstance(s0, PluginSettingDef)
        assert s0.key == "greeting"
        assert s0.type == "text"
        assert s0.default == "Hello"

    def test_invalid_manifest_raises(self, tmp_path):
        path = tmp_path / "bad" / "manifest.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"id": "bad plugin!"}))

        with pytest.raises(ValueError, match="Invalid manifest"):
            PluginManifest.from_file(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            PluginManifest.from_file(tmp_path / "nonexistent.json")


class TestManifestToFrontendDict:
    """Tests for to_frontend_dict() output."""

    def test_basic_fields(self, manifest_file):
        manifest = PluginManifest.from_file(manifest_file)
        d = manifest.to_frontend_dict()
        assert d['id'] == "test-plugin"
        assert d['name'] == "Test Plugin"
        assert d['version'] == "1.0.0"
        assert d['description'] == "A test plugin"
        assert d['permissions'] == ["read"]
        assert len(d['settings']) == 4

    def test_settings_format(self, manifest_file):
        manifest = PluginManifest.from_file(manifest_file)
        d = manifest.to_frontend_dict()
        s0 = d['settings'][0]
        assert s0['key'] == 'greeting'
        assert s0['type'] == 'text'
        assert s0['label'] == 'Greeting'
        assert s0['default'] == 'Hello'

    def test_no_js_css_when_not_specified(self, manifest_file):
        manifest = PluginManifest.from_file(manifest_file)
        d = manifest.to_frontend_dict()
        # No frontend_js/css in manifest, so keys should not be present
        assert 'js' not in d
        assert 'css' not in d
