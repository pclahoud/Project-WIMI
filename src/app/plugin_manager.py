"""
WIMI PluginManager — Discovers, loads, and manages plugins.

Scans app_data/plugins/ for directories with manifest.json,
validates manifests, creates scoped PluginAPI instances,
and manages plugin lifecycle.
"""

import importlib.util
import shutil
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from .plugin_manifest import PluginManifest
from .plugin_api import PluginAPI


class PluginManager:
    """
    Manages plugin discovery, loading, and lifecycle.

    Args:
        plugins_dir: Path to the plugins directory (e.g., app_data/plugins/)
        user_db: UserDatabase instance
        error_logger: Optional ErrorLogger instance
    """

    def __init__(self, plugins_dir: Path, user_db, error_logger=None):
        self._plugins_dir = plugins_dir
        self._user_db = user_db
        self._error_logger = error_logger
        self._manifests: Dict[str, PluginManifest] = {}
        self._backend_instances: Dict[str, object] = {}
        self._apis: Dict[str, PluginAPI] = {}

    def _log(self, message: str, level: str = 'info'):
        """Log a message."""
        if self._error_logger:
            getattr(self._error_logger, level, self._error_logger.info)(message)
        else:
            print(f'[PluginManager] {message}')

    def discover_plugins(self) -> List[PluginManifest]:
        """
        Scan plugins_dir for directories containing manifest.json.

        Returns:
            List of valid PluginManifest objects
        """
        manifests = []

        if not self._plugins_dir.exists():
            return manifests

        for entry in sorted(self._plugins_dir.iterdir()):
            if not entry.is_dir():
                continue

            manifest_path = entry / 'manifest.json'
            if not manifest_path.exists():
                continue

            try:
                manifest = PluginManifest.from_file(manifest_path)
                manifests.append(manifest)
                self._manifests[manifest.id] = manifest
            except Exception as e:
                self._log(f'Skipping plugin in {entry.name}: {e}', 'warning')

        return manifests

    def load_plugin(self, plugin_id: str) -> bool:
        """
        Load a single plugin by ID.

        1. Check enabled state
        2. If backend module specified, import and call create_plugin(api)
        3. Store backend instance

        Returns:
            True if loaded successfully
        """
        manifest = self._manifests.get(plugin_id)
        if not manifest:
            self._log(f'Plugin not found: {plugin_id}', 'warning')
            return False

        # Check enabled state
        if not self._user_db.get_plugin_enabled(plugin_id):
            self._log(f'Plugin disabled, skipping: {plugin_id}')
            return False

        # Create scoped API
        media_mgr = getattr(self, '_media_manager', None)
        api = PluginAPI(plugin_id, self._user_db, manifest.permissions, manifest.plugin_dir, media_manager=media_mgr)
        self._apis[plugin_id] = api

        # Load backend if specified
        if manifest.backend and manifest.plugin_dir:
            backend_path = manifest.plugin_dir / manifest.backend
            if not backend_path.exists():
                self._log(f'Backend file not found: {backend_path}', 'warning')
                return False

            try:
                module = self._import_module(plugin_id, backend_path)
                create_fn = getattr(module, 'create_plugin', None)
                if not create_fn or not callable(create_fn):
                    self._log(
                        f'Plugin {plugin_id}: backend module missing create_plugin() function',
                        'warning'
                    )
                    return False

                instance = create_fn(api)
                self._backend_instances[plugin_id] = instance
                self._log(f'Loaded backend for plugin: {plugin_id}')

            except Exception as e:
                self._log(f'Failed to load backend for {plugin_id}: {e}', 'error')
                traceback.print_exc()
                return False
        else:
            # Frontend-only plugin, still considered loaded
            self._backend_instances[plugin_id] = None

        self._log(f'Plugin loaded: {manifest.name} ({plugin_id}) v{manifest.version}')
        return True

    def _import_module(self, plugin_id: str, module_path: Path):
        """Import a Python module from a file path."""
        module_name = f'wimi_plugin_{plugin_id}'
        spec = importlib.util.spec_from_file_location(module_name, str(module_path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def unload_plugin(self, plugin_id: str) -> bool:
        """
        Unload a plugin and clean up.

        Returns:
            True if unloaded
        """
        instance = self._backend_instances.pop(plugin_id, None)
        self._apis.pop(plugin_id, None)

        # Call cleanup if available
        if instance and hasattr(instance, 'on_unload') and callable(instance.on_unload):
            try:
                instance.on_unload()
            except Exception as e:
                self._log(f'Error during unload of {plugin_id}: {e}', 'warning')

        # Remove from sys.modules
        module_name = f'wimi_plugin_{plugin_id}'
        sys.modules.pop(module_name, None)

        self._log(f'Plugin unloaded: {plugin_id}')
        return True

    def load_all(self) -> dict:
        """
        Discover and load all enabled plugins.

        Returns:
            Dict of {plugin_id: success_bool}
        """
        manifests = self.discover_plugins()
        results = {}

        for manifest in manifests:
            results[manifest.id] = self.load_plugin(manifest.id)

        return results

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        """
        Enable or disable a plugin, loading/unloading as needed.
        """
        self._user_db.set_plugin_enabled(plugin_id, enabled)

        if enabled:
            if plugin_id not in self._backend_instances:
                self.load_plugin(plugin_id)
        else:
            if plugin_id in self._backend_instances:
                self.unload_plugin(plugin_id)

    def install_plugin(self, zip_path: str) -> dict:
        """
        Install a plugin from a .zip file.

        Extracts the zip, validates the manifest, and copies to plugins_dir.
        If a plugin with the same ID already exists, it is replaced.

        Args:
            zip_path: Path to the .zip file

        Returns:
            Dict with {plugin_id, name, version, replaced}

        Raises:
            ValueError: If the zip is invalid or contains no valid manifest
        """
        zip_path = Path(zip_path)
        if not zip_path.exists():
            raise ValueError(f'File not found: {zip_path}')

        if not zipfile.is_zipfile(str(zip_path)):
            raise ValueError(f'Not a valid zip file: {zip_path}')

        tmp_dir = None
        try:
            # Security: reject path traversal
            with zipfile.ZipFile(str(zip_path), 'r') as zf:
                for entry in zf.namelist():
                    if '..' in entry.split('/') or '..' in entry.split('\\'):
                        raise ValueError(
                            f'Zip contains path traversal entry: {entry}'
                        )

                tmp_dir = Path(tempfile.mkdtemp(prefix='wimi_plugin_'))
                zf.extractall(str(tmp_dir))

            # Find manifest.json: at root OR in single top-level directory
            manifest_path = tmp_dir / 'manifest.json'
            plugin_content_dir = tmp_dir

            if not manifest_path.exists():
                # Check for single subdirectory containing manifest
                subdirs = [
                    d for d in tmp_dir.iterdir() if d.is_dir()
                ]
                found = False
                for subdir in subdirs:
                    candidate = subdir / 'manifest.json'
                    if candidate.exists():
                        manifest_path = candidate
                        plugin_content_dir = subdir
                        found = True
                        break
                if not found:
                    raise ValueError(
                        'Zip does not contain a manifest.json at root or '
                        'in a top-level directory'
                    )

            # Validate manifest
            manifest = PluginManifest.from_file(manifest_path)

            # Determine target directory
            target_dir = self._plugins_dir / manifest.id
            replaced = False

            # If exists, unload and remove
            if target_dir.exists():
                if manifest.id in self._backend_instances:
                    self.unload_plugin(manifest.id)
                shutil.rmtree(str(target_dir))
                replaced = True

            # Ensure plugins dir exists
            self._plugins_dir.mkdir(parents=True, exist_ok=True)

            # Move extracted plugin to target
            shutil.copytree(str(plugin_content_dir), str(target_dir))

            # Re-discover and load
            self.discover_plugins()
            self.load_plugin(manifest.id)

            self._log(
                f'Plugin installed: {manifest.name} v{manifest.version}'
                + (' (replaced)' if replaced else '')
            )

            return {
                'plugin_id': manifest.id,
                'name': manifest.name,
                'version': manifest.version,
                'replaced': replaced,
            }

        finally:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(str(tmp_dir), ignore_errors=True)

    def uninstall_plugin(self, plugin_id: str) -> bool:
        """
        Uninstall a plugin: unload, delete directory, clear DB data.

        Args:
            plugin_id: Plugin identifier

        Returns:
            True if uninstalled successfully

        Raises:
            ValueError: If plugin not found
        """
        manifest = self._manifests.get(plugin_id)
        if not manifest:
            raise ValueError(f'Plugin not found: {plugin_id}')

        plugin_dir = manifest.plugin_dir

        # Unload if loaded
        if plugin_id in self._backend_instances:
            self.unload_plugin(plugin_id)

        # Delete directory
        if plugin_dir and plugin_dir.exists():
            shutil.rmtree(str(plugin_dir))

        # Clear DB data
        self._user_db.clear_plugin_data(plugin_id)

        # Remove from manifests
        self._manifests.pop(plugin_id, None)

        self._log(f'Plugin uninstalled: {plugin_id}')
        return True

    def get_installed_plugins(self) -> List[dict]:
        """
        Get all discovered plugins with their enabled status.

        Returns:
            List of dicts with manifest info + 'enabled' field
        """
        result = []
        for plugin_id, manifest in self._manifests.items():
            info = manifest.to_frontend_dict()
            info['enabled'] = self._user_db.get_plugin_enabled(plugin_id)
            info['has_backend'] = plugin_id in self._backend_instances and self._backend_instances[plugin_id] is not None
            result.append(info)
        return result

    def get_plugin_settings(self, plugin_id: str) -> dict:
        """
        Get plugin settings merged with manifest defaults.

        Returns:
            Dict of setting key -> value (with defaults applied)
        """
        manifest = self._manifests.get(plugin_id)
        if not manifest:
            return {}

        # Build defaults from manifest
        defaults = {}
        for setting in manifest.settings:
            defaults[setting.key] = setting.default

        # Merge with saved settings
        saved = self._user_db.get_plugin_settings(plugin_id)
        merged = {**defaults, **saved}
        return merged

    def update_plugin_settings(self, plugin_id: str, settings: dict) -> dict:
        """
        Save plugin settings and return the merged result.

        Args:
            plugin_id: Plugin identifier
            settings: Settings dict to save

        Returns:
            Merged settings (defaults + saved)
        """
        self._user_db.set_plugin_settings(plugin_id, settings)
        return self.get_plugin_settings(plugin_id)

    def set_media_manager(self, media_manager) -> None:
        """
        Set the media manager on all existing PluginAPI instances.

        Called from MainWindow after the MediaManager is created/updated.
        """
        self._media_manager = media_manager
        for api in self._apis.values():
            api._media_manager = media_manager

    def get_plugin_registry(self) -> dict:
        """
        Get the backend instance registry for use by the bridge's callPlugin.

        Returns:
            Dict of plugin_id -> backend instance (only non-None entries)
        """
        return {
            pid: inst
            for pid, inst in self._backend_instances.items()
            if inst is not None
        }
