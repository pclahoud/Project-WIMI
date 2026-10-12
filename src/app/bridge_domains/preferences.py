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

    # ------------------------------------------------------------------
    # First-run tour (#430)
    # ------------------------------------------------------------------

    @pyqtSlot(result=str)
    @instrumented_slot
    def getTourState(self) -> str:
        """``{seen: [page:anchor, ...], auto_start: bool}``.

        ``auto_start`` is false under ``--test-mode`` unless a scenario turned
        it on (#430). A first-run overlay defaulting to on would cover every
        one of the ~400 scenarios, because each gets a fresh profile, and
        suppressing it only in the harness would leave the tour itself
        untested. So it is off by default there, and the tour's own scenarios
        switch it on through ``setTourAutoStartForTest``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            from app import test_mode
            auto_start = (not test_mode.is_active()
                          or getattr(self, '_tour_auto_start_for_test', False))
            return serialize_response(True, data={
                'seen': self.user_db.get_tour_seen_steps(),
                'auto_start': bool(auto_start),
            })
        except Exception as e:
            self._log_error(f'Error reading tour state: {e}', {})
            return serialize_response(False, error=f'Failed to read tour state: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def markTourStepsSeen(self, keys_json: str) -> str:
        """Record shown steps. Takes a JSON list of ``page:anchor`` keys."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            import json
            seen = self.user_db.mark_tour_steps_seen(json.loads(keys_json))
            return serialize_response(True, data={'seen': seen})
        except (ValidationError, ValueError) as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'Error recording tour steps: {e}', {})
            return serialize_response(False, error=f'Failed to record tour steps: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def resetTour(self) -> str:
        """Replay from Settings: every step shows again once it can."""
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            self.user_db.reset_tour_seen_steps()
            return serialize_response(True, data={'seen': []})
        except Exception as e:
            self._log_error(f'Error resetting the tour: {e}', {})
            return serialize_response(False, error=f'Failed to reset the tour: {e}')

    @pyqtSlot(bool, result=str)
    @instrumented_slot
    def setTourAutoStartForTest(self, enabled: bool) -> str:
        """Let a scenario turn the tour on. Refused outside ``--test-mode``.

        A release build refuses ``--test-mode`` itself (#144), so this cannot
        change a student's tour; the refusal here is for a development run
        without the flag.
        """
        from app import test_mode
        if not test_mode.is_active():
            return serialize_response(
                False, error='setTourAutoStartForTest is only available in test mode')
        self._tour_auto_start_for_test = bool(enabled)
        return serialize_response(True, data={'auto_start': bool(enabled)})
