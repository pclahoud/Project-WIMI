"""WIMI Plugin management bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from ..bridge_helpers import serialize_response


class PluginManagementMixin:
    """Bridge mixin for plugin management. Composed into DatabaseBridge."""

    @pyqtSlot(result=str)
    @instrumented_slot
    def getInstalledPlugins(self) -> str:
        """Get all installed plugins with enabled status."""
        try:
            pm = getattr(self, 'plugin_manager', None)
            if not pm:
                return serialize_response(True, data=[])

            plugins = pm.get_installed_plugins()
            return serialize_response(True, data=plugins)

        except Exception as e:
            # getInstalledPlugins takes no params.
            self._log_error(f'Error getting installed plugins: {e}')
            return serialize_response(False, error=f'Failed to get plugins: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def setPluginEnabled(self, params_json: str) -> str:
        """
        Enable or disable a plugin.

        Args:
            params_json: JSON with {plugin_id: str, enabled: bool}
        """
        try:
            params = json.loads(params_json)
            plugin_id = params.get('plugin_id')
            enabled = params.get('enabled', True)

            if not plugin_id:
                return serialize_response(False, error='plugin_id is required')

            pm = getattr(self, 'plugin_manager', None)
            if not pm:
                return serialize_response(False, error='Plugin manager not available')

            pm.set_plugin_enabled(plugin_id, enabled)

            # Update the bridge's plugin registry
            self._plugin_registry = pm.get_plugin_registry()

            return serialize_response(True, data={'plugin_id': plugin_id, 'enabled': enabled})

        except Exception as e:
            self._log_error(
                f'Error setting plugin enabled: {e}',
                {
                    'plugin_id': locals().get('plugin_id'),
                    'enabled': locals().get('enabled'),
                    'params_json_preview': params_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to set plugin state: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def openPluginInstallDialog(self) -> str:
        """Open a file dialog to select a .zip plugin file and install it."""
        try:
            from PyQt6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getOpenFileName(
                None,
                "Install Plugin from Zip",
                "",
                "Zip Files (*.zip);;All Files (*)"
            )
            if not file_path:
                return serialize_response(True, data=None)

            pm = getattr(self, 'plugin_manager', None)
            if not pm:
                return serialize_response(False, error='Plugin manager not available')

            result = pm.install_plugin(file_path)

            # Update the bridge's plugin registry
            self._plugin_registry = pm.get_plugin_registry()

            return serialize_response(True, data=result)

        except ValueError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error installing plugin: {e}',
                {'file_path': locals().get('file_path')},
            )
            return serialize_response(False, error=f'Failed to install plugin: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def uninstallPlugin(self, params_json: str) -> str:
        """
        Uninstall a plugin by ID.

        Args:
            params_json: JSON with {plugin_id: str}
        """
        try:
            params = json.loads(params_json)
            plugin_id = params.get('plugin_id')

            if not plugin_id:
                return serialize_response(False, error='plugin_id is required')

            pm = getattr(self, 'plugin_manager', None)
            if not pm:
                return serialize_response(False, error='Plugin manager not available')

            pm.uninstall_plugin(plugin_id)

            # Update the bridge's plugin registry
            self._plugin_registry = pm.get_plugin_registry()

            return serialize_response(True, data={'plugin_id': plugin_id, 'uninstalled': True})

        except ValueError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error uninstalling plugin: {e}',
                {
                    'plugin_id': locals().get('plugin_id'),
                    'params_json_preview': params_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to uninstall plugin: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getPluginSettings(self, params_json: str) -> str:
        """
        Get settings for a plugin (merged with defaults).

        Args:
            params_json: JSON with {plugin_id: str}
        """
        try:
            params = json.loads(params_json)
            plugin_id = params.get('plugin_id')

            if not plugin_id:
                return serialize_response(False, error='plugin_id is required')

            pm = getattr(self, 'plugin_manager', None)
            if not pm:
                return serialize_response(False, error='Plugin manager not available')

            settings = pm.get_plugin_settings(plugin_id)
            return serialize_response(True, data=settings)

        except Exception as e:
            self._log_error(
                f'Error getting plugin settings: {e}',
                {
                    'plugin_id': locals().get('plugin_id'),
                    'params_json_preview': params_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to get plugin settings: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def updatePluginSettings(self, params_json: str) -> str:
        """
        Update settings for a plugin.

        Args:
            params_json: JSON with {plugin_id: str, settings: dict}
        """
        try:
            params = json.loads(params_json)
            plugin_id = params.get('plugin_id')
            settings = params.get('settings', {})

            if not plugin_id:
                return serialize_response(False, error='plugin_id is required')

            pm = getattr(self, 'plugin_manager', None)
            if not pm:
                return serialize_response(False, error='Plugin manager not available')

            merged = pm.update_plugin_settings(plugin_id, settings)
            return serialize_response(True, data=merged)

        except Exception as e:
            self._log_error(
                f'Error updating plugin settings: {e}',
                {
                    'plugin_id': locals().get('plugin_id'),
                    'params_json_preview': params_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to update plugin settings: {e}')
