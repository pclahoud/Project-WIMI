"""Tests for user-DB migration v28 -- ``relation_confidence_threshold``.

One idempotent ``add_column_if_missing`` on ``user_preferences``, for the
owner's #380 decision: the confidence cutoff for relation proposals is the
student's, 0.80 by default.

Three properties are load-bearing beyond "the column exists":

* the default is **0.8**, the decided default, and an existing profile gets
  it on upgrade rather than a NULL;
* there is **no CHECK constraint**: the range lives in code so it can move
  without rebuilding a table of real user data (the m028 docstring says why);
* the column is **user-level**, not device-local (#126/#129), so it travels.
"""
from __future__ import annotations

import sqlite3

from database.device_local import DEVICE_LOCAL_SETTING_FIELDS
from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names
from database.migrations.user import (
    MIGRATIONS,
    m028_relation_confidence_threshold,
)

COLUMN = "relation_confidence_threshold"


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v27(conn: sqlite3.Connection) -> MigrationRunner:
    """Simulates a database from just before #380 landed."""
    return MigrationRunner(
        conn, registry=[m for m in MIGRATIONS if m.version <= 27], scope="user",
    )


def _ledger_versions(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


# The registry snapshot that used to live here has MOVED to
# tests/database/migrations/test_user_030_settings_defaults_reset.py, as the
# docstring on it instructed: it asserts max(versions) and so belongs to
# whichever migration is newest, by exactly one file at a time. Moved, not
# loosened. m029 joined the skipped set there.


def test_pre_v28_database_lacks_the_column(fresh_conn):
    _runner_through_v27(fresh_conn).apply_pending()
    assert COLUMN not in get_column_names(fresh_conn, "user_preferences")


def test_apply_pending_adds_the_column_and_stamps_the_ledger(fresh_conn):
    _runner_through_v27(fresh_conn).apply_pending()
    applied = _full_runner(fresh_conn).apply_pending()
    assert applied[0] == 28
    assert COLUMN in get_column_names(fresh_conn, "user_preferences")
    assert 28 in _ledger_versions(fresh_conn)


def test_an_existing_profile_gets_the_decided_default(fresh_conn):
    """A student who already has preferences starts at 0.80, not at NULL."""
    _runner_through_v27(fresh_conn).apply_pending()
    fresh_conn.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    fresh_conn.commit()

    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(f"SELECT {COLUMN} FROM user_preferences").fetchone()
    assert row[COLUMN] == 0.8


def test_the_column_is_not_null_and_has_no_check(fresh_conn):
    """NOT NULL, because NULL would be a second meaning for "the default".

    No CHECK, because the range is a product decision that has already moved
    once; a value outside it is refused in code (``update_preferences`` and
    ``runtime.validate_threshold``), not by the schema.
    """
    _full_runner(fresh_conn).apply_pending()
    info = {r["name"]: r for r in fresh_conn.execute("PRAGMA table_info(user_preferences)")}
    assert info[COLUMN]["notnull"] == 1
    fresh_conn.execute("INSERT INTO user_preferences (user_id) VALUES (2)")
    fresh_conn.execute(f"UPDATE user_preferences SET {COLUMN} = 0.01 WHERE user_id = 2")
    assert fresh_conn.execute(
        f"SELECT {COLUMN} FROM user_preferences WHERE user_id = 2").fetchone()[0] == 0.01


def test_the_column_is_not_device_local():
    """It denotes a judgement about proposals, not a machine, so it travels."""
    assert COLUMN not in DEVICE_LOCAL_SETTING_FIELDS


def test_rerun_is_idempotent(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    before = get_column_names(fresh_conn, "user_preferences")
    m028_relation_confidence_threshold.upgrade(fresh_conn)  # must not raise
    fresh_conn.commit()
    assert get_column_names(fresh_conn, "user_preferences") == before


def test_upgrade_noop_on_bare_database():
    conn = sqlite3.connect(":memory:")
    try:
        m028_relation_confidence_threshold.upgrade(conn)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "user_preferences" not in tables
    finally:
        conn.close()


def test_fresh_user_database_reaches_v28(legacy_user_db_path):
    conn = sqlite3.connect(legacy_user_db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert 28 in _ledger_versions(conn)
        assert COLUMN in get_column_names(conn, "user_preferences")
    finally:
        conn.close()
