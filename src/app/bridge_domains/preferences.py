"""WIMI Preferences bridge operations."""
from dataclasses import asdict

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
            prefs = self.user_db.get_preferences()
            if not prefs:
                return serialize_response(False, error='Could not load preferences')

            prefs_dict = asdict(prefs)
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

            updated = self.user_db.update_preferences(**params)

            prefs_dict = asdict(updated)
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
