"""Tests for user-DB migration v23 — the four speech-to-text settings (#59).

Four idempotent ``add_column_if_missing`` calls across two tables. The
interesting assertions are not "the columns exist" but **which table
each one landed in**, because a split made backwards is silent: the
value is stored, read back and used, and only shows itself when a
profile reaches a second machine.

* ``stt_priming_enabled``, ``stt_show_first_use_notice`` →
  ``user_preferences``. Neither denotes a machine, so both travel in a
  ``.wimi``.
* ``stt_model_size``, ``stt_input_device_id`` → ``device_settings``. The
  first names a weights file in this machine's ``app_data/``; the second
  names hardware plugged into this machine. Copying either is wrong.

D1 means there is no ``question_entries`` column to check for, and that
absence is asserted rather than assumed.
"""
from __future__ import annotations

import sqlite3

from database.device_local import DEVICE_LOCAL_SETTING_FIELDS
from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names
from database.migrations.user import (
    MIGRATIONS,
    m023_speech_to_text_settings,
)

USER_COLUMNS = ("stt_priming_enabled", "stt_show_first_use_notice")
DEVICE_COLUMNS = ("stt_model_size", "stt_input_device_id")


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v22(conn: sqlite3.Connection) -> MigrationRunner:
    """Simulates a database from just before #59 landed."""
    return MigrationRunner(
        conn,
        registry=[m for m in MIGRATIONS if m.version <= 22],
        scope="user",
    )


def _ledger_versions(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


# ---------------------------------------------------------------- tests


def test_registry_has_v23_above_the_m022_floor():
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert 23 in versions
    # The newest-migration claim has MOVED to m024's test, as the comment
    # here instructed when m024 landed (#210). It is deliberately held by
    # exactly one file at a time -- m022's copy was left behind when m023
    # landed, which is how it stopped noticing anything.
    # The gaps stay gaps: v8 is the assessments branch, v11-v14 were
    # stamped into real databases by the capture feature branch
    # (paused, #145). Reusing one would silently skip this migration on
    # any database that ran those builds.
    for skipped in (8, 11, 12, 13, 14):
        assert skipped not in versions
    names = {m.version: m.name for m in MIGRATIONS}
    assert names[23] == "speech_to_text_settings"


def test_registry_registers_the_module_exactly_once():
    """A module imported but left out of ``MIGRATIONS`` never runs."""
    assert [m.version for m in MIGRATIONS].count(23) == 1


def test_pre_v23_database_lacks_all_four_columns(fresh_conn):
    _runner_through_v22(fresh_conn).apply_pending()
    prefs = get_column_names(fresh_conn, "user_preferences")
    device = get_column_names(fresh_conn, "device_settings")
    for column in USER_COLUMNS:
        assert column not in prefs
    for column in DEVICE_COLUMNS:
        assert column not in device


def test_apply_pending_adds_all_four_and_stamps_the_ledger(fresh_conn):
    _runner_through_v22(fresh_conn).apply_pending()

    applied = _full_runner(fresh_conn).apply_pending()

    # Not `== [23]`: a later migration joins this list, and the newest-
    # migration tripwire lives in one place (see above) rather than in
    # every test that happens to call apply_pending.
    assert 23 in applied
    prefs = get_column_names(fresh_conn, "user_preferences")
    device = get_column_names(fresh_conn, "device_settings")
    for column in USER_COLUMNS:
        assert column in prefs
    for column in DEVICE_COLUMNS:
        assert column in device
    assert 23 in _ledger_versions(fresh_conn)


def test_each_column_lands_in_one_table_only(fresh_conn):
    """The split made concrete in the schema.

    A device-local column sitting on ``user_preferences`` as well would
    be a second place to write it, and m021 leaves such legacy columns
    in place — so the guard is that these were never added there.
    """
    _full_runner(fresh_conn).apply_pending()
    prefs = get_column_names(fresh_conn, "user_preferences")
    device = get_column_names(fresh_conn, "device_settings")

    for column in DEVICE_COLUMNS:
        assert column not in prefs
    for column in USER_COLUMNS:
        assert column not in device


def test_no_column_was_added_to_question_entries(fresh_conn):
    """D1: the microphone goes on the two fields the form already has.

    The entry save path is untouched by this feature, and a stray
    column here would be the first sign that it was not.
    """
    _full_runner(fresh_conn).apply_pending()
    entry_columns = get_column_names(fresh_conn, "question_entries")
    assert not any(c.startswith("stt_") for c in entry_columns)
    assert "feynman_explanation" not in entry_columns


def test_existing_preferences_get_priming_on_and_the_notice_pending(fresh_conn):
    """A student already using WIMI gets the designed defaults.

    Priming on, because §3.6 ships it as the behaviour and the
    preference is the escape hatch. The notice still to be shown,
    because they have not seen it — the column is named for what it
    controls, so 1 means "show it".
    """
    _runner_through_v22(fresh_conn).apply_pending()
    fresh_conn.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    fresh_conn.commit()

    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        "SELECT stt_priming_enabled, stt_show_first_use_notice "
        "FROM user_preferences"
    ).fetchone()
    assert row["stt_priming_enabled"] == 1
    assert row["stt_show_first_use_notice"] == 1


def test_existing_device_row_has_not_chosen_anything(fresh_conn):
    """NULL means "this machine has not chosen", not "base".

    Resolving that belongs to ``stt/model_spec.py``, which owns the
    pinned revision and digest. A DEFAULT here would be a second
    statement of the same fact, free to disagree with it later.
    """
    _runner_through_v22(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO device_settings (device_id) VALUES ('device-desktop')"
    )
    fresh_conn.commit()

    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        "SELECT stt_model_size, stt_input_device_id FROM device_settings"
    ).fetchone()
    assert row["stt_model_size"] is None
    assert row["stt_input_device_id"] is None


def test_user_columns_are_not_null_and_device_columns_are_nullable(fresh_conn):
    """The two tables say different things, on purpose.

    A NULL preference would read as falsy in Python and as "unset" to
    anyone reading the table — two meanings for one value. A NULL device
    column *is* the meaning: nothing chosen here yet.
    """
    _full_runner(fresh_conn).apply_pending()

    prefs_notnull = {
        r["name"]: r["notnull"]
        for r in fresh_conn.execute("PRAGMA table_info(user_preferences)")
    }
    for column in USER_COLUMNS:
        assert prefs_notnull[column] == 1

    device_notnull = {
        r["name"]: r["notnull"]
        for r in fresh_conn.execute("PRAGMA table_info(device_settings)")
    }
    for column in DEVICE_COLUMNS:
        assert device_notnull[column] == 0


def test_model_size_takes_any_string(fresh_conn):
    """No CHECK constraint, and that is m021's stated policy.

    A value the app cannot use must be something to clamp at read time,
    not a failed migration and an app that will not open. A CHECK naming
    today's model sizes would also need a migration every time the
    pinned set changes.
    """
    _full_runner(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO device_settings (device_id, stt_model_size) "
        "VALUES ('device-desktop', 'a-size-that-no-longer-exists')"
    )
    fresh_conn.commit()
    row = fresh_conn.execute(
        "SELECT stt_model_size FROM device_settings"
    ).fetchone()
    assert row["stt_model_size"] == "a-size-that-no-longer-exists"


def test_the_device_local_register_agrees_with_the_tables():
    """``DEVICE_LOCAL_SETTING_FIELDS`` is the one definition of the
    boundary. A column device-local in one place and user-level in
    another is silent either way, which is the failure #126 exists to
    prevent."""
    for column in DEVICE_COLUMNS:
        assert column in DEVICE_LOCAL_SETTING_FIELDS
    for column in USER_COLUMNS:
        assert column not in DEVICE_LOCAL_SETTING_FIELDS


def test_rerun_is_idempotent(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    prefs_before = get_column_names(fresh_conn, "user_preferences")
    device_before = get_column_names(fresh_conn, "device_settings")

    m023_speech_to_text_settings.upgrade(fresh_conn)  # must not raise
    fresh_conn.commit()

    assert get_column_names(fresh_conn, "user_preferences") == prefs_before
    assert get_column_names(fresh_conn, "device_settings") == device_before


def test_rerun_does_not_reset_a_stored_value(fresh_conn):
    """Re-runnability is about the data as much as the schema."""
    _full_runner(fresh_conn).apply_pending()
    fresh_conn.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    fresh_conn.execute(
        "UPDATE user_preferences SET stt_priming_enabled = 0"
    )
    fresh_conn.execute(
        "INSERT INTO device_settings (device_id, stt_model_size) "
        "VALUES ('device-desktop', 'small')"
    )
    fresh_conn.commit()

    m023_speech_to_text_settings.upgrade(fresh_conn)
    fresh_conn.commit()

    assert fresh_conn.execute(
        "SELECT stt_priming_enabled FROM user_preferences"
    ).fetchone()["stt_priming_enabled"] == 0
    assert fresh_conn.execute(
        "SELECT stt_model_size FROM device_settings"
    ).fetchone()["stt_model_size"] == "small"


def test_upgrade_noop_on_bare_database():
    """Defensive guard: neither table exists, nothing is created."""
    conn = sqlite3.connect(":memory:")
    try:
        m023_speech_to_text_settings.upgrade(conn)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "user_preferences" not in tables
        assert "device_settings" not in tables
    finally:
        conn.close()


def test_fresh_user_database_reaches_v23(legacy_user_db_path):
    """The UserDatabase adoption path applies it like any other."""
    conn = sqlite3.connect(legacy_user_db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert 23 in _ledger_versions(conn)
        for column in USER_COLUMNS:
            assert column in get_column_names(conn, "user_preferences")
        for column in DEVICE_COLUMNS:
            assert column in get_column_names(conn, "device_settings")
    finally:
        conn.close()
