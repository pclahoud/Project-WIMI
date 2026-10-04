"""Where the four speech-to-text settings actually land (#59, #126).

``m023`` put two columns on ``user_preferences`` and two on
``device_settings``. This file is about the half that a schema test
cannot see: that the flat interface the settings page uses routes each
value to the store that owns it, that ``update_preferences`` refuses a
device-local one by name, and that the dataclasses carry the values back
out again.

**A round trip that only checks the values come back would pass with the
split backwards**, which is the bug this area can produce — so every
assertion here names the table.
"""
from __future__ import annotations

from dataclasses import fields as dataclass_fields

import pytest

from database.device_local import DEVICE_LOCAL_SETTING_FIELDS
from database.exceptions import ValidationError
from database.models import DeviceSettings, UserPreferences
from database.user_db import UserDatabase


DESKTOP = "device-desktop"
LAPTOP = "device-laptop"

USER_LEVEL = ("stt_priming_enabled", "stt_show_first_use_notice")
DEVICE_LOCAL = ("stt_model_size", "stt_input_device_id")


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


def _column_value(db: UserDatabase, table: str, column: str):
    """Read one column straight from one table, bypassing every mixin."""
    row = db.fetchone(f"SELECT {column} FROM {table} LIMIT 1")
    return row[column] if row else None


# ==================== the guard on the wrong door ====================


class TestUpdatePreferencesRefusesTheDeviceHalf:
    """Loud, not silent.

    m021 leaves legacy columns in place on ``user_preferences``, so a
    write that slipped through would succeed and then be ignored forever
    by the code that reads ``device_settings`` instead. Both new fields
    need the guard, not just the obvious one.
    """

    @pytest.mark.parametrize("field, value", [
        ("stt_model_size", "small"),
        ("stt_input_device_id", "usb-audio-0042"),
    ])
    def test_it_raises_and_names_the_right_method(self, desktop, field, value):
        with pytest.raises(ValidationError) as exc:
            desktop.update_preferences(**{field: value})

        message = str(exc.value)
        assert field in message
        assert "update_device_settings()" in message

    @pytest.mark.parametrize("field, value", [
        ("stt_priming_enabled", False),
        ("stt_show_first_use_notice", False),
    ])
    def test_the_user_half_goes_through_unchallenged(
        self, desktop, field, value
    ):
        prefs = desktop.update_preferences(**{field: value})
        assert getattr(prefs, field) is False

    @pytest.mark.parametrize("field, value", [
        ("stt_priming_enabled", False),
        ("stt_show_first_use_notice", False),
    ])
    def test_update_device_settings_refuses_the_user_half(
        self, desktop, field, value
    ):
        """The guard points both ways."""
        with pytest.raises(ValidationError) as exc:
            desktop.update_device_settings(**{field: value})
        assert "update_preferences" in str(exc.value)


# ==================== the round trip, with destinations ====================


class TestTheFlatInterfaceRoutesEachValue:
    """``get_all_settings`` / ``update_settings`` are what the settings
    page sees: one flat object. The split is a storage-and-travel
    property the UI has no reason to model."""

    def test_all_four_set_through_one_call_come_back(self, desktop):
        merged = desktop.update_settings(
            stt_priming_enabled=False,
            stt_show_first_use_notice=False,
            stt_model_size="small",
            stt_input_device_id="usb-audio-0042",
        )

        assert merged["stt_priming_enabled"] is False
        assert merged["stt_show_first_use_notice"] is False
        assert merged["stt_model_size"] == "small"
        assert merged["stt_input_device_id"] == "usb-audio-0042"

        # And again on a fresh read, not just the value handed back.
        reread = desktop.get_all_settings()
        assert reread["stt_model_size"] == "small"
        assert reread["stt_priming_enabled"] is False

    def test_the_user_half_landed_in_user_preferences(self, desktop):
        desktop.update_settings(
            stt_priming_enabled=False,
            stt_show_first_use_notice=False,
        )

        assert _column_value(desktop, "user_preferences", "stt_priming_enabled") == 0
        assert _column_value(
            desktop, "user_preferences", "stt_show_first_use_notice"
        ) == 0

    def test_the_device_half_landed_in_device_settings(self, desktop):
        desktop.update_settings(
            stt_model_size="small",
            stt_input_device_id="usb-audio-0042",
        )

        assert _column_value(desktop, "device_settings", "stt_model_size") == "small"
        assert _column_value(
            desktop, "device_settings", "stt_input_device_id"
        ) == "usb-audio-0042"

    def test_neither_half_wrote_into_the_other_table(self, desktop):
        """The columns do not exist on the other table at all.

        Asserting the write went to the right place is not enough on its
        own — m021's legacy columns are the precedent for a value
        sitting in two places and being read from one.
        """
        desktop.update_settings(
            stt_priming_enabled=False,
            stt_model_size="small",
        )

        prefs_columns = {
            r["name"] for r in desktop.fetchall("PRAGMA table_info(user_preferences)")
        }
        device_columns = {
            r["name"] for r in desktop.fetchall("PRAGMA table_info(device_settings)")
        }

        for field in DEVICE_LOCAL:
            assert field not in prefs_columns
        for field in USER_LEVEL:
            assert field not in device_columns

    def test_defaults_before_anything_is_set(self, desktop):
        settings = desktop.get_all_settings()
        assert settings["stt_priming_enabled"] is True
        assert settings["stt_show_first_use_notice"] is True
        assert settings["stt_model_size"] is None
        assert settings["stt_input_device_id"] is None


# ==================== the travel property itself ====================


class TestASecondMachineOpeningTheSameProfile:
    """The whole point of the split, stated as behaviour.

    This is what a ``.wimi`` install or a folder-sync pull looks like
    from the database's side: the same file, a different device id.
    """

    def test_it_inherits_the_preference_but_not_the_microphone(self, db_path, desktop):
        desktop.update_settings(
            stt_priming_enabled=False,
            stt_show_first_use_notice=False,
            stt_model_size="small",
            stt_input_device_id="usb-audio-0042",
        )

        laptop = _laptop(db_path)
        try:
            settings = laptop.get_all_settings()

            # Stated preferences follow the student.
            assert settings["stt_priming_enabled"] is False
            assert settings["stt_show_first_use_notice"] is False

            # This machine has its own microphone and its own models.
            assert settings["stt_model_size"] is None
            assert settings["stt_input_device_id"] is None
        finally:
            laptop.close()

    def test_each_machine_keeps_its_own_choice(self, db_path, desktop):
        desktop.update_settings(stt_model_size="small")

        laptop = _laptop(db_path)
        try:
            laptop.update_settings(stt_model_size="tiny")
            assert laptop.get_all_settings()["stt_model_size"] == "tiny"
        finally:
            laptop.close()

        assert desktop.get_all_settings()["stt_model_size"] == "small"


# ==================== the hand-enumerated from_db_row ====================
#
# ``from_db_row`` lists every field by hand. A field added to a
# dataclass and forgotten there is **silently defaulted forever** — no
# error, no warning, just a value that never changes. These tests are
# generic on purpose: they guard every future field, not only the four
# added here.


_SKIP_FIELDS = {"id", "user_id", "device_id", "created_at", "updated_at"}


def _a_value_that_is_not_the_default(field):
    """Produce a value distinguishable from ``field``'s default."""
    default = field.default
    if isinstance(default, bool):
        return not default
    if isinstance(default, float):
        return default + 0.5
    if isinstance(default, int):
        return default + 7
    if isinstance(default, str):
        return default + "_changed"
    if default is None:
        return 4242 if "int" in str(field.type) else "a-distinctive-value"
    raise AssertionError(
        f"{field.name} has an unhandled default {default!r}; teach this "
        f"helper about it rather than skipping the field."
    )


def _round_trip_every_field(cls, base_row):
    row = dict(base_row)
    expected = {}
    for field in dataclass_fields(cls):
        if field.name in _SKIP_FIELDS:
            continue
        value = _a_value_that_is_not_the_default(field)
        row[field.name] = value
        expected[field.name] = value

    obj = cls.from_db_row(row)

    forgotten = [
        name for name, value in expected.items()
        if getattr(obj, name) != value
    ]
    assert not forgotten, (
        f"{cls.__name__}.from_db_row does not carry {forgotten} out of the "
        f"row. It enumerates fields by hand, so a field missing there is "
        f"silently defaulted forever."
    )


class TestFromDbRowCarriesEveryField:
    def test_user_preferences(self):
        _round_trip_every_field(
            UserPreferences, {"id": 1, "user_id": 1}
        )

    def test_device_settings(self):
        _round_trip_every_field(
            DeviceSettings, {"id": 1, "device_id": DESKTOP}
        )

    def test_the_four_new_fields_by_name(self):
        """The generic test above would catch these; naming them makes a
        failure say which feature broke."""
        prefs = UserPreferences.from_db_row({
            "id": 1,
            "user_id": 1,
            "stt_priming_enabled": 0,
            "stt_show_first_use_notice": 0,
        })
        assert prefs.stt_priming_enabled is False
        assert prefs.stt_show_first_use_notice is False

        device = DeviceSettings.from_db_row({
            "id": 1,
            "device_id": DESKTOP,
            "stt_model_size": "small",
            "stt_input_device_id": "usb-audio-0042",
        })
        assert device.stt_model_size == "small"
        assert device.stt_input_device_id == "usb-audio-0042"

    def test_an_absent_column_falls_back_to_the_designed_default(self):
        """A row read before m023 applied — priming on, notice pending."""
        prefs = UserPreferences.from_db_row({"id": 1, "user_id": 1})
        assert prefs.stt_priming_enabled is True
        assert prefs.stt_show_first_use_notice is True

        device = DeviceSettings.from_db_row({"id": 1, "device_id": DESKTOP})
        assert device.stt_model_size is None
        assert device.stt_input_device_id is None


def test_the_register_and_the_dataclasses_agree():
    """``DEVICE_LOCAL_SETTING_FIELDS`` is the single definition of the
    boundary, and the dataclasses are what the rest of the app reads.
    They must not drift apart."""
    prefs_fields = {f.name for f in dataclass_fields(UserPreferences)}
    device_fields = {f.name for f in dataclass_fields(DeviceSettings)}

    for field in DEVICE_LOCAL:
        assert field in DEVICE_LOCAL_SETTING_FIELDS
        assert field in device_fields
        assert field not in prefs_fields

    for field in USER_LEVEL:
        assert field not in DEVICE_LOCAL_SETTING_FIELDS
        assert field in prefs_fields
        assert field not in device_fields
