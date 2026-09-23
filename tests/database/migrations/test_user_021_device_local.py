"""Tests for user-DB migration v21 (device-local settings + profile id).

m021 does two things at once because they are the same problem twice:
#126 (WIMI has no stable notion of which *device* it is on) and #129
(none of which *profile* it is looking at). Each decision below is one a
later tidy-up could quietly reverse:

- The **profile id is minted here**, in the user database, because an
  identifier living inside the thing it identifies cannot get out of step
  with it and survives ``.wimi`` export for free. The **device id is
  not** — it names a machine, lives in master's ``app_settings``, and
  this migration only creates tables *keyed by* it.
- The singleton is a ``CHECK (id = 1)``, so a second identity is an error
  at the point of the mistake.
- **No CHECK constraints on the value columns.** An out-of-range legacy
  value must be a value to clamp, not a failed migration and an app that
  will not open.
- The **handover row** exists because a migration cannot know the device
  id. It is written only for a profile that already has preferences, and
  claimed by the machine that ran the migration.
- The legacy columns are **not dropped** — dropping means rebuilding a
  table of real user data, and the guard that matters is in code.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.device_local import LEGACY_DEVICE_ID as APP_LEGACY_DEVICE_ID
from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names, get_table_names
from database.migrations.user import MIGRATIONS
from database.migrations.user.m021_device_local_settings import LEGACY_DEVICE_ID


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v20(conn: sqlite3.Connection) -> MigrationRunner:
    """A database from just before the split landed."""
    return MigrationRunner(
        conn,
        registry=[m for m in MIGRATIONS if m.version <= 20],
        scope="user",
    )


def _ledger_versions(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def _seed_preferences(conn: sqlite3.Connection, **overrides) -> None:
    conn.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    if overrides:
        sets = ", ".join(f"{k} = ?" for k in overrides)
        conn.execute(
            f"UPDATE user_preferences SET {sets} WHERE user_id = 1",
            tuple(overrides.values()),
        )


# ---------------------------------------------------------------- registry


def test_registry_has_v21_and_keeps_the_gaps():
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert 21 in versions
    # m008 is reserved for the assessments branch; v11-v14 are stamped
    # into real databases by the capture feature branch (paused, #145), and the runner
    # treats a stamped version as applied.
    for skipped in (8, 11, 12, 13, 14):
        assert skipped not in versions
    assert {m.version: m.name for m in MIGRATIONS}[21] == "device_local_settings"


def test_the_handover_sentinel_agrees_with_the_application():
    """The migration keeps its own literal; the two must still match.

    A migration is a historical record and must keep meaning what it
    meant when it was applied, so it does not import the app's constant.
    That makes drift possible, which is what this asserts against.
    """
    assert LEGACY_DEVICE_ID == APP_LEGACY_DEVICE_ID


# ---------------------------------------------------------------- schema


def test_pre_v21_database_has_none_of_the_new_tables(fresh_conn):
    _runner_through_v20(fresh_conn).apply_pending()
    tables = get_table_names(fresh_conn)
    for table in ("profile_identity", "device_settings",
                  "device_source_settings"):
        assert table not in tables


def test_apply_pending_creates_the_tables_and_stamps_the_ledger(fresh_conn):
    _runner_through_v20(fresh_conn).apply_pending()
    _full_runner(fresh_conn).apply_pending()

    tables = get_table_names(fresh_conn)
    assert {"profile_identity", "device_settings",
            "device_source_settings"} <= tables
    assert 21 in _ledger_versions(fresh_conn)


def test_every_moved_column_exists_on_device_settings(fresh_conn):
    """The device side of the split, named one by one.

    ``ankiconnect_host`` is the load-bearing one: its default
    ``localhost`` denotes a different machine on each device, which is
    why byte-identical values still must not be copied.
    """
    _full_runner(fresh_conn).apply_pending()
    cols = get_column_names(fresh_conn, "device_settings")
    for moved in (
        "pane_last_url", "pane_split_app_pct", "pane_zoom_pct",
        "ankiconnect_enabled", "anki_integration_enabled",
        "ankiconnect_host", "ankiconnect_port",
        "mcp_server_enabled", "mcp_server_port",
    ):
        assert moved in cols, moved


def test_the_legacy_columns_are_deliberately_left_in_place(fresh_conn):
    """Dropping them means rebuilding a table of real user data.

    The guard that keeps them unread is in code — they are gone from the
    ``UserPreferences`` dataclass and ``update_preferences`` refuses them
    by name — so their continued presence here is a decision, not an
    oversight.
    """
    _full_runner(fresh_conn).apply_pending()
    cols = get_column_names(fresh_conn, "user_preferences")
    assert "ankiconnect_host" in cols
    assert "pane_zoom_pct" in cols


def test_value_columns_carry_no_check_constraints(fresh_conn):
    """An out-of-range legacy value must be clampable, not fatal.

    A CHECK here would turn one odd stored number into a migration that
    raises — i.e. an app that will not open — which is a far worse
    outcome than a value the writer validates.
    """
    _full_runner(fresh_conn).apply_pending()
    sql = fresh_conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'device_settings'"
    ).fetchone()[0]
    assert "CHECK" not in sql.upper()


# ---------------------------------------------------------------- identity


def test_profile_identity_is_minted_once(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    row = fresh_conn.execute(
        "SELECT profile_uuid FROM profile_identity WHERE id = 1"
    ).fetchone()
    assert row is not None
    assert len(row[0]) == 36


def test_a_second_identity_row_is_refused_by_the_schema(fresh_conn):
    """The singleton is a schema fact, not a convention."""
    _full_runner(fresh_conn).apply_pending()
    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO profile_identity (id, profile_uuid) VALUES (2, 'x')"
        )


def test_reapplying_never_remints_the_identity(fresh_conn):
    """Re-running must not give a profile a second, different identity."""
    _full_runner(fresh_conn).apply_pending()
    first = fresh_conn.execute(
        "SELECT profile_uuid FROM profile_identity"
    ).fetchone()[0]

    from database.migrations.user import m021_device_local_settings
    m021_device_local_settings.upgrade(fresh_conn)

    rows = fresh_conn.execute("SELECT profile_uuid FROM profile_identity").fetchall()
    assert [r[0] for r in rows] == [first]


def test_two_databases_get_different_identities(fresh_conn):
    other = sqlite3.connect(":memory:")
    other.row_factory = sqlite3.Row
    try:
        _full_runner(fresh_conn).apply_pending()
        MigrationRunner(other, registry=MIGRATIONS, scope="user").apply_pending()
        a = fresh_conn.execute("SELECT profile_uuid FROM profile_identity").fetchone()[0]
        b = other.execute("SELECT profile_uuid FROM profile_identity").fetchone()[0]
        assert a != b
    finally:
        other.close()


# ---------------------------------------------------------------- handover


def test_existing_preferences_are_parked_under_the_handover_id(fresh_conn):
    _runner_through_v20(fresh_conn).apply_pending()
    _seed_preferences(
        fresh_conn,
        pane_zoom_pct=135,
        pane_split_app_pct=62,
        pane_last_url="https://desktop.example.com/q/1",
        ankiconnect_host="desktop-box",
        ankiconnect_port=9999,
        mcp_server_enabled=1,
        mcp_server_port=8123,
    )
    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        "SELECT * FROM device_settings WHERE device_id = ?", (LEGACY_DEVICE_ID,)
    ).fetchone()
    assert row is not None
    assert row["pane_zoom_pct"] == 135
    assert row["pane_split_app_pct"] == 62
    assert row["pane_last_url"] == "https://desktop.example.com/q/1"
    assert row["ankiconnect_host"] == "desktop-box"
    assert row["ankiconnect_port"] == 9999
    assert row["mcp_server_enabled"] == 1
    assert row["mcp_server_port"] == 8123


def test_a_fresh_profile_gets_no_handover_row(fresh_conn):
    """A brand-new profile runs this migration too.

    Seeding a handover from defaults would hand the first device a row it
    should have minted itself, and would make "this profile has never
    been configured" indistinguishable from "it was configured to the
    defaults".
    """
    _full_runner(fresh_conn).apply_pending()
    count = fresh_conn.execute(
        "SELECT COUNT(*) FROM device_settings"
    ).fetchone()[0]
    assert count == 0


def test_a_null_legacy_value_is_repaired_rather_than_fatal(fresh_conn):
    """A NOT NULL device column must not reject a nullable legacy value.

    ``user_preferences`` declares most of these columns nullable — only
    ``pane_zoom_pct`` gained a NOT NULL, in m016 — so an old profile can
    legitimately hold a NULL where ``device_settings`` will not. Refusing
    it would mean a migration that raises, i.e. an app that will not
    open, over a value with a perfectly good default.
    """
    _runner_through_v20(fresh_conn).apply_pending()
    _seed_preferences(fresh_conn)
    fresh_conn.execute(
        "UPDATE user_preferences SET ankiconnect_host = NULL, "
        "ankiconnect_port = NULL, ankiconnect_enabled = NULL, "
        "anki_integration_enabled = NULL, mcp_server_enabled = NULL, "
        "mcp_server_port = NULL WHERE user_id = 1"
    )
    _full_runner(fresh_conn).apply_pending()

    row = fresh_conn.execute(
        "SELECT * FROM device_settings WHERE device_id = ?", (LEGACY_DEVICE_ID,)
    ).fetchone()
    assert row["ankiconnect_host"] == "localhost"
    assert row["ankiconnect_port"] == 8765
    assert row["ankiconnect_enabled"] == 0
    assert row["anki_integration_enabled"] == 0
    assert row["mcp_server_enabled"] == 0
    assert row["mcp_server_port"] == 8000


def test_only_touched_sources_are_carried_over(fresh_conn):
    """A source at its defaults carries no per-device state worth moving."""
    _runner_through_v20(fresh_conn).apply_pending()
    fresh_conn.execute(
        "INSERT INTO question_sources (id, user_id, source_name, url) "
        "VALUES (1, 1, 'Untouched', 'https://a.example')"
    )
    fresh_conn.execute(
        "INSERT INTO question_sources "
        "(id, user_id, source_name, url, pane_last_opened_at) "
        "VALUES (2, 1, 'Opened', 'https://b.example', '2026-01-01 10:00:00.100')"
    )
    fresh_conn.execute(
        "INSERT INTO question_sources "
        "(id, user_id, source_name, url, pane_desktop_site) "
        "VALUES (3, 1, 'Mobile', 'https://c.example', 0)"
    )
    _full_runner(fresh_conn).apply_pending()

    carried = {
        r[0]: r
        for r in fresh_conn.execute(
            "SELECT source_id, pane_desktop_site, pane_last_opened_at "
            "FROM device_source_settings WHERE device_id = ?",
            (LEGACY_DEVICE_ID,),
        )
    }
    assert set(carried) == {2, 3}
    assert carried[2]["pane_last_opened_at"] == "2026-01-01 10:00:00.100"
    assert carried[3]["pane_desktop_site"] == 0


def test_migration_is_idempotent(fresh_conn):
    _runner_through_v20(fresh_conn).apply_pending()
    _seed_preferences(fresh_conn, pane_zoom_pct=150)
    _full_runner(fresh_conn).apply_pending()

    from database.migrations.user import m021_device_local_settings
    m021_device_local_settings.upgrade(fresh_conn)

    rows = fresh_conn.execute("SELECT * FROM device_settings").fetchall()
    assert len(rows) == 1
    assert rows[0]["pane_zoom_pct"] == 150
