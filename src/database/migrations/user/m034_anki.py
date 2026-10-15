"""User DB migration v34 -- the Anki integration's tables (#784 Wave 0).

Plan: ``docs/planning/ANKI_INTEGRATION_IMPLEMENTATION_PLAN.md``, Data model,
as amended by the owner's fourteen decisions (#784 comment #10774).

Why these tables live in the user database
------------------------------------------
The owner chose to fold the anki-connect plugin into core so card data
travels in a ``.wimi`` and through folder sync (#784 comment #10736). The
plugin kept a per-*installation* SQLite file found from ``__file__``, so every
profile on a machine shared it while its templates keyed on a per-profile
exam id. Here everything is per profile, because it is in the profile.

What each table is, and the defect it replaces
----------------------------------------------
- ``anki_search_templates``: per (exam, question bank), bank required
  (decision 7), with foreign keys and cascade. The plugin keyed templates by
  the bank's *name*, so renaming a bank orphaned them.
- ``anki_question_matches``: what one (exam, bank, question id) found and
  when. The plugin keyed its cache by question id text alone, so the same id
  in two exams or two banks shared one row and the second read as fresh.
  Keyed on the question rather than the entry so re-logging a question in a
  later session shares one match.
- ``anki_match_cards``: which cards a match found. A card is shared between
  matches; the plugin deleted a card's reviews and fields when *one* question
  refreshed, while another still referenced it.
- ``anki_cards``: one row per card, ``cardsInfo``'s scheduling facts.
- ``anki_reviews``: **the full review log** (decision 2), one row per review,
  keyed by AnkiConnect's revlog id (epoch milliseconds, the log's own primary
  key). The memory estimates are computed from it on read.
- ``anki_note_fields``: **every field's value** (decision 3), stored per
  *note* -- the plugin stored fields once per card, duplicating a cloze
  note's fields on every sibling. Values are stored as Anki returned them and
  are untrusted content: the reader turns them into text plus image filenames
  and never renders them as HTML.
- ``anki_field_visibility``: which fields the student chose to show, per
  note type. It decides what the panel shows, not what is stored.
- ``user_preferences.anki_display_mode`` (card or note, decision 10) and
  ``anki_auto_refresh`` ("manual only" when 0). The refresh interval reuses
  the existing ``anki_cache_refresh_interval_minutes`` (v1 schema, CHECK
  1..1440, read by nothing until now) at its existing default of 60
  (decision 6): widening that CHECK to admit 0 would rebuild
  ``user_preferences``, hence the separate boolean.

What is deliberately absent
---------------------------
- **No ``user_id`` column** on any table (#776): rows scope through
  ``exam_contexts``, so ``rehome_user_rows`` has nothing to do here and
  ``test_profile_archive``'s list of user_id tables does not move.
- **No triggers and no views**: #593's fingerprint refuses any trigger WIMI
  does not create, and nothing here needs one.
- **Nothing is carried from the plugin's ``plugin_data`` rows** (decision 9:
  the plugin was privately developed, so its only user re-enters templates).
- No host column: AnkiConnect is loopback only (decision 4), and the port
  already lives in m021's ``device_settings``.

Idempotent: ``CREATE ... IF NOT EXISTS`` and ``add_column_if_missing``.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 34
NAME = "anki"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS anki_search_templates (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_context_id    INTEGER NOT NULL REFERENCES exam_contexts(id) ON DELETE CASCADE,
            question_source_id INTEGER NOT NULL REFERENCES question_sources(id) ON DELETE CASCADE,
            template           TEXT NOT NULL
                               CHECK (length(trim(template)) BETWEEN 1 AND 1000),
            created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (exam_context_id, question_source_id, template)
        );

        CREATE TABLE IF NOT EXISTS anki_question_matches (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_context_id    INTEGER NOT NULL REFERENCES exam_contexts(id) ON DELETE CASCADE,
            question_source_id INTEGER NOT NULL REFERENCES question_sources(id) ON DELETE CASCADE,
            question_id        TEXT NOT NULL CHECK (length(trim(question_id)) > 0),
            last_synced_at     TEXT NOT NULL,
            UNIQUE (exam_context_id, question_source_id, question_id)
        );

        CREATE TABLE IF NOT EXISTS anki_match_cards (
            match_id INTEGER NOT NULL REFERENCES anki_question_matches(id) ON DELETE CASCADE,
            card_id  INTEGER NOT NULL,
            PRIMARY KEY (match_id, card_id)
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS idx_anki_match_cards_card
            ON anki_match_cards (card_id);

        CREATE TABLE IF NOT EXISTS anki_cards (
            card_id    INTEGER PRIMARY KEY,
            note_id    INTEGER NOT NULL,
            deck_name  TEXT,
            model_name TEXT,
            interval   INTEGER,
            due        INTEGER,
            reps       INTEGER,
            lapses     INTEGER,
            queue      INTEGER,
            card_type  INTEGER,
            card_ord   INTEGER,
            fetched_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_anki_cards_note ON anki_cards (note_id);

        CREATE TABLE IF NOT EXISTS anki_reviews (
            card_id      INTEGER NOT NULL,
            review_id_ms INTEGER NOT NULL,
            ease         INTEGER,
            ivl          INTEGER,
            last_ivl     INTEGER,
            factor       INTEGER,
            time_ms      INTEGER,
            review_type  INTEGER,
            PRIMARY KEY (card_id, review_id_ms)
        ) WITHOUT ROWID;

        -- An ordinary rowid table on purpose, unlike the small join and key
        -- tables beside it: field values are whole HTML fields, and SQLite
        -- packs large rows badly in a WITHOUT ROWID table. Measured on a
        -- synthetic 3,118-question profile (#784 Wave 0): 36.8 MB on disk
        -- WITHOUT ROWID against 14.6 MB as a rowid table, same rows.
        CREATE TABLE IF NOT EXISTS anki_note_fields (
            note_id     INTEGER NOT NULL,
            field_name  TEXT NOT NULL,
            model_name  TEXT NOT NULL,
            field_order INTEGER NOT NULL DEFAULT 0,
            field_value TEXT,
            PRIMARY KEY (note_id, field_name)
        );

        CREATE TABLE IF NOT EXISTS anki_field_visibility (
            model_name TEXT NOT NULL,
            field_name TEXT NOT NULL,
            visible    INTEGER NOT NULL DEFAULT 1 CHECK (visible IN (0, 1)),
            PRIMARY KEY (model_name, field_name)
        ) WITHOUT ROWID;
        """
    )
    add_column_if_missing(
        conn, "user_preferences", "anki_display_mode",
        "TEXT NOT NULL DEFAULT 'card' CHECK (anki_display_mode IN ('card', 'note'))",
    )
    add_column_if_missing(
        conn, "user_preferences", "anki_auto_refresh",
        "INTEGER NOT NULL DEFAULT 1 CHECK (anki_auto_refresh IN (0, 1))",
    )
