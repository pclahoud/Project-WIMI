"""WIMI Preferences database operations.

**User-level only.** m021 (#126) moved the machine-local settings out of
``user_preferences`` into ``device_settings`` — the pane's remembered
geometry, AnkiConnect's host/port and the MCP server's port — because
they are *wrong* on another machine rather than merely different there.
``update_preferences`` refuses one by name rather than writing a column
nothing reads; see ``DEVICE_LOCAL_SETTING_FIELDS`` in
``database/device_local.py`` for the list and the reasoning.

The legacy columns are still on the table. m021 leaves them rather than
rebuilding a table of real user data for columns that, once nothing
reads them, are inert — so this guard, plus their absence from the
``UserPreferences`` dataclass, is what actually keeps them unread.
"""

from typing import Optional

from ..base_db import DatabaseIntegrityError
from ..exceptions import ValidationError, PreferenceError
from ..models import UserPreferences
from ..device_local import DEVICE_LOCAL_SETTING_FIELDS
from app_logging import ErrorCategory


class PreferencesMixin:
    """Mixin for preferences operations. Composed into UserDatabase."""

    def get_preferences(self) -> Optional[UserPreferences]:
        """Get user preferences, create defaults if not exists"""
        row = self.fetchone(
            "SELECT * FROM user_preferences WHERE user_id = ?",
            (self.user_id,)
        )

        if not row:
            # Create default preferences
            return self.create_default_preferences()

        return UserPreferences.from_db_row(row)

    def create_default_preferences(self) -> UserPreferences:
        """Create default user preferences"""
        try:
            with self.transaction():
                self.execute("""
                    INSERT INTO user_preferences (user_id)
                    VALUES (?)
                """, (self.user_id,))

                if self.error_logger:
                    self.error_logger.debug(
                        f"Created default preferences for user {self.username}",
                        category=ErrorCategory.DATABASE
                    )

            return self.get_preferences()

        except DatabaseIntegrityError as e:
            # Preferences already exist
            return self.get_preferences()

    def update_preferences(self, **kwargs) -> UserPreferences:
        """
        Update user preferences.

        Args:
            **kwargs: Preference fields to update

        Returns:
            Updated UserPreferences object
        """
        # Ensure preferences exist
        prefs = self.get_preferences()

        # Build update query
        updates = []
        params = []

        # Map of preference fields that need validation
        validated_fields = {
            'font_size_scale': (0.5, 3.0),
            'default_session_duration_minutes': (15, 480),
            'default_break_interval_minutes': (5, 60),
            'default_long_break_minutes': (10, 60),
            'dashboard_auto_refresh_seconds': (30, 3600),
            'calendar_time_slot_minutes': [15, 30, 60],
            'child_subject_weight_inheritance_fraction': (0.1, 1.0),
            'entry_review_items_per_page': (10, 100),
            'anki_cache_refresh_interval_minutes': (1, 1440),
            'backup_frequency_hours': (1, 168),
            'backup_retention_days': (7, 365),
            'realtime_update_delay_ms': (100, 5000),
            'ui_density': ['compact', 'comfortable', 'spacious'],
            'analytics_detail_level': ['summary', 'detailed', 'advanced'],
            'long_break_interval_rounds': (2, 10),
            'timer_display_size': ['normal', 'large'],
            # 'source' opens pane_default_source_id; a dangling id there
            # degrades to blank rather than erroring, so it is not
            # validated against the sources table here.
            'pane_open_mode': ['last', 'source', 'blank'],
            'pane_shortcut_opens': ['current', 'new'],
        }

        for field, value in kwargs.items():
            if field in DEVICE_LOCAL_SETTING_FIELDS:
                # Loud, not silent. The column may still exist on this
                # table (m021 does not drop it), so writing it would
                # succeed and then be ignored forever by the code that
                # reads device_settings instead.
                raise ValidationError(
                    f"'{field}' is a device-local setting and does not travel "
                    f"with a profile — write it through "
                    f"update_device_settings() (or update_settings(), which "
                    f"routes each field to the right store)."
                )
            # Validate if needed
            if field in validated_fields:
                constraint = validated_fields[field]
                if isinstance(constraint, tuple):
                    min_val, max_val = constraint
                    if not (min_val <= value <= max_val):
                        raise ValidationError(
                            f"{field} must be between {min_val} and {max_val}"
                        )
                elif isinstance(constraint, list):
                    if value not in constraint:
                        raise ValidationError(
                            f"{field} must be one of {constraint}"
                        )

            updates.append(f"{field} = ?")
            params.append(value)

        if not updates:
            return prefs

        # Add timestamp update
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(self.user_id)

        query = f"""
            UPDATE user_preferences
            SET {', '.join(updates)}
            WHERE user_id = ?
        """

        with self.transaction():
            self.execute(query, tuple(params))

        return self.get_preferences()
