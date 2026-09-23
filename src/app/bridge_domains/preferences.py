"""WIMI Preferences bridge operations.

**One flat object, two stores.** m021 (#126) split the machine-local
settings out of ``user_preferences`` into ``device_settings``, keyed by
a device id that never travels with a profile. That split is a storage
and travel property; it is not something the settings page has any
reason to model, and forcing it into the UI would mean two save paths
and a second place for a field to be forgotten. So these two slots keep
speaking the flat vocabulary the page already uses, and
``get_all_settings`` / ``update_settings`` on the database route each
field to the store that owns it.
"""

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from ..bridge_helpers import serialize_response
from database.exceptions import ValidationError


class PreferencesBridgeMixin:
    """Bridge mixin for user preferences operations. Composed into DatabaseBridge."""

    @pyqtSlot(result=str)
    @instrumented_slot
    def getUserPreferences(self) -> str:
        """Get all user preferences."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            prefs_dict = self.user_db.get_all_settings()
            if not prefs_dict:
                return serialize_response(False, error='Could not load preferences')

            prefs_dict.pop('created_at', None)
            prefs_dict.pop('updated_at', None)

            return serialize_response(True, data=prefs_dict)

        except Exception as e:
            # getUserPreferences takes no params.
            self._log_error(f'Error getting preferences: {e}')
            return serialize_response(False, error=f'Failed to get preferences: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def updateUserPreferences(self, params_json: str) -> str:
        """
        Update user preferences.

        Args:
            params_json: JSON object with preference fields to update
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            import json
            params = json.loads(params_json)

            prefs_dict = self.user_db.update_settings(**params)
            prefs_dict.pop('created_at', None)
            prefs_dict.pop('updated_at', None)

            return serialize_response(True, data=prefs_dict)

        except ValidationError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'Error updating preferences: {e}',
                {
                    'params_json_len': len(params_json),
                    'params_json_preview': params_json[:200],
                },
            )
            return serialize_response(False, error=f'Failed to update preferences: {e}')
