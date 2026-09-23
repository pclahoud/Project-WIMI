"""Tests for user-DB migration v22 — ``efficiency_show_confidence_band``.

One idempotent ``add_column_if_missing`` on ``user_preferences``, added
by #133 when weight provenance came out of the efficiency score's
arithmetic and the remaining uncertainty became something the student
chooses to see.

Two properties are load-bearing beyond "the column exists":

* the default is **0**, because ``_get_efficiency_rating``'s bands
  (``>= 85`` Excellent, and so on) assume a single number;
* the column is **user-level**, not device-local. #126/#129's test is
  whether a value denotes a machine; a display preference does not, so
  it must travel in a ``.wimi`` rather than sit in ``device_settings``.
"""
from __future__ import annotations

import sqlite3

from database.device_local import DEVICE_LOCAL_SETTING_FIELDS
from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names
from database.migrations.user import (
    MIGRATIONS,
    m022_efficiency_confidence_band,
)

COLUMN = "efficiency_show_confidence_band"


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v21(conn: sqlite3.Connection) -> MigrationRunner:
    """Simulates a database from just before #133 landed."""
    return MigrationRunner(
        conn,
        registry=[m for m in MIGRATIONS if m.version <= 21],
        scope="user",
    )


def _ledger_versions(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


# ---------------------------------------------------------------- tests


def test_registry_has_v22_above_the_m021_floor():
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert 22 in versions
    assert max(versions) == 22
    # The gaps stay gaps: v8 is the assessments branch, v11-v14 were
    # stamped into real databases by the capture feature branch (paused, #145).
    for skipped in (8, 11, 12, 13, 14):
        assert skipped not in versions
    names = {m.version: m.name for m in MIGRATIONS}
    assert names[22] == "efficiency_confidence_band"


def test_pre_v22_database_lacks_the_column(fresh_conn):
    _runner_through_v21(fresh_conn).apply_pending()
    assert COLUMN not in get_column_names(fresh_conn, "user_preferences")


def test_apply_pending_adds_the_column_and_stamps_the_ledger(fresh_conn):
    _runner_through_v21(fresh_conn).apply_pending()

    applied = _full_runner(fresh_conn).apply_pending()

    assert applied == [22]
    assert COLUMN in get_column_names(fresh_conn, "user_preferences")
    assert 22 in _ledger_versions(fresh_conn)


def test_existing_preferences_default_to_off(fresh_conn):
    """A student who has been using WIMI keeps seeing one number.

    The rating vocabulary assumes a scalar, so turning the band on for
    everybody would change what "Excellent" means without asking.
    """
    _runner_through_v21(fresh_conn).apply_pending()
    fresh_conn.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    fresh_conn.commit()

    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        f"SELECT {COLUMN} FROM user_preferences"
    ).fetchone()
    assert row[COLUMN] == 0


def test_the_column_is_not_null(fresh_conn):
    """``NOT NULL DEFAULT 0`` — a NULL here would read as falsy in
    Python and as "unset" to anyone reading the table, which is two
    meanings for one value."""
    _full_runner(fresh_conn).apply_pending()
    notnull = {
        r["name"]: r["notnull"]
        for r in fresh_conn.execute("PRAGMA table_info(user_preferences)")
    }
    assert notnull[COLUMN] == 1


def test_the_column_is_not_device_local():
    """It denotes a preference, not a machine, so it travels (#126/#129).

    ``DEVICE_LOCAL_SETTING_FIELDS`` is the one definition of the
    boundary; a column that is device-local in one place and user-level
    in another is silent either way.
    """
    assert COLUMN not in DEVICE_LOCAL_SETTING_FIELDS


def test_rerun_is_idempotent(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    before = get_column_names(fresh_conn, "user_preferences")

    m022_efficiency_confidence_band.upgrade(fresh_conn)  # must not raise
    fresh_conn.commit()

    assert get_column_names(fresh_conn, "user_preferences") == before


def test_upgrade_noop_on_bare_database():
    """Defensive guard: the table does not exist, nothing is created."""
    conn = sqlite3.connect(":memory:")
    try:
        m022_efficiency_confidence_band.upgrade(conn)
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "user_preferences" not in tables
    finally:
        conn.close()


def test_fresh_user_database_reaches_v22(legacy_user_db_path):
    """The UserDatabase adoption path applies it like any other."""
    conn = sqlite3.connect(legacy_user_db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert 22 in _ledger_versions(conn)
        assert COLUMN in get_column_names(conn, "user_preferences")
    finally:
        conn.close()
