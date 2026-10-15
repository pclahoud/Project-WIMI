"""User DB migration v32 — psychometric assessment battery tables.

Numbered 32, not 8. This module was authored as ``m008_assessments`` on
``feat/psychometric-assessment`` (ca63e69, 2026-05-15) and renumbered when
the feature resumed (#766, 2026-10-12). By then the registry had reached
m031, and v8 is reserved: the registry's own comment records that dev
databases which checked out that branch already carry a v8 stamp, and in
any case a migration numbered below the registry's maximum applies out of
order. Nothing but the version and this note changed.

Stage 0 of the Psychometric Assessment Implementation Plan
(``docs/planning/PSYCHOMETRIC_ASSESSMENT_IMPLEMENTATION_PLAN.md``).

Adds three new tables capturing longitudinal psychometric measurements
of Need for Cognition (NFC), Learning Goal Orientation (LGO), and
Personal Importance:

1. ``user_assessments`` — one row per administration (longitudinal,
   never overwritten on re-take). Holds composite/subscale scores plus
   completion metadata and an ``instrument_version`` tag so v1 and
   future v2 administrations stay separable.
2. ``user_assessment_responses`` — one row per item per administration.
   Raw responses + per-item response time. Cascades on parent delete so
   discarding an administration cleans up its responses.
3. ``user_assessment_preferences`` — singleton per user. Re-measurement
   cadence (default 180 days, CHECK 30–730), next due timestamp, and
   snooze tracking.

Indices:

- ``idx_user_assessments_user_complete`` — supports the "latest finished
  administration" lookup powering :py:meth:`get_latest_scores`.
- ``idx_user_assessments_in_flight`` — partial index over the at-most-one
  resumable row per user; used by ``start_assessment`` to detect and
  return an in-flight administration rather than starting a fresh one.
- ``idx_responses_assessment``, ``idx_responses_by_item_code`` — support
  the response-load and per-item analytics queries.

Idempotent — uses ``CREATE TABLE IF NOT EXISTS`` and
``CREATE INDEX IF NOT EXISTS`` throughout. Re-running the upgrade body
against an already-migrated DB is a no-op.
"""
from __future__ import annotations

import sqlite3

VERSION = 32
NAME = "assessments"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_assessments (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id               INTEGER NOT NULL,
            instrument_version    TEXT NOT NULL,
            started_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at          TIMESTAMP,
            completion_time_ms    INTEGER,
            attention_check_pass  INTEGER,
            nfc_total             REAL,
            lgo_learning          REAL,
            lgo_prove             REAL,
            lgo_avoid             REAL,
            importance_exam       REAL,
            importance_clinical   REAL,
            importance_mastery    REAL,
            importance_reflection REAL,
            is_complete           INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_user_assessments_user_complete
            ON user_assessments (user_id, is_complete, completed_at DESC);

        CREATE INDEX IF NOT EXISTS idx_user_assessments_in_flight
            ON user_assessments (user_id, is_complete)
            WHERE is_complete = 0;

        CREATE TABLE IF NOT EXISTS user_assessment_responses (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_id    INTEGER NOT NULL
                             REFERENCES user_assessments(id) ON DELETE CASCADE,
            item_code        TEXT NOT NULL,
            raw_response     INTEGER NOT NULL,
            response_time_ms INTEGER,
            answered_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (assessment_id, item_code)
        );

        CREATE INDEX IF NOT EXISTS idx_responses_assessment
            ON user_assessment_responses (assessment_id, item_code);
        CREATE INDEX IF NOT EXISTS idx_responses_by_item_code
            ON user_assessment_responses (item_code);

        CREATE TABLE IF NOT EXISTS user_assessment_preferences (
            user_id         INTEGER PRIMARY KEY,
            cadence_days    INTEGER NOT NULL DEFAULT 180
                            CHECK (cadence_days BETWEEN 30 AND 730),
            next_due_at     TIMESTAMP,
            last_snoozed_at TIMESTAMP,
            snooze_count    INTEGER NOT NULL DEFAULT 0
        );
        """
    )
