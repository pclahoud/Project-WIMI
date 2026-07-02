"""User DB migration v7 — exam_contexts gains exam-length triple columns.

Stage 4 of the Hierarchical Weight Allocation Implementation Plan
(``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``). The plan's
companion design (``HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`` §3.2)
replaces the previously-proposed ``total_questions INTEGER NOT NULL``
with a *length triple* — five columns that capture both the official
exam length and a planning baseline that the Hamilton allocator can
consume.

Adds five nullable columns to ``exam_contexts``:

1. ``length_kind TEXT CHECK(IN ('fixed','range','unknown')) NOT NULL DEFAULT 'unknown'``
   — kind enum that drives validation downstream. Existing rows default
   to ``'unknown'`` so the upgrade is purely additive: no existing
   exam-context loses any data, and the analytics/UX layers treat
   ``'unknown'`` as "show only percentages, no question counts".
2. ``length_min INTEGER`` — lower bound of the question count range.
   ``NULL`` when ``length_kind='unknown'``.
3. ``length_max INTEGER`` — upper bound of the question count range.
   ``NULL`` when ``length_kind='unknown'``.
4. ``length_typical INTEGER`` — the planning baseline integer item
   count. Hamilton consumes this; CAT exams have it but skip rounding.
5. ``length_note TEXT`` — free-form copy (e.g. ``"+13 CCS cases"``).

Cross-column validation invariants (``kind='fixed'`` ⇒
``min == max == typical``; ``kind='range'`` ⇒ ``min ≤ typical ≤ max``;
``kind='unknown'`` ⇒ all NULL) are enforced in
``ExamContextMixin.update_exam_length`` rather than via a SQLite CHECK
because SQLite cannot reference multiple columns in a single CHECK
without sacrificing the clarity of an application-layer error message.

Idempotent — every column add is gated on ``add_column_if_missing``
which is a no-op when the column is already present. Re-running the
migration body against an already-migrated DB is safe.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 7
NAME = "exam_length_triple"


def upgrade(conn: sqlite3.Connection) -> None:
    # The kind column is the discriminant; all other length columns are
    # nullable INTEGERs (TEXT for the note). Defaulting to ``'unknown'``
    # keeps existing rows valid without forcing every user to fill in
    # a value before they can use the rest of the app.
    add_column_if_missing(
        conn,
        "exam_contexts",
        "length_kind",
        "TEXT NOT NULL DEFAULT 'unknown' "
        "CHECK(length_kind IN ('fixed','range','unknown'))",
    )
    add_column_if_missing(conn, "exam_contexts", "length_min", "INTEGER")
    add_column_if_missing(conn, "exam_contexts", "length_max", "INTEGER")
    add_column_if_missing(conn, "exam_contexts", "length_typical", "INTEGER")
    add_column_if_missing(conn, "exam_contexts", "length_note", "TEXT")
