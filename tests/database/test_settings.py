"""
Tests for Global Settings: schema migration, preference CRUD, and validation.

Covers preferences column migration (now handled by the migration runner),
get_preferences(), create_default_preferences(), update_preferences(), and
validation logic.

Run with: pytest tests/database/test_settings.py --no-cov -v
(Use --no-cov to skip the 80% coverage threshold that fails on single-file runs.)
"""

import pytest
from dataclasses import fields as dataclass_fields
from datetime import date
from database.user_db import UserDatabase
from database.exceptions import ValidationError
from database.models import UserPreferences


@pytest.fixture
def db(tmp_path):
    """Create a database with preferences support."""
    db_path = tmp_path / "test_settings.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")
    return db


# ==================== Migration Tests ====================


class TestPreferencesMigration:
    """Tests for the preferences column migration (applied via migration runner)."""

    EXPECTED_MIGRATION_COLUMNS = [
        "primary_color_hex",
        "secondary_color_hex",
        "font_family",
        "ui_density",
        "manual_break_control",
        "analytics_detail_level",
        "show_performance_trends",
        "show_mistake_patterns",
        "show_subject_breakdown",
        "show_time_analytics",
        "show_weekend_in_calendar",
        "anki_integration_enabled",
        "auto_backup_enabled",
        "cloud_sync_enabled",
        "entry_review_default_sort_field",
        "entry_review_default_sort_direction",
    ]

    def test_migration_adds_columns(self, db):
        """After init, all 16 new preference columns should exist in user_preferences."""
        columns = db.fetchall("PRAGMA table_info(user_preferences)")
        column_names = {col['name'] for col in columns}

        for col in self.EXPECTED_MIGRATION_COLUMNS:
            assert col in column_names, f"Missing column: {col}"

    def test_new_columns_have_defaults(self, db):
        """Newly migrated columns should produce correct default values in preferences."""
        prefs = db.get_preferences()

        assert prefs.primary_color_hex == '#2196F3'
        assert prefs.secondary_color_hex == '#FFC107'
        assert prefs.font_family == 'system'
        assert prefs.ui_density == 'comfortable'
        assert prefs.manual_break_control is True
        assert prefs.analytics_detail_level == 'detailed'
        assert prefs.show_performance_trends is True
        assert prefs.show_mistake_patterns is True
        assert prefs.show_subject_breakdown is True
        assert prefs.show_time_analytics is True
        assert prefs.show_weekend_in_calendar is True
        assert prefs.anki_integration_enabled is False
        assert prefs.auto_backup_enabled is True
        assert prefs.cloud_sync_enabled is False
        assert prefs.entry_review_default_sort_field == 'answered_incorrectly_date'
        assert prefs.entry_review_default_sort_direction == 'desc'


# ==================== Get Preferences Tests ====================


class TestGetPreferences:
    """Tests for get_preferences() auto-creation and field completeness."""

    def test_get_preferences_creates_defaults(self, db):
        """First call to get_preferences() should auto-create defaults and return UserPreferences."""
        prefs = db.get_preferences()

        assert prefs is not None
        assert isinstance(prefs, UserPreferences)
        assert prefs.user_id == 1

    def test_get_preferences_returns_all_fields(self, db):
        """Returned UserPreferences should have all fields defined in the dataclass."""
        prefs = db.get_preferences()

        expected_fields = {f.name for f in dataclass_fields(UserPreferences)}
        actual_fields = set(vars(prefs).keys())

        for field_name in expected_fields:
            assert field_name in actual_fields, (
                f"Field '{field_name}' missing from returned preferences"
            )


# ==================== Update Preferences Tests ====================


class TestUpdatePreferences:
    """Tests for update_preferences() single/multiple field updates."""

    def test_update_single_field(self, db):
        """Updating a single field should persist the new value."""
        db.update_preferences(primary_color_hex='#FF0000')
        prefs = db.get_preferences()

        assert prefs.primary_color_hex == '#FF0000'

    def test_update_multiple_fields(self, db):
        """Updating multiple fields in one call should persist all changes."""
        db.update_preferences(font_size_scale=1.2, ui_density='compact')
        prefs = db.get_preferences()

        assert prefs.font_size_scale == 1.2
        assert prefs.ui_density == 'compact'

    def test_update_returns_updated_prefs(self, db):
        """The return value of update_preferences() should reflect new values."""
        result = db.update_preferences(
            primary_color_hex='#00FF00',
            analytics_detail_level='advanced'
        )

        assert isinstance(result, UserPreferences)
        assert result.primary_color_hex == '#00FF00'
        assert result.analytics_detail_level == 'advanced'

    def test_update_no_changes_returns_prefs(self, db):
        """Calling update_preferences() with no kwargs should return current prefs unchanged."""
        original = db.get_preferences()
        result = db.update_preferences()

        assert result.theme_name == original.theme_name
        assert result.primary_color_hex == original.primary_color_hex


# ==================== Validation Tests ====================


class TestValidation:
    """Tests for validation constraints in update_preferences()."""

    def test_invalid_ui_density_raises(self, db):
        """An invalid ui_density value should raise ValidationError."""
        with pytest.raises(ValidationError):
            db.update_preferences(ui_density='invalid')

    def test_valid_ui_density_values(self, db):
        """All three valid ui_density values should be accepted."""
        for value in ['compact', 'comfortable', 'spacious']:
            result = db.update_preferences(ui_density=value)
            assert result.ui_density == value

    def test_invalid_analytics_detail_level_raises(self, db):
        """An invalid analytics_detail_level should raise ValidationError."""
        with pytest.raises(ValidationError):
            db.update_preferences(analytics_detail_level='invalid')

    def test_valid_analytics_detail_level_values(self, db):
        """All three valid analytics_detail_level values should be accepted."""
        for value in ['summary', 'detailed', 'advanced']:
            result = db.update_preferences(analytics_detail_level=value)
            assert result.analytics_detail_level == value

    def test_font_size_scale_range(self, db):
        """font_size_scale must be between 0.5 and 3.0 inclusive."""
        # Valid boundary values
        result_low = db.update_preferences(font_size_scale=0.5)
        assert result_low.font_size_scale == 0.5

        result_high = db.update_preferences(font_size_scale=3.0)
        assert result_high.font_size_scale == 3.0

        # Below minimum
        with pytest.raises(ValidationError):
            db.update_preferences(font_size_scale=0.4)

        # Above maximum
        with pytest.raises(ValidationError):
            db.update_preferences(font_size_scale=3.1)

    def test_entry_review_items_per_page_range(self, db):
        """entry_review_items_per_page must be between 10 and 100 inclusive."""
        # Valid boundary values
        result_low = db.update_preferences(entry_review_items_per_page=10)
        assert result_low.entry_review_items_per_page == 10

        result_high = db.update_preferences(entry_review_items_per_page=100)
        assert result_high.entry_review_items_per_page == 100

        # Below minimum
        with pytest.raises(ValidationError):
            db.update_preferences(entry_review_items_per_page=9)

        # Above maximum
        with pytest.raises(ValidationError):
            db.update_preferences(entry_review_items_per_page=101)


# ==================== Round-Trip Tests ====================


class TestRoundTrip:
    """Tests for full update-then-read round trips and reset behavior."""

    def test_update_then_get_matches(self, db):
        """Updated fields should match when retrieved via get_preferences()."""
        updates = {
            'primary_color_hex': '#123456',
            'secondary_color_hex': '#654321',
            'font_family': 'monospace',
            'font_size_scale': 1.5,
            'ui_density': 'compact',
            'analytics_detail_level': 'summary',
            'show_performance_trends': False,
            'show_mistake_patterns': False,
            'entry_review_items_per_page': 50,
            'entry_review_default_sort_field': 'question_id',
            'entry_review_default_sort_direction': 'asc',
        }

        db.update_preferences(**updates)
        prefs = db.get_preferences()

        assert prefs.primary_color_hex == '#123456'
        assert prefs.secondary_color_hex == '#654321'
        assert prefs.font_family == 'monospace'
        assert prefs.font_size_scale == 1.5
        assert prefs.ui_density == 'compact'
        assert prefs.analytics_detail_level == 'summary'
        assert prefs.show_performance_trends is False
        assert prefs.show_mistake_patterns is False
        assert prefs.entry_review_items_per_page == 50
        assert prefs.entry_review_default_sort_field == 'question_id'
        assert prefs.entry_review_default_sort_direction == 'asc'

    def test_reset_to_defaults(self, db):
        """After modifying fields, resetting them to defaults should restore initial state."""
        # Capture initial defaults
        initial = db.get_preferences()

        # Change several fields away from defaults
        db.update_preferences(
            primary_color_hex='#000000',
            font_size_scale=2.0,
            ui_density='spacious',
            analytics_detail_level='advanced',
            show_performance_trends=False,
            entry_review_items_per_page=75,
        )

        # Verify they changed
        changed = db.get_preferences()
        assert changed.primary_color_hex == '#000000'
        assert changed.ui_density == 'spacious'

        # Reset back to defaults
        db.update_preferences(
            primary_color_hex=initial.primary_color_hex,
            font_size_scale=initial.font_size_scale,
            ui_density=initial.ui_density,
            analytics_detail_level=initial.analytics_detail_level,
            show_performance_trends=initial.show_performance_trends,
            entry_review_items_per_page=initial.entry_review_items_per_page,
        )

        # Verify reset matches initial state
        reset = db.get_preferences()
        assert reset.primary_color_hex == initial.primary_color_hex
        assert reset.font_size_scale == initial.font_size_scale
        assert reset.ui_density == initial.ui_density
        assert reset.analytics_detail_level == initial.analytics_detail_level
        assert reset.show_performance_trends == initial.show_performance_trends
        assert reset.entry_review_items_per_page == initial.entry_review_items_per_page
