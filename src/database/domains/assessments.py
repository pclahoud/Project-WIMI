"""Psychometric assessment domain mixin.

Stage 1 of ``docs/planning/PSYCHOMETRIC_ASSESSMENT_IMPLEMENTATION_PLAN.md``.
Composed into :class:`UserDatabase` via multiple inheritance.

The mixin owns the lifecycle of a psychometric administration
(:meth:`start_assessment` / :meth:`submit_response` /
:meth:`finish_assessment`), the read-side queries
(:meth:`get_latest_scores`, :meth:`get_assessment_history`), and the
re-measurement preference surface (:meth:`set_reassessment_cadence`,
:meth:`snooze_reassessment`, :meth:`get_reassessment_status`).

Scoring math is delegated to :mod:`._assessment_scoring`; this mixin is
only concerned with persistence + lifecycle. Time math (next-due
computation, snooze advancement) is pushed down to SQL via SQLite's
``julianday`` and ``datetime`` functions so the Python side stays
timezone-agnostic.
"""
from __future__ import annotations

import math
from typing import Optional

from ..exceptions import (
    AssessmentNotFoundError,
    AssessmentAlreadyCompleteError,
    InvalidLikertResponseError,
)
from ..models import (
    AssessmentRecord,
    AssessmentResponse,
    AssessmentPreferences,
)
from ._assessment_scoring import (
    load_fixture,
    score_administration,
    validate_response,
)


class AssessmentsMixin:
    """Lifecycle + persistence for psychometric assessments."""

    # ------------------------------------------------------------- start / resume

    def start_assessment(self, instrument_version: str = "v1") -> AssessmentRecord:
        """Start a new administration, or return the in-flight one if it exists.

        Resumption-safe: if the user navigated away mid-assessment, this
        returns the same ``is_complete=0`` row rather than orphaning it.
        Lazily inserts a ``user_assessment_preferences`` row on first use.
        """
        with self.transaction():
            self.execute(
                "INSERT OR IGNORE INTO user_assessment_preferences (user_id) "
                "VALUES (?)",
                (self.user_id,),
            )
            existing = self.fetchone(
                "SELECT * FROM user_assessments "
                "WHERE user_id = ? AND is_complete = 0 "
                "ORDER BY started_at DESC LIMIT 1",
                (self.user_id,),
            )
            if existing:
                return AssessmentRecord.from_db_row(existing)
            cursor = self.execute(
                "INSERT INTO user_assessments (user_id, instrument_version) "
                "VALUES (?, ?)",
                (self.user_id, instrument_version),
            )
            new_id = cursor.lastrowid
        row = self.fetchone(
            "SELECT * FROM user_assessments WHERE id = ?",
            (new_id,),
        )
        return AssessmentRecord.from_db_row(row)

    def get_in_flight_assessment(self) -> Optional[AssessmentRecord]:
        row = self.fetchone(
            "SELECT * FROM user_assessments "
            "WHERE user_id = ? AND is_complete = 0 "
            "ORDER BY started_at DESC LIMIT 1",
            (self.user_id,),
        )
        return AssessmentRecord.from_db_row(row)

    # ------------------------------------------------------------- submit

    def submit_response(
        self,
        assessment_id: int,
        item_code: str,
        raw_response: int,
        response_time_ms: int = 0,
    ) -> None:
        """Upsert a single item response. Validates ownership, completion, and scale bounds."""
        row = self._require_owned_assessment(assessment_id)
        if row['is_complete']:
            raise AssessmentAlreadyCompleteError(
                f"Assessment {assessment_id} is already complete"
            )

        fixture = load_fixture(row['instrument_version'])
        try:
            item = fixture.item(item_code)
        except KeyError as e:
            raise InvalidLikertResponseError(
                f"Unknown item code {item_code!r} for instrument {row['instrument_version']!r}"
            ) from e
        try:
            validate_response(item, raw_response)
        except ValueError as e:
            raise InvalidLikertResponseError(str(e)) from e

        with self.transaction():
            self.execute(
                "INSERT INTO user_assessment_responses "
                "(assessment_id, item_code, raw_response, response_time_ms) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(assessment_id, item_code) DO UPDATE SET "
                "  raw_response = excluded.raw_response, "
                "  response_time_ms = excluded.response_time_ms, "
                "  answered_at = CURRENT_TIMESTAMP",
                (assessment_id, item_code, int(raw_response), int(response_time_ms or 0)),
            )

    # ------------------------------------------------------------- finish

    def finish_assessment(self, assessment_id: int) -> AssessmentRecord:
        """Compute and persist scores; advance preferences.next_due_at.

        Partial-completion safe: subscales with no responses score as
        NULL rather than zero. Both the assessment UPDATE and the
        preferences UPDATE happen in one transaction so a mid-finish
        crash never leaves ``next_due_at`` pointing at a stale time.
        """
        row = self._require_owned_assessment(assessment_id)
        if row['is_complete']:
            raise AssessmentAlreadyCompleteError(
                f"Assessment {assessment_id} is already complete"
            )

        response_rows = self.fetchall(
            "SELECT item_code, raw_response FROM user_assessment_responses "
            "WHERE assessment_id = ?",
            (assessment_id,),
        )
        responses = {r['item_code']: int(r['raw_response']) for r in response_rows}
        fixture = load_fixture(row['instrument_version'])
        scores = score_administration(responses, fixture)

        with self.transaction():
            self.execute(
                "UPDATE user_assessments SET "
                "  completed_at = CURRENT_TIMESTAMP, "
                "  completion_time_ms = CAST("
                "    (julianday(CURRENT_TIMESTAMP) - julianday(started_at)) * 86400000 AS INTEGER"
                "  ), "
                "  attention_check_pass = ?, "
                "  nfc_total = ?, "
                "  lgo_learning = ?, lgo_prove = ?, lgo_avoid = ?, "
                "  importance_exam = ?, importance_clinical = ?, "
                "  importance_mastery = ?, importance_reflection = ?, "
                "  is_complete = 1 "
                "WHERE id = ?",
                (
                    int(scores.attention_check_pass),
                    scores.nfc_total,
                    scores.lgo_learning, scores.lgo_prove, scores.lgo_avoid,
                    scores.importance_exam, scores.importance_clinical,
                    scores.importance_mastery, scores.importance_reflection,
                    assessment_id,
                ),
            )
            self.execute(
                "INSERT OR IGNORE INTO user_assessment_preferences (user_id) "
                "VALUES (?)",
                (self.user_id,),
            )
            self.execute(
                "UPDATE user_assessment_preferences SET "
                "  next_due_at = datetime("
                "    (SELECT completed_at FROM user_assessments WHERE id = ?), "
                "    '+' || cadence_days || ' days'"
                "  ) "
                "WHERE user_id = ?",
                (assessment_id, self.user_id),
            )

        final = self.fetchone(
            "SELECT * FROM user_assessments WHERE id = ?",
            (assessment_id,),
        )
        return AssessmentRecord.from_db_row(final)

    def delete_assessment(self, assessment_id: int) -> None:
        """Delete an administration. Cascades to its responses via FK."""
        self._require_owned_assessment(assessment_id)
        with self.transaction():
            self.execute(
                "DELETE FROM user_assessments WHERE id = ?",
                (assessment_id,),
            )

    # ------------------------------------------------------------- reads

    def get_latest_scores(self) -> Optional[AssessmentRecord]:
        """Most recent completed administration for this user, or None."""
        row = self.fetchone(
            "SELECT * FROM user_assessments "
            "WHERE user_id = ? AND is_complete = 1 "
            "ORDER BY completed_at DESC, id DESC LIMIT 1",
            (self.user_id,),
        )
        return AssessmentRecord.from_db_row(row)

    def get_assessment_history(self, limit: int = 50) -> list[AssessmentRecord]:
        """All completed administrations, newest first."""
        rows = self.fetchall(
            "SELECT * FROM user_assessments "
            "WHERE user_id = ? AND is_complete = 1 "
            "ORDER BY completed_at DESC, id DESC LIMIT ?",
            (self.user_id, int(limit)),
        )
        return [AssessmentRecord.from_db_row(r) for r in rows]

    def get_assessment_responses(
        self, assessment_id: int
    ) -> list[AssessmentResponse]:
        """All item responses for one administration, in answer order."""
        self._require_owned_assessment(assessment_id)
        rows = self.fetchall(
            "SELECT * FROM user_assessment_responses "
            "WHERE assessment_id = ? "
            "ORDER BY answered_at, id",
            (assessment_id,),
        )
        return [AssessmentResponse.from_db_row(r) for r in rows]

    # ------------------------------------------------------------- preferences

    def get_assessment_preferences(self) -> AssessmentPreferences:
        """Return the user's preferences row; lazily creates defaults."""
        row = self.fetchone(
            "SELECT * FROM user_assessment_preferences WHERE user_id = ?",
            (self.user_id,),
        )
        if not row:
            with self.transaction():
                self.execute(
                    "INSERT OR IGNORE INTO user_assessment_preferences (user_id) "
                    "VALUES (?)",
                    (self.user_id,),
                )
            row = self.fetchone(
                "SELECT * FROM user_assessment_preferences WHERE user_id = ?",
                (self.user_id,),
            )
        return AssessmentPreferences.from_db_row(row)

    def set_reassessment_cadence(self, cadence_days: int) -> AssessmentPreferences:
        """Change the user's cadence. Does not retroactively shift ``next_due_at``.

        CHECK constraint enforces 30 ≤ cadence ≤ 730; violations bubble up
        as ``DatabaseIntegrityError`` from the base layer.
        """
        with self.transaction():
            self.execute(
                "INSERT OR IGNORE INTO user_assessment_preferences (user_id) "
                "VALUES (?)",
                (self.user_id,),
            )
            self.execute(
                "UPDATE user_assessment_preferences SET cadence_days = ? "
                "WHERE user_id = ?",
                (int(cadence_days), self.user_id),
            )
        return self.get_assessment_preferences()

    def snooze_reassessment(self, days: int) -> AssessmentPreferences:
        """Push ``next_due_at`` forward by ``days`` and increment the counter.

        Advances from the existing ``next_due_at`` (or now if NULL), not
        from now — so successive snoozes accumulate. Stamps
        ``last_snoozed_at`` with the current time.
        """
        if not isinstance(days, int) or isinstance(days, bool):
            raise ValueError(f"snooze days must be int, got {type(days).__name__}")
        if days <= 0:
            raise ValueError(f"snooze days must be positive, got {days}")

        with self.transaction():
            self.execute(
                "INSERT OR IGNORE INTO user_assessment_preferences (user_id) "
                "VALUES (?)",
                (self.user_id,),
            )
            self.execute(
                "UPDATE user_assessment_preferences SET "
                "  snooze_count = snooze_count + 1, "
                "  last_snoozed_at = CURRENT_TIMESTAMP, "
                "  next_due_at = datetime("
                "    COALESCE(next_due_at, CURRENT_TIMESTAMP), "
                "    '+' || ? || ' days'"
                "  ) "
                "WHERE user_id = ?",
                (days, self.user_id),
            )
        return self.get_assessment_preferences()

    def get_reassessment_status(self) -> dict:
        """Snapshot of whether the user is due for re-measurement.

        Returns a dict with:

        - ``due`` (bool): True iff a completed administration exists and
          ``next_due_at <= now``. Always False when no administration
          has been completed.
        - ``next_due_at`` (ISO str or None)
        - ``days_until_due`` (int or None): positive = in the future,
          negative = overdue. ``None`` when ``next_due_at`` is NULL.
        - ``snooze_count`` (int)
        - ``has_completed_administration`` (bool): the gating signal the
          dashboard banner uses to decide whether to show at all.
        """
        prefs_row = self.fetchone(
            "SELECT "
            "  next_due_at, "
            "  snooze_count, "
            "  CASE WHEN next_due_at IS NULL THEN NULL "
            "       ELSE julianday(next_due_at) - julianday(CURRENT_TIMESTAMP) "
            "  END AS days_delta, "
            "  EXISTS(SELECT 1 FROM user_assessments "
            "         WHERE user_id = :uid AND is_complete = 1) "
            "    AS has_completed "
            "FROM user_assessment_preferences "
            "WHERE user_id = :uid",
            {"uid": self.user_id},
        )
        # If no prefs row yet, treat as "no preferences, not due".
        if not prefs_row:
            return {
                "due": False,
                "next_due_at": None,
                "days_until_due": None,
                "snooze_count": 0,
                "has_completed_administration": False,
            }
        has_completed = bool(prefs_row['has_completed'])
        next_due_at = prefs_row['next_due_at']
        days_delta = prefs_row['days_delta']
        if days_delta is None:
            days_until_due: Optional[int] = None
            due = False
        else:
            # Floor toward negative infinity: 1.5 → 1, -0.5 → -1.
            days_until_due = math.floor(days_delta)
            due = has_completed and days_delta <= 0
        return {
            "due": due,
            "next_due_at": next_due_at,
            "days_until_due": days_until_due,
            "snooze_count": int(prefs_row['snooze_count']),
            "has_completed_administration": has_completed,
        }

    # ------------------------------------------------------------- helpers

    def _require_owned_assessment(self, assessment_id: int) -> dict:
        """Fetch an assessment row, raising if missing or owned by another user."""
        row = self.fetchone(
            "SELECT * FROM user_assessments WHERE id = ?",
            (int(assessment_id),),
        )
        if not row:
            raise AssessmentNotFoundError(
                f"Assessment {assessment_id} not found"
            )
        if row['user_id'] != self.user_id:
            # Same exception type as "missing" so we don't leak ownership
            # information to callers that pass arbitrary IDs.
            raise AssessmentNotFoundError(
                f"Assessment {assessment_id} not found"
            )
        return row
