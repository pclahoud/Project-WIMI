"""Tests for user-DB migration v10 (default tag definitions backfill).

Step 1 of the Error Type Management plan. Verifies that seeded default
error-type names with NULL descriptions get backfilled, that re-running
is idempotent, and that user-authored descriptions are never clobbered.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner, build_migration
from database.migrations.user import MIGRATIONS, m010_default_tag_definitions
from database.migrations.user.m010_default_tag_definitions import DEFAULT_DEFINITIONS


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    """Runner over the real registry (m001..m010)."""
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v9(conn: sqlite3.Connection) -> MigrationRunner:
    """Runner stopping just before m010 — simulates a pre-m010 database."""
    return MigrationRunner(
        conn,
        registry=[m for m in MIGRATIONS if m.version < 10],
        scope="user",
    )


def _insert_tag(
    conn: sqlite3.Connection,
    tag_name: str,
    description: str | None = None,
    exam_context: str = "TESTEXAM",
) -> int:
    cur = conn.execute(
        "INSERT INTO tags (exam_context, tag_name, description) VALUES (?, ?, ?)",
        (exam_context, tag_name, description),
    )
    conn.commit()
    return cur.lastrowid


def _description_of(conn: sqlite3.Connection, tag_id: int) -> str | None:
    row = conn.execute(
        "SELECT description FROM tags WHERE id = ?", (tag_id,)
    ).fetchone()
    return row["description"]


# ---------------------------------------------------------------- tests


def test_registry_contains_v10():
    """m010 is registered, named, and the v8 gap is preserved."""
    versions = [m.version for m in MIGRATIONS]
    assert 10 in versions
    assert 8 not in versions  # reserved for m008_assessments (branch)
    v10 = next(m for m in MIGRATIONS if m.version == 10)
    assert v10.name == "default_tag_definitions"


def test_fills_null_descriptions_for_known_names(fresh_conn):
    """Pre-m010 DB with NULL-description seeded names → backfilled."""
    _runner_through_v9(fresh_conn).apply_pending()
    gap_id = _insert_tag(fresh_conn, "Knowledge Gap")
    group_id = _insert_tag(fresh_conn, "Test Strategy")

    m010_default_tag_definitions.upgrade(fresh_conn)
    fresh_conn.commit()

    assert _description_of(fresh_conn, gap_id) == DEFAULT_DEFINITIONS["Knowledge Gap"]
    assert _description_of(fresh_conn, group_id) == DEFAULT_DEFINITIONS["Test Strategy"]


def test_backfill_applies_via_runner(fresh_conn):
    """The registry path (apply_pending) performs the same backfill."""
    _runner_through_v9(fresh_conn).apply_pending()
    gap_id = _insert_tag(fresh_conn, "Second-Guessing")

    _full_runner(fresh_conn).apply_pending()

    assert (
        _description_of(fresh_conn, gap_id)
        == DEFAULT_DEFINITIONS["Second-Guessing"]
    )
    # Ledger stamped at v10.
    row = fresh_conn.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()
    assert row[0] == 10


def test_rerun_is_idempotent(fresh_conn):
    """Running upgrade() again changes nothing."""
    _runner_through_v9(fresh_conn).apply_pending()
    gap_id = _insert_tag(fresh_conn, "Misread Question")

    m010_default_tag_definitions.upgrade(fresh_conn)
    fresh_conn.commit()
    first = _description_of(fresh_conn, gap_id)

    m010_default_tag_definitions.upgrade(fresh_conn)
    fresh_conn.commit()
    second = _description_of(fresh_conn, gap_id)

    assert first == second == DEFAULT_DEFINITIONS["Misread Question"]


def test_user_edited_description_untouched(fresh_conn):
    """A pre-set description on a seeded name is never clobbered."""
    _runner_through_v9(fresh_conn).apply_pending()
    edited_id = _insert_tag(
        fresh_conn, "Careless Mistake", description="my own words about this"
    )

    m010_default_tag_definitions.upgrade(fresh_conn)
    fresh_conn.commit()

    assert _description_of(fresh_conn, edited_id) == "my own words about this"


def test_unknown_tag_names_untouched(fresh_conn):
    """User-created tags outside the default set keep their NULL."""
    _runner_through_v9(fresh_conn).apply_pending()
    custom_id = _insert_tag(fresh_conn, "My Custom Error Type")

    m010_default_tag_definitions.upgrade(fresh_conn)
    fresh_conn.commit()

    assert _description_of(fresh_conn, custom_id) is None


def test_backfills_across_all_exam_contexts(fresh_conn):
    """Matching is by name — seeded rows in every context get filled."""
    _runner_through_v9(fresh_conn).apply_pending()
    a = _insert_tag(fresh_conn, "Time Pressure", exam_context="EXAM_A")
    b = _insert_tag(fresh_conn, "Time Pressure", exam_context="EXAM_B")

    m010_default_tag_definitions.upgrade(fresh_conn)
    fresh_conn.commit()

    expected = DEFAULT_DEFINITIONS["Time Pressure"]
    assert _description_of(fresh_conn, a) == expected
    assert _description_of(fresh_conn, b) == expected


def test_upgrade_noop_without_tags_table():
    """Defensive guard: isolated run against a bare DB does nothing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        m010_default_tag_definitions.upgrade(conn)  # must not raise
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "tags" not in tables
    finally:
        conn.close()


def test_definitions_cover_expected_seed_set():
    """The frozen map covers exactly the 5 groups + 16 seeded types."""
    assert len(DEFAULT_DEFINITIONS) == 21
    for name, definition in DEFAULT_DEFINITIONS.items():
        assert isinstance(definition, str) and definition.strip(), name
