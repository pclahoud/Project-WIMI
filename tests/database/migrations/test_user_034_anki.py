"""Tests for user-DB migration v34 (the Anki integration's tables; #784 Wave 0).

Verifies the seven tables and their constraints, ON DELETE behaviour, the two
``user_preferences`` columns and their CHECKs, that the migration leaves the
refresh interval's default at 60 (owner decision 6), the deliberate absences
(no ``user_id`` column, no trigger, no view), idempotency, and the registry
snapshot moved here from m033's test.
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
)

ANKI_TABLES = {
    "anki_search_templates", "anki_question_matches", "anki_match_cards",
    "anki_cards", "anki_reviews", "anki_note_fields", "anki_field_visibility",
}


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
        ],
        scope="user",
    )


def _names(conn, kind):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type=?", (kind,))}


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


@pytest.fixture
def migrated(fresh_conn):
    _runner(fresh_conn).apply_pending()
    fresh_conn.execute("PRAGMA foreign_keys = ON")
    return fresh_conn


def _exam_and_bank(conn, exam="Exam", bank="Bank"):
    exam_id = conn.execute(
        "INSERT INTO exam_contexts (user_id, exam_name) VALUES (1, ?)", (exam,)).lastrowid
    bank_id = conn.execute(
        "INSERT INTO question_sources (user_id, source_name) VALUES (1, ?)", (bank,)).lastrowid
    return exam_id, bank_id


def test_creates_every_table_and_index(migrated):
    assert ANKI_TABLES <= _names(migrated, "table")
    assert {"idx_anki_match_cards_card", "idx_anki_cards_note"} <= _names(migrated, "index")


def test_no_anki_table_carries_a_user_id(migrated):
    """#776: rows scope through exam_contexts, so rehome_user_rows has nothing
    to do here and its pinned list of user_id tables does not move."""
    for table in ANKI_TABLES:
        assert "user_id" not in _columns(migrated, table), table


def test_no_trigger_or_view(migrated):
    """#593's fingerprint refuses triggers WIMI does not create; m034 needs none.

    Matched on the table a trigger is attached to, not on its name (#797
    review note 5): a trigger on an Anki table under any name is caught, and
    so is any view at all reading one.
    """
    triggers = [r[0] for r in migrated.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN (%s)"
        % ",".join("?" * len(ANKI_TABLES)), tuple(ANKI_TABLES))]
    views = [r[0] for r in migrated.execute(
        "SELECT name FROM sqlite_master WHERE type = 'view' AND (%s)"
        % " OR ".join("sql LIKE ?" for _ in ANKI_TABLES),
        tuple(f"%{t}%" for t in ANKI_TABLES))]
    assert triggers == [] and views == []


def test_upgrade_is_idempotent(migrated):
    m034_anki.upgrade(migrated)
    m034_anki.upgrade(migrated)
    assert ANKI_TABLES <= _names(migrated, "table")


def test_template_needs_text_and_is_unique_per_bank(migrated):
    exam_id, bank_id = _exam_and_bank(migrated)
    insert = ("INSERT INTO anki_search_templates (exam_context_id, question_source_id, template) "
              "VALUES (?, ?, ?)")
    migrated.execute(insert, (exam_id, bank_id, "tag:x::{{qid}}"))
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute(insert, (exam_id, bank_id, "tag:x::{{qid}}"))
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute(insert, (exam_id, bank_id, "   "))
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute(insert, (exam_id, bank_id, "x" * 1001))
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute(insert, (exam_id, None, "tag:y::{{qid}}"))


def test_deleting_an_exam_cascades_templates_matches_and_match_cards(migrated):
    exam_id, bank_id = _exam_and_bank(migrated)
    migrated.execute("INSERT INTO anki_search_templates (exam_context_id, question_source_id, "
                     "template) VALUES (?, ?, 't {{qid}}')", (exam_id, bank_id))
    match_id = migrated.execute(
        "INSERT INTO anki_question_matches (exam_context_id, question_source_id, question_id, "
        "last_synced_at) VALUES (?, ?, '7', '2026-10-12T00:00:00Z')", (exam_id, bank_id)).lastrowid
    migrated.execute("INSERT INTO anki_match_cards (match_id, card_id) VALUES (?, 99)", (match_id,))
    migrated.execute("DELETE FROM exam_contexts WHERE id = ?", (exam_id,))
    for table in ("anki_search_templates", "anki_question_matches", "anki_match_cards"):
        assert migrated.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


def test_a_match_is_unique_per_exam_bank_and_question(migrated):
    exam_id, bank_id = _exam_and_bank(migrated)
    other_exam, _ = _exam_and_bank(migrated, exam="Other", bank="Bank2")
    insert = ("INSERT INTO anki_question_matches (exam_context_id, question_source_id, "
              "question_id, last_synced_at) VALUES (?, ?, ?, 'now')")
    migrated.execute(insert, (exam_id, bank_id, "42"))
    migrated.execute(insert, (other_exam, bank_id, "42"))   # same qid, other exam: fine
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute(insert, (exam_id, bank_id, "42"))
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute(insert, (exam_id, bank_id, "  "))


def test_review_log_is_keyed_by_card_and_review_id(migrated):
    migrated.execute("INSERT INTO anki_reviews (card_id, review_id_ms) VALUES (1, 100)")
    migrated.execute("INSERT INTO anki_reviews (card_id, review_id_ms) VALUES (1, 200)")
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute("INSERT INTO anki_reviews (card_id, review_id_ms) VALUES (1, 100)")


def test_preference_columns_and_their_defaults(migrated):
    assert {"anki_display_mode", "anki_auto_refresh"} <= _columns(migrated, "user_preferences")
    migrated.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    row = migrated.execute(
        "SELECT anki_display_mode, anki_auto_refresh, anki_cache_refresh_interval_minutes "
        "FROM user_preferences WHERE user_id = 1").fetchone()
    # Owner decision 6: the interval's existing default (60) is kept.
    assert tuple(row) == ("card", 1, 60)


@pytest.mark.parametrize("column, bad", [("anki_display_mode", "grid"),
                                         ("anki_auto_refresh", 2)])
def test_preference_checks(migrated, column, bad):
    migrated.execute("INSERT INTO user_preferences (user_id) VALUES (1)")
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute(f"UPDATE user_preferences SET {column} = ? WHERE user_id = 1", (bad,))


def test_field_visibility_is_boolean(migrated):
    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute("INSERT INTO anki_field_visibility (model_name, field_name, visible) "
                         "VALUES ('Basic', 'Front', 2)")


# The registry snapshot moved to test_user_035_anki_relevance.py when m035
# landed (#784 Wave 5), as its docstring instructed.
