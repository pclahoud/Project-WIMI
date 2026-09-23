"""Tests for user-DB migrations v15-v17 (browser pane columns).

m015 adds ``pane_desktop_site`` / ``pane_last_opened_at`` to
``question_sources``; m016 adds five ``pane_*`` state columns to
``user_preferences``; m017 adds ``pane_shortcut_opens``. All three are
idempotent ``add_column_if_missing`` adds.

The registry deliberately skips v11-v14: databases carried over from the
capture feature branch (paused, #145) have those versions stamped, and the runner
treats a stamped version as applied, so reusing one of those numbers
would mean the pane migration silently never ran on exactly the
databases that already exist. That path is exercised here rather than
only described in the m015 docstring.
"""
from __future__ import annotations

import sqlite3

from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names
from database.migrations.user import (
    MIGRATIONS,
    m015_browser_pane_source_fields,
    m016_browser_pane_state,
    m017_pane_shortcut_opens,
)

PANE_MODULES = (
    m015_browser_pane_source_fields,
    m016_browser_pane_state,
    m017_pane_shortcut_opens,
)
SOURCE_COLUMNS = {'pane_desktop_site', 'pane_last_opened_at'}
PREF_COLUMNS_V16 = {
    'pane_open_mode', 'pane_default_source_id', 'pane_last_url',
    'pane_split_app_pct', 'pane_zoom_pct',
}
PREF_COLUMN_V17 = 'pane_shortcut_opens'
PREF_COLUMNS = PREF_COLUMNS_V16 | {PREF_COLUMN_V17}


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v10(conn: sqlite3.Connection) -> MigrationRunner:
    """Simulates a database from just before the pane work landed."""
    return MigrationRunner(
        conn,
        registry=[m for m in MIGRATIONS if m.version <= 10],
        scope="user",
    )


def _stamp(conn: sqlite3.Connection, version: int, name: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
        (version, name, "carried-over-from-capture-branch"),
    )
    conn.commit()


def _ledger_versions(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


# ---------------------------------------------------------------- tests


def test_registry_has_v15_to_v17_and_keeps_the_gaps():
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert {15, 16, 17} <= set(versions)
    for skipped in (8, 11, 12, 13, 14):
        assert skipped not in versions
    names = {m.version: m.name for m in MIGRATIONS}
    assert names[15] == "browser_pane_source_fields"
    assert names[16] == "browser_pane_state"
    assert names[17] == "pane_shortcut_opens"


def test_pre_v15_database_lacks_pane_columns(fresh_conn):
    _runner_through_v10(fresh_conn).apply_pending()
    assert not (SOURCE_COLUMNS & get_column_names(fresh_conn, "question_sources"))
    assert not (PREF_COLUMNS & get_column_names(fresh_conn, "user_preferences"))


def test_apply_pending_adds_columns_and_stamps_ledger(fresh_conn):
    _runner_through_v10(fresh_conn).apply_pending()

    applied = _full_runner(fresh_conn).apply_pending()

    # Leading slice, not equality: every migration added after v17 also
    # lands in this run, and this file is about the pane ones.
    assert applied[:3] == [15, 16, 17]
    assert SOURCE_COLUMNS <= get_column_names(fresh_conn, "question_sources")
    assert PREF_COLUMNS <= get_column_names(fresh_conn, "user_preferences")
    assert {15, 16, 17} <= _ledger_versions(fresh_conn)


def test_existing_sources_keep_sending_the_desktop_user_agent(fresh_conn):
    """m015 defaults pane_desktop_site to 1, not 0: the global checkbox it
    replaced was checked, so a bank that logged in yesterday still can."""
    _runner_through_v10(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO question_sources (user_id, source_name, url) "
        "VALUES (1, 'UWorld', 'https://uworld.com')"
    )
    fresh_conn.commit()

    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        "SELECT pane_desktop_site, pane_last_opened_at FROM question_sources"
    ).fetchone()
    assert row["pane_desktop_site"] == 1
    assert row["pane_last_opened_at"] is None


def test_existing_preferences_get_pane_defaults(fresh_conn):
    _runner_through_v10(fresh_conn).apply_pending()
    fresh_conn.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    fresh_conn.commit()

    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        "SELECT pane_open_mode, pane_default_source_id, pane_last_url, "
        "pane_split_app_pct, pane_zoom_pct, pane_shortcut_opens "
        "FROM user_preferences"
    ).fetchone()
    assert row["pane_open_mode"] == "last"
    assert row["pane_zoom_pct"] == 100
    assert row["pane_shortcut_opens"] == "current"
    assert row["pane_default_source_id"] is None
    assert row["pane_last_url"] is None
    assert row["pane_split_app_pct"] is None


def test_default_source_id_is_not_a_foreign_key(fresh_conn):
    """A nominated bank can be deleted; the preference must not block it
    or cascade. The fixture runs with foreign_keys=ON, so a FK here
    would make the insert fail."""
    _full_runner(fresh_conn).apply_pending()

    fk_targets = {
        r["from"]
        for r in fresh_conn.execute("PRAGMA foreign_key_list(user_preferences)")
    }
    assert "pane_default_source_id" not in fk_targets

    fresh_conn.execute(
        "INSERT INTO user_preferences (user_id, pane_default_source_id) "
        "VALUES (1, 424242)"
    )
    fresh_conn.commit()
    row = fresh_conn.execute(
        "SELECT pane_default_source_id FROM user_preferences"
    ).fetchone()
    assert row[0] == 424242


def test_rerun_is_idempotent(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    before_sources = get_column_names(fresh_conn, "question_sources")
    before_prefs = get_column_names(fresh_conn, "user_preferences")

    for module in PANE_MODULES:
        module.upgrade(fresh_conn)  # must not raise on a migrated DB
    fresh_conn.commit()

    assert get_column_names(fresh_conn, "question_sources") == before_sources
    assert get_column_names(fresh_conn, "user_preferences") == before_prefs


def test_carried_over_database_with_v11_to_v14_stamped_still_migrates(fresh_conn):
    """The reason for the numbering gap, exercised.

    A profile that ran the capture feature branch has v11-v14 in its
    ledger. The runner skips stamped versions, so the pane migrations
    must sit above 14 to run on that database at all.
    """
    _runner_through_v10(fresh_conn).apply_pending()
    for version, name in ((11, "capture_a"), (12, "capture_b"),
                          (13, "capture_c"), (14, "capture_d")):
        _stamp(fresh_conn, version, name)

    applied = _full_runner(fresh_conn).apply_pending()

    assert applied[:3] == [15, 16, 17]
    assert SOURCE_COLUMNS <= get_column_names(fresh_conn, "question_sources")
    assert PREF_COLUMNS <= get_column_names(fresh_conn, "user_preferences")
    assert {11, 12, 13, 14, 15, 16, 17} <= _ledger_versions(fresh_conn)


def test_upgrade_noop_on_bare_database():
    """Defensive guard: neither table exists, nothing is created or raised."""
    conn = sqlite3.connect(":memory:")
    try:
        for module in PANE_MODULES:
            module.upgrade(conn)
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "question_sources" not in tables
        assert "user_preferences" not in tables
    finally:
        conn.close()


def test_fresh_user_database_reaches_v17(legacy_user_db_path):
    """The UserDatabase adoption path applies everything, pane columns included."""
    conn = sqlite3.connect(legacy_user_db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert {15, 16, 17} <= _ledger_versions(conn)
        assert SOURCE_COLUMNS <= get_column_names(conn, "question_sources")
        assert PREF_COLUMNS <= get_column_names(conn, "user_preferences")
    finally:
        conn.close()
