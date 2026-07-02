"""Shared helpers for migration ``upgrade()`` functions.

Migrations receive a raw ``sqlite3.Connection`` so they can be tested in
isolation without the full ``UserDatabase`` machinery. The functions
below cover the common patterns the existing schema code relied on
(reading ``sqlite_master``, ``PRAGMA table_info``, loading bundled SQL
schema files in both dev and frozen modes).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def get_table_names(conn: sqlite3.Connection) -> set[str]:
    """Return the set of table names in the current database."""
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cursor.fetchall()}


def get_column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names for ``table``.

    Returns an empty set if the table doesn't exist (rather than raising)
    so callers can use ``if 'foo' not in get_column_names(...)`` cleanly.
    """
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def schema_dir() -> Path:
    """Return the absolute path to the bundled SQL schema directory.

    Works in both dev mode (running from a checkout) and PyInstaller
    frozen mode (assets bundled under ``_internal/``). Mirrors the same
    detection used elsewhere in the app.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller bundle layout: <exe>/_internal/database/schema/
        base = Path(sys.executable).parent / "_internal" / "database" / "schema"
        if base.exists():
            return base
        # Fallback for one-file builds where _internal sits alongside
        return Path(sys._MEIPASS) / "database" / "schema"
    # Dev mode: src/database/schema/ relative to this file
    return Path(__file__).resolve().parent.parent / "schema"


def read_schema_file(filename: str) -> str:
    """Read a bundled ``.sql`` schema file and return its contents.

    Raises ``FileNotFoundError`` with a clear message if the file is
    missing — better to fail loud than to silently skip a migration.
    """
    path = schema_dir() / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Schema file not found: {path}. "
            f"This usually means the migrations directory wasn't bundled into the "
            f"PyInstaller build, or the schema file was renamed."
        )
    return path.read_text(encoding="utf-8")


def add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    column_def: str,
) -> bool:
    """Idempotent ``ALTER TABLE ADD COLUMN``.

    Returns ``True`` if the column was added, ``False`` if it already
    existed. Silently returns ``False`` if the table itself doesn't
    exist (matches the historical behavior of the WIMI ``_ensure_*``
    helpers, which never raised on missing tables — they were chained
    behind an existence check).

    ``column_def`` is the type + constraints, e.g. ``"INTEGER DEFAULT 0"``
    or ``"VARCHAR(50)"``. The runner concatenates ``ADD COLUMN <col> <def>``.
    """
    if table not in get_table_names(conn):
        return False
    if column in get_column_names(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")
    return True


def run_schema_script(conn: sqlite3.Connection, filename: str) -> None:
    """Execute a bundled ``.sql`` schema file via ``executescript``.

    Equivalent to ``conn.executescript(read_schema_file(filename))``.
    Schema files use ``CREATE TABLE IF NOT EXISTS`` patterns so this is
    safe to call repeatedly (the runner only calls it once per migration
    via the ``schema_migrations`` ledger).
    """
    conn.executescript(read_schema_file(filename))
