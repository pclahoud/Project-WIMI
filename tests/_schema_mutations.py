"""Named structural mutations of a real WIMI user database (#593).

Tests build every "foreign" database at runtime: a real one, then one named
change applied here. No crafted database is committed. ``master`` is mirrored
publicly, and a binary fixture can't be reviewed by reading it. Every value
written is benign; what these mutations change is the DDL, which is what the
structure check is about.
"""
from __future__ import annotations

import re
import sqlite3


def redeclare(conn: sqlite3.Connection, table: str, old: str, new: str) -> None:
    """Rebuild ``table`` with ``old`` replaced by ``new`` in its CREATE text.

    This is what a file built by something other than WIMI looks like: same
    rows, same ``schema_migrations``, different table definition. Indexes and
    triggers on the table are put back afterwards, so the change named is the
    only structural difference.
    """
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,)).fetchone()[0]
    assert sql.count(old) == 1, (
        f"{old!r} occurs {sql.count(old)} times in {table}'s DDL; the "
        f"mutation must name exactly one place")
    dependants = [r[0] for r in conn.execute(
        "SELECT sql FROM sqlite_master WHERE tbl_name = ? AND type IN "
        "('index', 'trigger') AND sql IS NOT NULL", (table,))]
    # After one rebuild SQLite stores the renamed header quoted
    # ("user_preferences"), so a second mutation of the same table must
    # match either spelling.
    rebuilt, found = re.subn(
        rf'CREATE TABLE\s+["`]?{table}["`]?', f'CREATE TABLE _mutated_{table}',
        sql.replace(old, new), count=1)
    assert found == 1, "CREATE TABLE header not found"
    conn.execute('PRAGMA foreign_keys = OFF')
    conn.execute('PRAGMA legacy_alter_table = ON')
    conn.execute(rebuilt)
    conn.execute(f'INSERT INTO _mutated_{table} SELECT * FROM {table}')
    conn.execute(f'DROP TABLE {table}')
    conn.execute(f'ALTER TABLE _mutated_{table} RENAME TO {table}')
    for statement in dependants:
        conn.execute(statement)
    conn.commit()


def drop_alias_type_check(conn: sqlite3.Connection) -> None:
    """#593 variant A: ``subject_aliases.alias_type`` loses its CHECK."""
    redeclare(conn, 'subject_aliases',
              "CHECK (alias_type IN ('eponym', 'acronym', 'alternate_name', "
              "'colloquial'))", '')


def alias_id_as_text(conn: sqlite3.Connection) -> None:
    """#593 variant D: ``subject_aliases.id`` declared ``TEXT PRIMARY KEY``."""
    redeclare(conn, 'subject_aliases',
              'id INTEGER PRIMARY KEY AUTOINCREMENT', 'id TEXT PRIMARY KEY')


def add_trigger(conn: sqlite3.Connection) -> None:
    """A trigger WIMI never creates, on one of WIMI's tables."""
    conn.execute(
        "CREATE TRIGGER mutation_trigger AFTER INSERT ON subject_aliases "
        "BEGIN UPDATE subject_aliases SET usage_count = 0 "
        "WHERE id = NEW.id; END")
    conn.commit()


def add_view(conn: sqlite3.Connection) -> None:
    """A view WIMI never creates."""
    conn.execute("CREATE VIEW mutation_view AS SELECT id FROM subject_aliases")
    conn.commit()


def add_unread_extras(conn: sqlite3.Connection) -> None:
    """What the AI-capture builds left in real databases: additions only.

    Measured on a database built from ``archive/ai-capture`` and migrated
    forward: two extra tables, extra columns on WIMI's tables, and extra
    indexes, while nothing WIMI declares is changed.
    """
    conn.execute("CREATE TABLE capture_profiles (id INTEGER PRIMARY KEY, "
                 "name TEXT)")
    conn.execute("ALTER TABLE question_entries ADD COLUMN needs_reflection "
                 "INTEGER DEFAULT 0")
    conn.execute("CREATE INDEX idx_entries_needs_reflection ON "
                 "question_entries(review_session_id) "
                 "WHERE needs_reflection = 1")
    conn.commit()


# The two CHECKs a profile created 2026-01-08 to 2026-03-12 lacks, as they
# appear in a fresh database's DDL. ``schema_fingerprint.LEGACY_MISSING_CHECKS``
# holds their normalised form.
LEGACY_CHECK_TEXTS = (
    'CHECK (long_break_interval_rounds >= 2 AND long_break_interval_rounds <= 10)',
    "CHECK (timer_display_size IN ('normal', 'large'))",
)


def drop_legacy_checks(conn: sqlite3.Connection) -> None:
    """The measured legacy gap: ``user_preferences`` without two CHECKs."""
    for text in LEGACY_CHECK_TEXTS:
        redeclare(conn, 'user_preferences', text, '')


def drop_font_scale_check(conn: sqlite3.Connection) -> None:
    """A ``user_preferences`` CHECK that NO real profile has ever lacked."""
    redeclare(conn, 'user_preferences',
              'CHECK (font_size_scale >= 0.5 AND font_size_scale <= 3.0)', '')
