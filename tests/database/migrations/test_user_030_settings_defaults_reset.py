"""Tests for user-DB migration v30 -- resetting two never-read preferences.

No schema change. One unconditional ``UPDATE`` over ``user_preferences``, for
the owner's #504 decision: every row's ``analytics_detail_level`` becomes
``'advanced'`` and every row's ``manual_break_control`` becomes ``0``.

Why it exists at all: #504 makes seven dead Settings controls live, which turns
two columns holding inert values into columns that decide what a student sees.
Both hold what m001's DEFAULTs put there on every profile that predates #504 --
``'detailed'`` and ``1`` -- and under the new readers those mean *drop the
cross-dimension heatmap, Study Recommendations and Interaction Effects* and
*offer no break at a round's end*. Without this migration, upgrading would take
all four away silently.

Three properties are load-bearing beyond "the values changed":

* the reset is **unconditional**. A row holding a value a student chose
  deliberately is reset too. That is the decision, not an oversight --
  ``user_preferences`` has no ``updated_at``, so a deliberate ``'detailed'``
  cannot be told from an untouched one, and a conditional reset would leave the
  outcome depending on data nobody can characterise.
* it is **idempotent**, by construction rather than by a guard.
* it changes **no schema**, so nothing downstream has a new column to handle.
"""
from __future__ import annotations

import sqlite3

from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names
from database.migrations.user import (
    MIGRATIONS,
    m030_settings_defaults_reset,
)

DETAIL = "analytics_detail_level"
BREAK = "manual_break_control"


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    """Every migration up to and including v30, and no later one.

    It read the whole registry until m031 landed, and then "the last applied
    version is 30" and "changes no schema" were measuring m031 too. A test of
    one migration stops at it.
    """
    return MigrationRunner(
        conn, registry=[m for m in MIGRATIONS if m.version <= 30], scope="user")


def _runner_through_v28(conn: sqlite3.Connection) -> MigrationRunner:
    """Simulates a database from just before #504 landed."""
    return MigrationRunner(
        conn, registry=[m for m in MIGRATIONS if m.version <= 28], scope="user",
    )


def _ledger_versions(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def _prefs(conn: sqlite3.Connection):
    return conn.execute(
        f"SELECT user_id, {DETAIL}, {BREAK} FROM user_preferences ORDER BY user_id"
    ).fetchall()


def test_registry_has_v30_and_keeps_the_gaps():
    """The snapshot claim, moved here from m028's test as it instructed.

    ``max(versions)`` is held by whichever migration is newest, by exactly one
    file at a time. It is the one assertion in the suite that notices a
    migration arriving with nothing else updated.

    **A new migration will make this fail, and the fix is to MOVE these lines
    into its test, not to loosen them.** Carried m023 -> ... -> m028 -> here.

    **29 JOINS THE SKIPPED SET.** It was reserved for a parallel batch that
    finished without needing a migration, and it must stay skipped for the same
    reason m008 and m011--m014 are: the runner treats a stamped version as
    applied, so a database that has taken 30 would later apply a 29 *after* it,
    out of order. A gap costs nothing; a reused number is unrecoverable on
    databases already in the wild.
    """
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert versions[versions.index(30) - 1] == 28
    for skipped in (8, 11, 12, 13, 14, 29):
        assert skipped not in versions
    assert {m.version: m.name for m in MIGRATIONS}[30] == "settings_defaults_reset"
    # The max(versions) snapshot moved to m031's test, as instructed above.


def test_a_pre_v30_profile_holds_the_values_that_would_cost_it_four_things(fresh_conn):
    """The precondition. If m001's DEFAULTs ever change, this test says so."""
    _runner_through_v28(fresh_conn).apply_pending()
    fresh_conn.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    fresh_conn.commit()

    row = _prefs(fresh_conn)[0]
    assert row[DETAIL] == "detailed", (
        "m001's column DEFAULT is the whole reason this migration exists"
    )
    assert row[BREAK] == 1


def test_apply_pending_resets_both_and_stamps_the_ledger(fresh_conn):
    _runner_through_v28(fresh_conn).apply_pending()
    fresh_conn.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    fresh_conn.commit()

    applied = _full_runner(fresh_conn).apply_pending()

    assert applied[-1] == 30
    assert 30 in _ledger_versions(fresh_conn)
    row = _prefs(fresh_conn)[0]
    assert row[DETAIL] == "advanced"
    assert row[BREAK] == 0


def test_the_reset_is_unconditional_including_a_deliberate_choice(fresh_conn):
    """The decision, pinned so nobody "improves" it into a conditional.

    A student who picked Summary, or who ticked the break box, is reset too.
    That is deliberate: there is no ``updated_at`` on this table, so a
    deliberate ``'detailed'`` cannot be distinguished from an untouched one, and
    a reset that fired only on the old defaults would leave the outcome
    depending on data nobody can characterise.

    The cost is real and is accepted: neither value had ever taken effect, so
    no student has seen the choice honoured.
    """
    _runner_through_v28(fresh_conn).apply_pending()
    fresh_conn.executemany(
        f"INSERT INTO user_preferences (user_id, {DETAIL}, {BREAK}) VALUES (?, ?, ?)",
        [(1, "summary", 0), (2, "detailed", 1), (3, "advanced", 1)],
    )
    fresh_conn.commit()

    _full_runner(fresh_conn).apply_pending()

    rows = _prefs(fresh_conn)
    assert [r[DETAIL] for r in rows] == ["advanced", "advanced", "advanced"], (
        "every row goes to the new default, deliberate or not"
    )
    assert [r[BREAK] for r in rows] == [0, 0, 0]


def test_running_it_twice_is_free(fresh_conn):
    """Idempotent by construction -- the same write, not a guarded one."""
    _full_runner(fresh_conn).apply_pending()
    fresh_conn.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    fresh_conn.commit()

    m030_settings_defaults_reset.upgrade(fresh_conn)
    first = _prefs(fresh_conn)
    m030_settings_defaults_reset.upgrade(fresh_conn)

    assert _prefs(fresh_conn) == first


def test_it_changes_no_schema(fresh_conn):
    """A data migration. Nothing downstream gains a column to handle."""
    _runner_through_v28(fresh_conn).apply_pending()
    before = get_column_names(fresh_conn, "user_preferences")

    _full_runner(fresh_conn).apply_pending()

    assert get_column_names(fresh_conn, "user_preferences") == before


def test_an_empty_table_is_not_an_error(fresh_conn):
    """A fresh install has no preferences row when the runner reaches v30."""
    _runner_through_v28(fresh_conn).apply_pending()
    assert _prefs(fresh_conn) == []

    _full_runner(fresh_conn).apply_pending()

    assert 30 in _ledger_versions(fresh_conn)
