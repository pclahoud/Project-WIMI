"""WIMI Plugin dispatch bridge operations."""
import json

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from ..bridge_helpers import serialize_response


class PluginDispatchMixin:
    """Bridge mixin for plugin dispatch. Composed into DatabaseBridge."""

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def callPlugin(self, request_json: str) -> str:
        """
        Dispatch a call to a registered plugin.

        Args:
            request_json: JSON string with {plugin_id, method, params}

        Returns:
            JSON response from the plugin or error
        """
        try:
            request = json.loads(request_json)
            plugin_id = request.get('plugin_id')
            method = request.get('method')
            params = request.get('params', {})

            if not plugin_id or not method:
                return serialize_response(False, error='plugin_id and method are required')

            # Look up the live backend instance via plugin_manager to avoid
            # stale registry snapshots after install/enable/disable.
            pm = getattr(self, 'plugin_manager', None)
            if not pm:
                return serialize_response(False, error='Plugin system not available')
            plugin = pm._backend_instances.get(plugin_id)
            if not plugin:
                return serialize_response(False, error=f'Plugin not found: {plugin_id}')

            handler = getattr(plugin, method, None)
            if not handler or not callable(handler):
                return serialize_response(False, error=f'Method not found on plugin {plugin_id}: {method}')

            result = handler(**params)
            return serialize_response(True, data=result)

        except Exception as e:
            self._log_error(
                f'Error calling plugin: {e}',
                {
                    'plugin_id': locals().get('plugin_id'),
                    'method': locals().get('method'),
                    'request_json_preview': request_json[:200],
                },
            )
            return serialize_response(False, error=f'Plugin call failed: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def pluginUploadMedia(self, request_json: str) -> str:
        """
        Upload media on behalf of a frontend plugin (permission-gated).

        Args:
            request_json: JSON string with {plugin_id, entry_id, base64_data, filename, mime_type}

        Returns:
            JSON response with full media record or error
        """
        try:
            request = json.loads(request_json)
            plugin_id = request.get('plugin_id')
            entry_id = request.get('entry_id')
            base64_data = request.get('base64_data')
            filename = request.get('filename')
            mime_type = request.get('mime_type')

            if not plugin_id:
                return serialize_response(False, error='plugin_id is required')

            pm = getattr(self, 'plugin_manager', None)
            if not pm:
                return serialize_response(False, error='Plugin system not available')

            api = pm._apis.get(plugin_id)
            if not api:
                return serialize_response(False, error=f'Plugin not loaded: {plugin_id}')

            result = api.upload_media(entry_id, base64_data, filename, mime_type)

            if 'error' in result:
                return serialize_response(False, error=result['error'])
            return serialize_response(True, data=result)

        except PermissionError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error in pluginUploadMedia: {e}',
                {
                    'plugin_id': locals().get('plugin_id'),
                    'entry_id': locals().get('entry_id'),
                    'filename': locals().get('filename'),
                    'mime_type': locals().get('mime_type'),
                },
            )
            return serialize_response(False, error=f'Plugin media upload failed: {e}')
