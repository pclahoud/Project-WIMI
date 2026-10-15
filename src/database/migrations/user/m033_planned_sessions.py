"""User DB migration v33 — planned sessions, session templates, exam colour (#778).

Wave 0 of ``docs/planning/CALENDAR_SCHEDULING_IMPLEMENTATION_PLAN.md``.

Why a separate table and not a status on ``review_sessions``
------------------------------------------------------------
``review_sessions.total_questions`` is ``NOT NULL CHECK (> 0)`` and
``total_incorrect`` is ``NOT NULL``; neither is known when a session is only
planned, so reusing that table means rebuilding the table every entry
references. And ``get_analytics_overview``'s ``total_sessions`` counts rows
of ``review_sessions``, so a planned-but-empty row would inflate analytics
on day one and every one of roughly ten readers would need a predicate.
This table is additive and links back with one nullable FK.

Owner decisions that shaped the schema (2026-10-12, #778 comments #10729
and #10743):

- **Exam-less plans are allowed**, so ``exam_context_id`` is nullable and the
  table carries ``user_id`` for scoping. ``rehome_user_rows`` (#776) reads the
  table list from ``sqlite_master`` on install, so the column is rehomed
  with the others.
- **Weekly recurrence in v1.** ``recurrence_rule`` holds an RFC 5545 RRULE
  subset on a *series* row; occurrences are expanded on read and never
  stored, except that an occurrence the student starts, skips or edits gets
  its own row with ``recurrence_parent_id`` set. See
  ``domains/_calendar_recurrence.py``.
- **Templates in v1**: ``session_templates``, with a partial unique index
  over active rows rather than a table UNIQUE, so archiving frees the name
  (#244's lesson; NULL exam is coalesced so exam-less names are unique too).
- **A chosen colour per exam**: ``exam_contexts.color_hex``, nullable.

``planned_date`` is the student's LOCAL calendar day (#286), written by
Python and never defaulted by ``date('now')``, which is UTC.
``planned_start_time`` is a local wall-clock ``HH:MM``. The ``*_at`` columns
are UTC instants like every other table's. ``uid`` is minted once at insert
and is the iCal UID, so a re-export does not duplicate events.

Idempotent: ``CREATE ... IF NOT EXISTS`` and ``add_column_if_missing``.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 33
NAME = "planned_sessions"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS session_templates (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id                  INTEGER NOT NULL,
            exam_context_id          INTEGER REFERENCES exam_contexts(id) ON DELETE CASCADE,
            question_source_id       INTEGER REFERENCES question_sources(id) ON DELETE SET NULL,
            name                     TEXT NOT NULL CHECK (length(trim(name)) > 0),
            default_start_time       TEXT CHECK (default_start_time IS NULL
                                                 OR default_start_time GLOB '[0-2][0-9]:[0-5][0-9]'),
            default_duration_minutes INTEGER CHECK (default_duration_minutes IS NULL
                                                    OR default_duration_minutes BETWEEN 1 AND 1440),
            default_questions        INTEGER CHECK (default_questions IS NULL OR default_questions > 0),
            notes                    TEXT,
            is_active                INTEGER NOT NULL DEFAULT 1,
            created_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_session_templates_active_name
            ON session_templates (user_id, COALESCE(exam_context_id, 0), name)
            WHERE is_active = 1;

        CREATE TRIGGER IF NOT EXISTS tr_session_templates_updated_at
            AFTER UPDATE ON session_templates FOR EACH ROW
            WHEN NEW.updated_at = OLD.updated_at
        BEGIN
            UPDATE session_templates SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END;

        CREATE TABLE IF NOT EXISTS planned_sessions (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            uid                      TEXT NOT NULL UNIQUE,
            user_id                  INTEGER NOT NULL,
            exam_context_id          INTEGER REFERENCES exam_contexts(id) ON DELETE CASCADE,
            question_source_id       INTEGER REFERENCES question_sources(id) ON DELETE SET NULL,
            template_id              INTEGER REFERENCES session_templates(id) ON DELETE SET NULL,
            goal_id                  INTEGER REFERENCES user_goals(id) ON DELETE SET NULL,
            review_session_id        INTEGER REFERENCES review_sessions(id) ON DELETE SET NULL,
            recurrence_rule          TEXT,
            recurrence_parent_id     INTEGER REFERENCES planned_sessions(id) ON DELETE CASCADE,
            title                    TEXT,
            planned_date             DATE NOT NULL,
            planned_start_time       TEXT CHECK (planned_start_time IS NULL
                                                 OR planned_start_time GLOB '[0-2][0-9]:[0-5][0-9]'),
            planned_duration_minutes INTEGER CHECK (planned_duration_minutes IS NULL
                                                    OR planned_duration_minutes BETWEEN 1 AND 1440),
            planned_questions        INTEGER CHECK (planned_questions IS NULL OR planned_questions > 0),
            notes                    TEXT,
            status                   TEXT NOT NULL DEFAULT 'planned'
                                     CHECK (status IN ('planned', 'started', 'skipped', 'cancelled')),
            started_at               TIMESTAMP,
            created_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            -- A series row and a plain row are told apart by recurrence_rule;
            -- an occurrence row names its series and carries no rule itself.
            CHECK (recurrence_rule IS NULL OR recurrence_parent_id IS NULL)
        );

        CREATE INDEX IF NOT EXISTS idx_planned_sessions_user_date
            ON planned_sessions (user_id, planned_date);
        CREATE INDEX IF NOT EXISTS idx_planned_sessions_review
            ON planned_sessions (review_session_id) WHERE review_session_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_planned_sessions_occurrence
            ON planned_sessions (recurrence_parent_id, planned_date)
            WHERE recurrence_parent_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_planned_sessions_due
            ON planned_sessions (user_id, status, planned_date) WHERE status = 'planned';

        CREATE TRIGGER IF NOT EXISTS tr_planned_sessions_updated_at
            AFTER UPDATE ON planned_sessions FOR EACH ROW
            WHEN NEW.updated_at = OLD.updated_at
        BEGIN
            UPDATE planned_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END;
        """
    )
    # Owner decision 9: a chosen colour per exam. Nullable; an exam with no
    # colour falls back to the calendar's series slots.
    add_column_if_missing(conn, "exam_contexts", "color_hex", "TEXT")
