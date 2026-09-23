"""Device-local settings and profile identity at the database layer (#126, #129).

The transfer behaviour is covered end-to-end in
``tests/app/test_profile_identity_transfer.py``. This file pins the
mechanics underneath it: which store owns which field, how a machine
that has never seen a profile behaves, and the one-time handover from
the pre-m021 world.
"""
from __future__ import annotations

import pytest

from database.device_local import (
    DEVICE_LOCAL_SETTING_FIELDS,
    LEGACY_DEVICE_ID,
    UNKNOWN_DEVICE_ID,
    partition_settings,
)
from database.exceptions import ValidationError
from database.user_db import UserDatabase


DESKTOP = "device-desktop"
LAPTOP = "device-laptop"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "user_001_alice.db"


@pytest.fixture
def desktop(db_path):
    db = UserDatabase(db_path, user_id=1, username="alice", device_id=DESKTOP)
    yield db
    db.close()


def _laptop(db_path) -> UserDatabase:
    """The same profile file, opened by a different machine."""
    return UserDatabase(db_path, user_id=1, username="alice", device_id=LAPTOP)


# ==================== the split itself ====================

class TestTheSplit:
    def test_partition_sends_each_field_to_one_store(self):
        user, device = partition_settings({
            "theme_name": "dark",
            "ankiconnect_host": "box",
            "pane_open_mode": "blank",
            "pane_zoom_pct": 150,
        })
        assert user == {"theme_name": "dark", "pane_open_mode": "blank"}
        assert device == {"ankiconnect_host": "box", "pane_zoom_pct": 150}

    def test_ankiconnect_host_is_the_canonical_device_local_field(self):
        """Its default ``localhost`` denotes a different machine on each device.

        That is the test for the whole split, so it is asserted by name:
        copying this value is wrong even when the two values are
        byte-identical.
        """
        assert "ankiconnect_host" in DEVICE_LOCAL_SETTING_FIELDS

    def test_pane_default_source_id_stays_user_level(self):
        """It references a row that travels inside the same snapshot.

        ``question_sources`` is in the user database, so the id denotes
        the same question bank on the other machine. Nothing about it
        names a device, which is why it is on the user side despite
        sitting next to the pane's remembered geometry.
        """
        assert "pane_default_source_id" not in DEVICE_LOCAL_SETTING_FIELDS
        assert "pane_open_mode" not in DEVICE_LOCAL_SETTING_FIELDS
        assert "pane_shortcut_opens" not in DEVICE_LOCAL_SETTING_FIELDS

    def test_update_preferences_refuses_a_device_local_field(self, desktop):
        with pytest.raises(ValidationError) as exc:
            desktop.update_preferences(ankiconnect_host="box")
        assert "update_device_settings" in str(exc.value)

    def test_update_device_settings_refuses_a_user_level_field(self, desktop):
        with pytest.raises(ValidationError) as exc:
            desktop.update_device_settings(theme_name="dark")
        assert "update_preferences" in str(exc.value)

    def test_update_settings_writes_both_atomically(self, desktop):
        merged = desktop.update_settings(theme_name="dark", pane_zoom_pct=150)
        assert merged["theme_name"] == "dark"
        assert merged["pane_zoom_pct"] == 150
        assert desktop.get_preferences().theme_name == "dark"
        assert desktop.get_device_settings().pane_zoom_pct == 150

    def test_a_rejected_device_field_rolls_back_the_user_field(self, desktop):
        """One call, one transaction.

        The settings page saves a whole form through ``update_settings``.
        A half-applied save would leave the page showing values that were
        never stored together.
        """
        desktop.update_settings(theme_name="dark")
        with pytest.raises(ValidationError):
            desktop.update_settings(theme_name="light", pane_zoom_pct=9001)
        assert desktop.get_preferences().theme_name == "dark"


# ==================== one profile, two machines ====================

class TestTwoMachines:
    def test_each_machine_gets_its_own_row(self, db_path, desktop):
        desktop.update_device_settings(
            pane_zoom_pct=150, ankiconnect_host="desktop-box"
        )
        laptop = _laptop(db_path)
        try:
            device = laptop.get_device_settings()
            assert device.device_id == LAPTOP
            assert device.pane_zoom_pct == 100
            assert device.ankiconnect_host == "localhost"
        finally:
            laptop.close()

        # The desktop's row is untouched by the laptop having looked.
        assert desktop.get_device_settings().pane_zoom_pct == 150

    def test_a_machine_that_has_never_seen_the_profile_takes_defaults(
        self, db_path, desktop
    ):
        desktop.update_device_settings(
            pane_last_url="https://desktop.example.com/q/1",
            pane_split_app_pct=62,
            mcp_server_port=8123,
        )
        laptop = _laptop(db_path)
        try:
            device = laptop.get_device_settings()
            assert device.pane_last_url is None
            assert device.pane_split_app_pct is None
            assert device.mcp_server_port == 8000
        finally:
            laptop.close()

    def test_user_level_settings_are_shared_by_both_machines(
        self, db_path, desktop
    ):
        desktop.update_preferences(theme_name="dark", font_size_scale=1.25)
        laptop = _laptop(db_path)
        try:
            prefs = laptop.get_preferences()
            assert prefs.theme_name == "dark"
            assert prefs.font_size_scale == 1.25
        finally:
            laptop.close()

    def test_pane_source_state_is_per_machine(self, db_path, desktop):
        source = desktop.create_question_source(
            source_name="UWorld", url="https://uworld.com"
        )
        desktop.touch_pane_source(source.id)
        desktop.set_pane_desktop_site(source.id, False)

        laptop = _laptop(db_path)
        try:
            (bank,) = laptop.get_pane_sources()
            # The bank itself is a shared fact and arrives...
            assert bank["source_name"] == "UWorld"
            assert bank["url"] == "https://uworld.com"
            # ... its pane state is not.
            assert bank["last_opened_at"] is None
            assert bank["desktop_site"] is True
        finally:
            laptop.close()

        (bank,) = desktop.get_pane_sources()
        assert bank["last_opened_at"] is not None
        assert bank["desktop_site"] is False

    def test_deleting_a_source_removes_every_machines_pane_state(
        self, db_path, desktop
    ):
        source = desktop.create_question_source(
            source_name="UWorld", url="https://uworld.com"
        )
        desktop.touch_pane_source(source.id)
        laptop = _laptop(db_path)
        try:
            laptop.touch_pane_source(source.id)
        finally:
            laptop.close()
        assert desktop.fetchone(
            "SELECT COUNT(*) n FROM device_source_settings"
        )["n"] == 2

        with desktop.transaction():
            desktop.execute("DELETE FROM question_sources WHERE id = ?",
                            (source.id,))
        assert desktop.fetchone(
            "SELECT COUNT(*) n FROM device_source_settings"
        )["n"] == 0


# ==================== identity ====================

class TestProfileIdentity:
    def test_a_profile_has_one_stable_identifier(self, db_path, desktop):
        minted = desktop.get_profile_uuid()
        assert len(minted) == 36
        assert desktop.get_profile_uuid() == minted

        laptop = _laptop(db_path)
        try:
            # Same profile, different machine, same identity.
            assert laptop.get_profile_uuid() == minted
        finally:
            laptop.close()

    def test_two_profiles_have_different_identifiers(self, tmp_path):
        a = UserDatabase(tmp_path / "a.db", user_id=1, username="a")
        b = UserDatabase(tmp_path / "b.db", user_id=2, username="b")
        try:
            assert a.get_profile_uuid() != b.get_profile_uuid()
        finally:
            a.close()
            b.close()

    def test_the_device_id_is_not_stored_in_the_profiles_identity(self, desktop):
        """The two identifiers must never be confused for one another.

        The profile id travels; the device id must not. A device id that
        leaked into ``profile_identity`` would make a profile claim to be
        a different profile on each machine.
        """
        row = desktop.fetchone("SELECT * FROM profile_identity WHERE id = 1")
        assert DESKTOP not in str(dict(row))

    def test_a_bare_userdatabase_falls_back_to_a_named_sentinel(self, tmp_path):
        """Tests and short-lived verify-opens still need somewhere coherent."""
        db = UserDatabase(tmp_path / "bare.db", user_id=1, username="a")
        try:
            assert db.device_id() == UNKNOWN_DEVICE_ID
            assert db.get_device_settings().device_id == UNKNOWN_DEVICE_ID
        finally:
            db.close()


# ==================== the handover ====================

class TestLegacyHandover:
    def test_an_unclaimed_row_is_adopted_by_the_first_machine(
        self, db_path, desktop
    ):
        """m021 parks values for the machine that ran it to adopt."""
        with desktop.transaction():
            desktop.execute("DELETE FROM device_settings")
            desktop.execute(
                "INSERT INTO device_settings (device_id, pane_zoom_pct, "
                "ankiconnect_host) VALUES (?, 135, 'desktop-box')",
                (LEGACY_DEVICE_ID,),
            )
        desktop._legacy_device_rows_claimed = False

        device = desktop.get_device_settings()
        assert device.device_id == DESKTOP
        assert device.pane_zoom_pct == 135
        assert device.ankiconnect_host == "desktop-box"
        assert desktop.fetchone(
            "SELECT COUNT(*) n FROM device_settings WHERE device_id = ?",
            (LEGACY_DEVICE_ID,),
        )["n"] == 0

    def test_a_stale_handover_never_overwrites_an_existing_row(
        self, db_path, desktop
    ):
        """This machine's own row wins; the handover is dropped.

        Reached only if a handover somehow outlived the claim in
        ``__init__``. Adopting it then would silently replace settings the
        student has since changed.
        """
        desktop.update_device_settings(pane_zoom_pct=150)
        with desktop.transaction():
            desktop.execute(
                "INSERT INTO device_settings (device_id, pane_zoom_pct) "
                "VALUES (?, 135)",
                (LEGACY_DEVICE_ID,),
            )
        desktop._legacy_device_rows_claimed = False

        assert desktop.get_device_settings().pane_zoom_pct == 150
        assert desktop.fetchone(
            "SELECT COUNT(*) n FROM device_settings WHERE device_id = ?",
            (LEGACY_DEVICE_ID,),
        )["n"] == 0

    def test_opening_a_database_claims_before_anything_can_read_it(
        self, db_path, desktop
    ):
        """The claim is in ``__init__``, not in the first read.

        The window between the migration and the first read is where an
        export could otherwise ship an unclaimed row, handing the
        receiving machine this machine's AnkiConnect host.
        """
        with desktop.transaction():
            desktop.execute("DELETE FROM device_settings")
            desktop.execute(
                "INSERT INTO device_settings (device_id, pane_zoom_pct) "
                "VALUES (?, 135)",
                (LEGACY_DEVICE_ID,),
            )
        desktop.close()

        reopened = UserDatabase(
            db_path, user_id=1, username="alice", device_id=DESKTOP
        )
        try:
            rows = reopened.fetchall("SELECT device_id FROM device_settings")
            assert [r["device_id"] for r in rows] == [DESKTOP]
        finally:
            reopened.close()
