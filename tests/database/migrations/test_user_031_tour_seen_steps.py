"""Tests for user-DB migration v31: ``user_preferences.tour_seen_steps`` (#430).

A TEXT column holding a JSON list of ``page:anchor`` step keys, default
``'[]'``. It is a list rather than a flag because a step shows only once its
target is on screen (owner, 2026-10-09). The reasoning is in the migration's
docstring.
"""
from __future__ import annotations

import sqlite3

from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names
from database.migrations.user import MIGRATIONS, m031_tour_seen_steps


def _runner_through_v30(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(
        conn, registry=[m for m in MIGRATIONS if m.version <= 30], scope="user")


def test_registry_has_v31_and_keeps_the_gaps():
    """The registry snapshot, moved here from m030's test as it instructs.

    **A new migration will make this fail, and the fix is to MOVE these lines
    into its test, not to loosen them.** Carried m023 -> ... -> m030 -> here.
    m031 was pre-assigned to the tour on #430, and 29 stays skipped: a database
    that has taken 30 would apply a later 29 out of order.
    """
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert versions[versions.index(31) - 1] == 30
    for skipped in (8, 11, 12, 13, 14, 29):
        assert skipped not in versions
    assert {m.version: m.name for m in MIGRATIONS}[31] == "tour_seen_steps"
    # The max(versions) snapshot moved to m032's test, as instructed above.


def test_an_existing_profile_gains_an_empty_list(fresh_conn):
    """No backfill: nobody has been shown a step that has never existed."""
    _runner_through_v30(fresh_conn).apply_pending()
    fresh_conn.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    fresh_conn.commit()
    assert "tour_seen_steps" not in get_column_names(fresh_conn, "user_preferences")

    MigrationRunner(fresh_conn, registry=MIGRATIONS, scope="user").apply_pending()

    row = fresh_conn.execute(
        "SELECT tour_seen_steps FROM user_preferences WHERE user_id = 1").fetchone()
    assert row[0] == "[]"


def test_it_is_idempotent(fresh_conn):
    MigrationRunner(fresh_conn, registry=MIGRATIONS, scope="user").apply_pending()
    m031_tour_seen_steps.upgrade(fresh_conn)  # a second run adds nothing
    cols = get_column_names(fresh_conn, "user_preferences")
    assert cols.count("tour_seen_steps") == 1 if isinstance(cols, list) \
        else "tour_seen_steps" in cols


def test_it_is_user_level_and_travels():
    """#126/#129: it records what the student was taught, not a machine fact,
    so it must not be listed as device-local."""
    from database.device_local import DEVICE_LOCAL_SETTING_FIELDS
    assert "tour_seen_steps" not in DEVICE_LOCAL_SETTING_FIELDS
