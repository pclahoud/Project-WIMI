"""Tests for user-DB migration v35 (the Anki relevance verdicts; #784 Wave 5).

Verifies the two tables, their keys and the verdict CHECK, both cascades, the
deliberate absences (no ``user_id``, no foreign key on ``card_id``, no trigger
or view), idempotency, and the registry snapshot moved here from m034's test.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner, build_migration
from database.migrations.user import (
    MIGRATIONS,
    m001_baseline,
    m002_phase6_goals,
    m003_phase7_dimensions,
    m004_subject_edges,
    m005_primary_parent_id,
    m006_subject_edge_weight_history,
    m007_exam_length_triple,
    m034_anki,
    m035_anki_relevance,
)

TABLES = {"anki_card_verdicts", "anki_card_subject_rejections"}


def _runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(
        conn,
        registry=[
            build_migration(m001_baseline),
            build_migration(m002_phase6_goals),
            build_migration(m003_phase7_dimensions),
            build_migration(m004_subject_edges),
            build_migration(m005_primary_parent_id),
            build_migration(m006_subject_edge_weight_history),
            build_migration(m007_exam_length_triple),
            build_migration(m034_anki),
            build_migration(m035_anki_relevance),
        ],
        scope="user",
    )


@pytest.fixture
def migrated(fresh_conn):
    _runner(fresh_conn).apply_pending()
    fresh_conn.execute("PRAGMA foreign_keys = ON")
    return fresh_conn


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _entry_and_subject(conn):
    """The smallest chain an entry and a subject need on the baseline schema."""
    exam = conn.execute(
        "INSERT INTO exam_contexts (user_id, exam_name) VALUES (1, 'Exam')").lastrowid
    session = conn.execute(
        "INSERT INTO review_sessions (user_id, exam_context_id, date_encountered, "
        "total_questions, total_incorrect) VALUES (1, ?, '2026-10-14', 5, 1)",
        (exam,)).lastrowid
    entry = conn.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, user_answer, "
        "correct_answer) VALUES (?, 1, 'A', 'B')", (session,)).lastrowid
    subject = conn.execute(
        "INSERT INTO subject_nodes (name, exam_context, level_type) "
        "VALUES ('Aorta', 'Exam', 'System')").lastrowid
    return entry, subject


def test_creates_both_tables(migrated):
    names = {r[0] for r in migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names


def test_no_user_id_and_no_trigger_or_view(migrated):
    for table in TABLES:
        assert "user_id" not in _columns(migrated, table), table
    for kind in ("trigger", "view"):
        assert not [r for r in migrated.execute(
            "SELECT name FROM sqlite_master WHERE type=? AND name LIKE 'anki%'", (kind,))]


def test_card_id_has_no_foreign_key(migrated):
    """A verdict outlives its card leaving the cache."""
    for table in TABLES:
        targets = {r[2] for r in migrated.execute(f"PRAGMA foreign_key_list({table})")}
        assert "anki_cards" not in targets, table


def test_upgrade_is_idempotent(migrated):
    m035_anki_relevance.upgrade(migrated)
    assert TABLES <= {r[0] for r in migrated.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def test_a_verdict_is_one_per_entry_and_card_and_checked(migrated):
    entry, _ = _entry_and_subject(migrated)
    migrated.execute("INSERT INTO anki_card_verdicts VALUES (?, 101, 'confirmed', 'now')",
                     (entry,))
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute("INSERT INTO anki_card_verdicts VALUES (?, 101, 'not_for_entry', 'now')",
                         (entry,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        migrated.execute("INSERT INTO anki_card_verdicts VALUES (?, 102, 'maybe', 'now')",
                         (entry,))


def test_deleting_the_entry_or_the_subject_cascades(migrated):
    entry, subject = _entry_and_subject(migrated)
    migrated.execute("INSERT INTO anki_card_verdicts VALUES (?, 101, 'confirmed', 'now')",
                     (entry,))
    migrated.execute("INSERT INTO anki_card_subject_rejections VALUES (?, 101, 'now')",
                     (subject,))
    migrated.execute("DELETE FROM question_entries WHERE id = ?", (entry,))
    migrated.execute("DELETE FROM subject_nodes WHERE id = ?", (subject,))
    assert migrated.execute("SELECT COUNT(*) FROM anki_card_verdicts").fetchone()[0] == 0
    assert migrated.execute("SELECT COUNT(*) FROM anki_card_subject_rejections").fetchone()[0] == 0


def test_registry_has_v35_and_keeps_the_gaps():
    """The registry snapshot, moved here from m034's test as it instructs.

    **A new migration will make this fail, and the fix is to MOVE these lines
    into its test, not to loosen them.** Carried m023 -> ... -> m034 -> here.

    m035 was reserved for #784 Wave 5 by the plan and announced on #784
    comment #11052 before it was written. 8 and 29 stay skipped for the reasons
    m032's and m030's tests record.
    """
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert versions[versions.index(35) - 1] == 34
    for skipped in (8, 11, 12, 13, 14, 29):
        assert skipped not in versions
    assert {m.version: m.name for m in MIGRATIONS}[35] == "anki_relevance"
    assert max(versions) == 35
