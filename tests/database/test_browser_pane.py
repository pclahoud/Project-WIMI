"""Browser pane, database layer: pane preferences and per-source pane fields.

Covers what m015-m017 added for the embedded browser pane and what the
Settings -> Question Banks panel reads and writes:

* ``update_preferences`` validation for ``pane_open_mode``,
  ``pane_shortcut_opens`` and ``pane_zoom_pct``, plus the defaults every
  fresh profile starts with.
* ``pane_default_source_id`` is deliberately NOT validated against the
  sources table: a dangling id degrades to "open blank" in the pane.
* ``SourcesMixin.get_pane_sources`` / ``touch_pane_source`` /
  ``set_pane_desktop_site``: which sources earn a shortcut button, the
  most-recently-opened ordering, and per-user scoping.

Run with: pytest tests/database/test_browser_pane.py --no-cov -v
"""
import time

import pytest

from database.exceptions import ValidationError
from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    db = UserDatabase(str(tmp_path / "pane.db"), user_id=1, username="pane_user")
    yield db
    db.close()


def _source(db, name, url=None):
    return db.create_question_source(source_name=name, url=url)


def _pane_names(db):
    return [s['source_name'] for s in db.get_pane_sources()]


def _foreign_source(db, name='Not Mine', url='https://example.com', user_id=999):
    """Insert a source owned by another user id, bypassing the mixin."""
    with db.transaction():
        cur = db.execute(
            "INSERT INTO question_sources (user_id, source_name, url) VALUES (?, ?, ?)",
            (user_id, name, url),
        )
        return cur.lastrowid


# ==================== Preferences ====================


class TestPanePreferenceDefaults:
    def test_fresh_profile_defaults(self, db):
        """The pane's stated preferences follow the student (#126).

        ``pane_default_source_id`` is here and not in device settings on
        purpose: it references a ``question_sources`` row, and that row
        travels inside the same snapshot, so the id denotes the same
        question bank on the other machine.
        """
        prefs = db.get_preferences()
        assert prefs.pane_open_mode == 'last'
        assert prefs.pane_shortcut_opens == 'current'
        assert prefs.pane_default_source_id is None
        for moved in ('pane_zoom_pct', 'pane_last_url', 'pane_split_app_pct'):
            assert not hasattr(prefs, moved), moved

    def test_fresh_profile_device_defaults(self, db):
        """The pane's remembered geometry belongs to the machine (#126)."""
        device = db.get_device_settings()
        assert device.pane_zoom_pct == 100
        assert device.pane_last_url is None
        assert device.pane_split_app_pct is None


class TestPanePreferenceValidation:
    def test_valid_open_modes(self, db):
        for value in ['last', 'source', 'blank']:
            assert db.update_preferences(pane_open_mode=value).pane_open_mode == value

    def test_invalid_open_mode_raises(self, db):
        with pytest.raises(ValidationError):
            db.update_preferences(pane_open_mode='always')

    def test_valid_shortcut_opens(self, db):
        for value in ['current', 'new']:
            result = db.update_preferences(pane_shortcut_opens=value)
            assert result.pane_shortcut_opens == value

    def test_invalid_shortcut_opens_raises(self, db):
        with pytest.raises(ValidationError):
            db.update_preferences(pane_shortcut_opens='popup')

    def test_zoom_pct_range(self, db):
        assert db.update_device_settings(pane_zoom_pct=25).pane_zoom_pct == 25
        assert db.update_device_settings(pane_zoom_pct=500).pane_zoom_pct == 500
        with pytest.raises(ValidationError):
            db.update_device_settings(pane_zoom_pct=24)
        with pytest.raises(ValidationError):
            db.update_device_settings(pane_zoom_pct=501)

    def test_a_device_local_field_is_refused_by_update_preferences(self, db):
        """The legacy column still exists, so the refusal must be loud.

        m021 does not drop ``user_preferences.pane_zoom_pct`` — dropping
        means rebuilding a table of real user data. Writing it would
        therefore succeed and then be ignored forever by the code that
        reads ``device_settings`` instead, which is the silent failure
        this guard exists to prevent.
        """
        with pytest.raises(ValidationError) as exc:
            db.update_preferences(pane_zoom_pct=150)
        assert 'update_device_settings' in str(exc.value)

    def test_rejected_value_leaves_stored_value_untouched(self, db):
        db.update_preferences(pane_open_mode='source')
        with pytest.raises(ValidationError):
            db.update_preferences(pane_open_mode='nope')
        assert db.get_preferences().pane_open_mode == 'source'

    def test_default_source_id_is_not_checked_against_sources(self, db):
        """A dangling id must be storable; the pane degrades to blank."""
        prefs = db.update_preferences(pane_default_source_id=424242)
        assert prefs.pane_default_source_id == 424242

    def test_default_source_survives_deleting_that_source(self, db):
        src = _source(db, 'UWorld', url='https://uworld.com')
        db.update_preferences(pane_default_source_id=src.id)
        assert db.delete_question_source(src.id) is True
        assert db.get_preferences().pane_default_source_id == src.id

    def test_remembered_state_round_trips(self, db):
        device = db.update_device_settings(
            pane_last_url='https://uworld.com/qbank/1',
            pane_split_app_pct=55,
        )
        assert device.pane_last_url == 'https://uworld.com/qbank/1'
        assert device.pane_split_app_pct == 55

    def test_update_settings_routes_a_mixed_bag(self, db):
        """The settings page saves every field through one call."""
        merged = db.update_settings(
            pane_open_mode='blank',
            pane_last_url='https://uworld.com/qbank/2',
        )
        assert merged['pane_open_mode'] == 'blank'
        assert merged['pane_last_url'] == 'https://uworld.com/qbank/2'
        assert db.get_preferences().pane_open_mode == 'blank'
        assert db.get_device_settings().pane_last_url == \
            'https://uworld.com/qbank/2'


# ==================== get_pane_sources ====================


class TestGetPaneSources:
    def test_only_sources_with_an_address_earn_a_shortcut(self, db):
        _source(db, 'UWorld', url='https://uworld.com')
        _source(db, 'Amboss')              # no address
        _source(db, 'Kaplan', url='   ')   # whitespace is not an address
        assert _pane_names(db) == ['UWorld']

    def test_row_shape_and_desktop_site_default(self, db):
        src = _source(db, 'UWorld', url='https://uworld.com')
        (row,) = db.get_pane_sources()
        assert row == {
            'id': src.id,
            'source_name': 'UWorld',
            'url': 'https://uworld.com',
            # m015 defaults to 1: the toolbar checkbox it replaced was on,
            # so existing banks keep receiving the desktop user-agent.
            'desktop_site': True,
            'last_opened_at': None,
        }

    def test_soft_deleted_sources_are_excluded(self, db):
        src = _source(db, 'UWorld', url='https://uworld.com')
        db.delete_question_source(src.id)
        assert db.get_pane_sources() == []

    def test_clearing_the_address_removes_the_shortcut(self, db):
        """What the settings panel does when a student blanks the field."""
        src = _source(db, 'UWorld', url='https://uworld.com')
        db.update_question_source(src.id, url='')
        assert db.get_pane_sources() == []
        db.update_question_source(src.id, url='https://uworld.com')
        assert _pane_names(db) == ['UWorld']

    def test_never_opened_sources_sort_alphabetically_case_insensitive(self, db):
        _source(db, 'uworld', url='https://uworld.com')
        _source(db, 'Amboss', url='https://amboss.com')
        _source(db, 'Kaplan', url='https://kaplan.com')
        assert _pane_names(db) == ['Amboss', 'Kaplan', 'uworld']

    def test_opened_sources_precede_never_opened_ones(self, db):
        _source(db, 'Amboss', url='https://amboss.com')
        kaplan = _source(db, 'Kaplan', url='https://kaplan.com')
        _source(db, 'UWorld', url='https://uworld.com')
        db.touch_pane_source(kaplan.id)
        assert _pane_names(db) == ['Kaplan', 'Amboss', 'UWorld']

    def test_other_users_sources_are_not_listed(self, db):
        _foreign_source(db)
        assert db.get_pane_sources() == []


# ==================== touch_pane_source ====================


class TestTouchPaneSource:
    def test_most_recently_opened_comes_first(self, db):
        amboss = _source(db, 'Amboss', url='https://amboss.com')
        uworld = _source(db, 'UWorld', url='https://uworld.com')

        db.touch_pane_source(amboss.id)
        time.sleep(0.005)
        db.touch_pane_source(uworld.id)
        assert _pane_names(db) == ['UWorld', 'Amboss']

        time.sleep(0.005)
        db.touch_pane_source(amboss.id)
        assert _pane_names(db) == ['Amboss', 'UWorld']

    def test_timestamp_carries_fractional_seconds(self, db):
        """Second granularity let two opens in one second tie and fall
        back to alphabetical order, so the pane could ignore a click."""
        src = _source(db, 'UWorld', url='https://uworld.com')
        db.touch_pane_source(src.id)
        (row,) = db.get_pane_sources()
        stamp = row['last_opened_at']
        assert stamp is not None
        # strftime('%Y-%m-%d %H:%M:%f') -> 'YYYY-MM-DD HH:MM:SS.SSS'
        assert len(stamp) == 23 and stamp[19] == '.', stamp

    def test_ordering_with_explicit_timestamps(self, db):
        """Deterministic check of the ORDER BY, independent of the clock."""
        a = _source(db, 'Amboss', url='https://amboss.com')
        k = _source(db, 'Kaplan', url='https://kaplan.com')
        u = _source(db, 'UWorld', url='https://uworld.com')
        # Per-device since m021 (#126): the MRU order lives in
        # device_source_settings, not on the shared source row.
        with db.transaction():
            for sid, stamp in ((a.id, '2026-01-01 10:00:00.100'),
                               (u.id, '2026-01-01 10:00:00.300'),
                               (k.id, '2026-01-01 10:00:00.200')):
                db._upsert_device_source(sid, 'pane_last_opened_at', stamp)
        assert _pane_names(db) == ['UWorld', 'Kaplan', 'Amboss']

    def test_touch_is_scoped_to_the_owning_user(self, db):
        other_id = _foreign_source(db)
        db.touch_pane_source(other_id)
        row = db.fetchone(
            "SELECT pane_last_opened_at FROM device_source_settings "
            "WHERE source_id = ?",
            (other_id,),
        )
        assert row is None

    def test_touch_unknown_id_is_a_noop(self, db):
        db.touch_pane_source(987654)  # must not raise
        assert db.get_pane_sources() == []


# ==================== set_pane_desktop_site ====================


class TestSetPaneDesktopSite:
    def test_toggle_off_and_back_on(self, db):
        src = _source(db, 'UWorld', url='https://uworld.com')
        db.set_pane_desktop_site(src.id, False)
        assert db.get_pane_sources()[0]['desktop_site'] is False
        db.set_pane_desktop_site(src.id, True)
        assert db.get_pane_sources()[0]['desktop_site'] is True

    def test_setting_is_per_source(self, db):
        amboss = _source(db, 'Amboss', url='https://amboss.com')
        uworld = _source(db, 'UWorld', url='https://uworld.com')
        db.set_pane_desktop_site(amboss.id, False)
        flags = {s['id']: s['desktop_site'] for s in db.get_pane_sources()}
        assert flags == {amboss.id: False, uworld.id: True}

    def test_is_scoped_to_the_owning_user(self, db):
        other_id = _foreign_source(db)
        db.set_pane_desktop_site(other_id, False)
        row = db.fetchone(
            "SELECT pane_desktop_site FROM question_sources WHERE id = ?",
            (other_id,),
        )
        assert row['pane_desktop_site'] == 1
