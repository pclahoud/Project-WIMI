"""Tests for AssessmentsMixin (Stage 1).

Stage 1 of ``docs/planning/PSYCHOMETRIC_ASSESSMENT_IMPLEMENTATION_PLAN.md``.
Exercises lifecycle (start / resume / submit / finish / delete),
reverse-scoring round-trip via the live v1 fixture, partial-completion
semantics, attention-check propagation, preferences (cadence + snooze),
and ``get_reassessment_status`` gating.

Run with: pytest tests/database/test_assessments.py --no-cov -v
"""
from __future__ import annotations

import time

import pytest

from database.base_db import DatabaseIntegrityError
from database.exceptions import (
    AssessmentNotFoundError,
    AssessmentAlreadyCompleteError,
    InvalidLikertResponseError,
)
from database.models import (
    AssessmentRecord,
    AssessmentResponse,
    AssessmentPreferences,
)
from database.user_db import UserDatabase


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def db(tmp_path):
    """Construct a fully migrated UserDatabase against a tmp file."""
    db_path = tmp_path / "test_assessments.db"
    instance = UserDatabase(str(db_path), user_id=1, username="testuser")
    yield instance
    try:
        instance.close()
    except Exception:
        pass


def _all_item_codes_for_section(section_name: str) -> list[str]:
    """Read the section's item codes from the live v1 fixture."""
    from database.domains._assessment_scoring import load_fixture
    fixture = load_fixture("v1")
    return [
        it.item_code
        for s in fixture.sections if s.name == section_name
        for it in s.items
    ]


def _submit_all(db, assessment_id: int, section_name: str, raw_value: int) -> None:
    for code in _all_item_codes_for_section(section_name):
        db.submit_response(assessment_id, code, raw_value)


# ---------------------------------------------------------------- start / resume


def test_start_assessment_returns_record(db):
    rec = db.start_assessment()
    assert isinstance(rec, AssessmentRecord)
    assert rec.id > 0
    assert rec.user_id == 1
    assert rec.instrument_version == "v1"
    assert rec.is_complete is False
    assert rec.started_at is not None


def test_start_assessment_resumes_in_flight(db):
    first = db.start_assessment()
    second = db.start_assessment()
    assert second.id == first.id  # Same row returned, not a new one


def test_get_in_flight_assessment_returns_none_initially(db):
    assert db.get_in_flight_assessment() is None


def test_get_in_flight_assessment_returns_record_after_start(db):
    rec = db.start_assessment()
    in_flight = db.get_in_flight_assessment()
    assert in_flight is not None
    assert in_flight.id == rec.id


def test_start_lazily_creates_preferences(db):
    db.start_assessment()
    prefs = db.get_assessment_preferences()
    assert prefs.cadence_days == 180
    assert prefs.snooze_count == 0
    assert prefs.next_due_at is None  # Until finish, no due-date set


# ---------------------------------------------------------------- submit


def test_submit_response_persists(db):
    rec = db.start_assessment()
    db.submit_response(rec.id, "nfc_01", 3, response_time_ms=1500)
    responses = db.get_assessment_responses(rec.id)
    assert len(responses) == 1
    assert isinstance(responses[0], AssessmentResponse)
    assert responses[0].item_code == "nfc_01"
    assert responses[0].raw_response == 3
    assert responses[0].response_time_ms == 1500


def test_submit_response_upserts_on_repeat(db):
    rec = db.start_assessment()
    db.submit_response(rec.id, "nfc_01", 3)
    db.submit_response(rec.id, "nfc_01", 5)
    responses = db.get_assessment_responses(rec.id)
    assert len(responses) == 1
    assert responses[0].raw_response == 5


def test_submit_response_rejects_below_min(db):
    rec = db.start_assessment()
    with pytest.raises(InvalidLikertResponseError):
        db.submit_response(rec.id, "nfc_01", 0)


def test_submit_response_rejects_above_max(db):
    rec = db.start_assessment()
    with pytest.raises(InvalidLikertResponseError):
        db.submit_response(rec.id, "nfc_01", 10)


def test_submit_response_rejects_above_max_for_6pt_lgo(db):
    rec = db.start_assessment()
    with pytest.raises(InvalidLikertResponseError):
        db.submit_response(rec.id, "lgo_learning_01", 7)


def test_submit_response_rejects_above_max_for_7pt_importance(db):
    rec = db.start_assessment()
    with pytest.raises(InvalidLikertResponseError):
        db.submit_response(rec.id, "imp_exam_01", 8)


def test_submit_response_rejects_unknown_item(db):
    rec = db.start_assessment()
    with pytest.raises(InvalidLikertResponseError):
        db.submit_response(rec.id, "nfc_999", 3)


def test_submit_response_rejects_after_complete(db):
    rec = db.start_assessment()
    db.finish_assessment(rec.id)
    with pytest.raises(AssessmentAlreadyCompleteError):
        db.submit_response(rec.id, "nfc_01", 3)


def test_submit_response_rejects_unknown_assessment(db):
    with pytest.raises(AssessmentNotFoundError):
        db.submit_response(99999, "nfc_01", 3)


# ---------------------------------------------------------------- finish


def test_finish_assessment_scores_full_battery(db):
    rec = db.start_assessment()
    _submit_all(db, rec.id, "nfc", 5)
    _submit_all(db, rec.id, "lgo", 4)
    _submit_all(db, rec.id, "importance", 5)
    # Pass both attention checks
    db.submit_response(rec.id, "atc_01", 3)
    db.submit_response(rec.id, "atc_02", 4)

    finished = db.finish_assessment(rec.id)
    assert finished.is_complete is True
    assert finished.completed_at is not None
    assert finished.completion_time_ms is not None and finished.completion_time_ms >= 0
    assert finished.attention_check_pass is True
    # NFC is answered at its nine-point midpoint (5), which a reversed item
    # maps to 10 - 5 = 5, so the mean is 5.0 whatever the keying. The keying
    # itself is pinned in test_nfc_fixture_keying.py.
    assert finished.nfc_total == 5.0
    assert finished.lgo_learning == 4.0
    assert finished.lgo_prove == 4.0
    assert finished.lgo_avoid == 4.0
    assert finished.importance_exam == 5.0
    assert finished.importance_clinical == 5.0
    assert finished.importance_mastery == 5.0
    assert finished.importance_reflection == 5.0


def test_finish_assessment_partial_completion_leaves_unscored_subscales_null(db):
    rec = db.start_assessment()
    # Only NFC + only one importance subscale. NFC at its nine-point midpoint
    # (5), which a reversed item maps to 10 - 5 = 5, so 5.0 whatever the keying.
    _submit_all(db, rec.id, "nfc", 5)
    db.submit_response(rec.id, "imp_exam_01", 7)
    db.submit_response(rec.id, "imp_exam_02", 7)

    finished = db.finish_assessment(rec.id)
    assert finished.is_complete is True
    assert finished.nfc_total == 5.0
    assert finished.lgo_learning is None
    assert finished.lgo_prove is None
    assert finished.lgo_avoid is None
    assert finished.importance_exam == 7.0
    assert finished.importance_clinical is None
    assert finished.importance_mastery is None
    assert finished.importance_reflection is None
    # No attention check responses -> fail
    assert finished.attention_check_pass is False


def test_finish_assessment_advances_next_due_at(db):
    db.set_reassessment_cadence(90)
    rec = db.start_assessment()
    db.finish_assessment(rec.id)
    prefs = db.get_assessment_preferences()
    assert prefs.next_due_at is not None
    # Should be approximately 90 days after completed_at; assert via SQL
    # since we want to dodge timezone issues entirely.
    row = db.fetchone(
        "SELECT julianday(p.next_due_at) - julianday(a.completed_at) AS delta_days "
        "FROM user_assessment_preferences p, user_assessments a "
        "WHERE p.user_id = ? AND a.id = ?",
        (1, rec.id),
    )
    assert abs(row['delta_days'] - 90.0) < 0.01


def test_finish_assessment_twice_raises(db):
    rec = db.start_assessment()
    db.finish_assessment(rec.id)
    with pytest.raises(AssessmentAlreadyCompleteError):
        db.finish_assessment(rec.id)


def test_finish_assessment_unknown_raises(db):
    with pytest.raises(AssessmentNotFoundError):
        db.finish_assessment(99999)


def test_finish_assessment_attention_check_one_off_fails(db):
    rec = db.start_assessment()
    db.submit_response(rec.id, "atc_01", 5)  # Expected 2
    db.submit_response(rec.id, "atc_02", 4)
    finished = db.finish_assessment(rec.id)
    assert finished.attention_check_pass is False


# ---------------------------------------------------------------- ownership


def test_submit_to_other_users_assessment_raises(tmp_path):
    user1 = UserDatabase(str(tmp_path / "u1.db"), user_id=1, username="u1")
    rec = user1.start_assessment()
    user2 = UserDatabase(str(tmp_path / "u2.db"), user_id=2, username="u2")
    with pytest.raises(AssessmentNotFoundError):
        user2.submit_response(rec.id, "nfc_01", 3)
    user1.close()
    user2.close()


# ---------------------------------------------------------------- history reads


def test_get_latest_scores_initially_none(db):
    assert db.get_latest_scores() is None


def test_get_latest_scores_returns_most_recent_complete(db):
    rec_a = db.start_assessment()
    db.finish_assessment(rec_a.id)
    time.sleep(1.05)  # Ensure CURRENT_TIMESTAMP (second resolution) advances
    rec_b = db.start_assessment()
    db.finish_assessment(rec_b.id)
    latest = db.get_latest_scores()
    assert latest is not None
    assert latest.id == rec_b.id


def test_get_latest_scores_ignores_in_flight(db):
    db.start_assessment()  # Leave in-flight
    assert db.get_latest_scores() is None


def test_get_assessment_history_returns_newest_first(db):
    rec_a = db.start_assessment()
    db.finish_assessment(rec_a.id)
    time.sleep(1.05)
    rec_b = db.start_assessment()
    db.finish_assessment(rec_b.id)
    history = db.get_assessment_history()
    assert [h.id for h in history] == [rec_b.id, rec_a.id]


def test_get_assessment_history_respects_limit(db):
    rec = db.start_assessment()
    db.finish_assessment(rec.id)
    history = db.get_assessment_history(limit=1)
    assert len(history) == 1


# ---------------------------------------------------------------- delete


def test_delete_assessment_cascades_responses(db):
    rec = db.start_assessment()
    db.submit_response(rec.id, "nfc_01", 3)
    db.delete_assessment(rec.id)
    # Should be gone
    assert db.fetchone(
        "SELECT id FROM user_assessments WHERE id = ?", (rec.id,)
    ) is None
    assert db.fetchone(
        "SELECT id FROM user_assessment_responses WHERE assessment_id = ?",
        (rec.id,),
    ) is None


def test_delete_assessment_unknown_raises(db):
    with pytest.raises(AssessmentNotFoundError):
        db.delete_assessment(99999)


# ---------------------------------------------------------------- preferences


def test_get_assessment_preferences_returns_defaults(db):
    prefs = db.get_assessment_preferences()
    assert isinstance(prefs, AssessmentPreferences)
    assert prefs.user_id == 1
    assert prefs.cadence_days == 180
    assert prefs.snooze_count == 0
    assert prefs.next_due_at is None
    assert prefs.last_snoozed_at is None


def test_set_reassessment_cadence_round_trip(db):
    prefs = db.set_reassessment_cadence(90)
    assert prefs.cadence_days == 90
    # Re-read to confirm persistence
    assert db.get_assessment_preferences().cadence_days == 90


def test_set_reassessment_cadence_rejects_below_min(db):
    with pytest.raises(DatabaseIntegrityError):
        db.set_reassessment_cadence(29)


def test_set_reassessment_cadence_rejects_above_max(db):
    with pytest.raises(DatabaseIntegrityError):
        db.set_reassessment_cadence(731)


def test_set_reassessment_cadence_does_not_reset_next_due_at(db):
    rec = db.start_assessment()
    db.finish_assessment(rec.id)
    original_due = db.get_assessment_preferences().next_due_at
    assert original_due is not None
    db.set_reassessment_cadence(90)
    new_due = db.get_assessment_preferences().next_due_at
    # next_due_at unchanged by cadence update
    assert new_due == original_due


# ---------------------------------------------------------------- snooze


def test_snooze_increments_count_and_advances(db):
    # Finish so there's a next_due_at to advance.
    rec = db.start_assessment()
    db.finish_assessment(rec.id)
    prefs_before = db.get_assessment_preferences()
    assert prefs_before.next_due_at is not None
    assert prefs_before.snooze_count == 0

    prefs_after = db.snooze_reassessment(7)
    assert prefs_after.snooze_count == 1
    assert prefs_after.last_snoozed_at is not None

    # next_due_at should be ~7 days after the original
    row = db.fetchone(
        "SELECT julianday(?) - julianday(?) AS delta",
        (prefs_after.next_due_at.isoformat(), prefs_before.next_due_at.isoformat()),
    )
    assert abs(row['delta'] - 7.0) < 0.01


def test_snooze_accumulates_from_existing_due(db):
    rec = db.start_assessment()
    db.finish_assessment(rec.id)
    db.snooze_reassessment(7)
    prefs_after_first = db.get_assessment_preferences()
    db.snooze_reassessment(30)
    prefs_after_second = db.get_assessment_preferences()
    # Second snooze advances from the already-snoozed value, not from now.
    row = db.fetchone(
        "SELECT julianday(?) - julianday(?) AS delta",
        (prefs_after_second.next_due_at.isoformat(),
         prefs_after_first.next_due_at.isoformat()),
    )
    assert abs(row['delta'] - 30.0) < 0.01
    assert prefs_after_second.snooze_count == 2


def test_snooze_rejects_zero(db):
    with pytest.raises(ValueError):
        db.snooze_reassessment(0)


def test_snooze_rejects_negative(db):
    with pytest.raises(ValueError):
        db.snooze_reassessment(-5)


def test_snooze_before_any_finish_uses_now_as_base(db):
    # No completed assessment yet; snooze should still work and stamp
    # next_due_at relative to "now".
    prefs_after = db.snooze_reassessment(7)
    assert prefs_after.next_due_at is not None
    assert prefs_after.snooze_count == 1


# ---------------------------------------------------------------- status


def test_get_reassessment_status_no_administration(db):
    status = db.get_reassessment_status()
    assert status["due"] is False
    assert status["has_completed_administration"] is False
    assert status["next_due_at"] is None
    assert status["days_until_due"] is None
    assert status["snooze_count"] == 0


def test_get_reassessment_status_after_complete_with_future_due(db):
    db.set_reassessment_cadence(180)
    rec = db.start_assessment()
    db.finish_assessment(rec.id)
    status = db.get_reassessment_status()
    assert status["has_completed_administration"] is True
    assert status["due"] is False
    assert status["next_due_at"] is not None
    # 180 days from now -> roughly 179 or 180 depending on second-precision
    assert 178 <= status["days_until_due"] <= 180


def test_get_reassessment_status_when_overdue(db):
    rec = db.start_assessment()
    db.finish_assessment(rec.id)
    # Force next_due_at into the past
    db.execute(
        "UPDATE user_assessment_preferences SET "
        "  next_due_at = datetime(CURRENT_TIMESTAMP, '-3 days') "
        "WHERE user_id = ?",
        (1,),
    )
    db.conn.commit()
    status = db.get_reassessment_status()
    assert status["due"] is True
    assert status["days_until_due"] == -3 or status["days_until_due"] == -4
    assert status["has_completed_administration"] is True


def test_get_reassessment_status_not_due_when_no_completed_admin_even_if_snoozed(db):
    # Snooze without ever finishing — banner should not trigger.
    db.snooze_reassessment(7)
    # Force next_due_at into the past to simulate "would otherwise be due"
    db.execute(
        "UPDATE user_assessment_preferences SET "
        "  next_due_at = datetime(CURRENT_TIMESTAMP, '-1 days') "
        "WHERE user_id = ?",
        (1,),
    )
    db.conn.commit()
    status = db.get_reassessment_status()
    assert status["has_completed_administration"] is False
    assert status["due"] is False  # Gated by has_completed_administration


# ---------------------------------------------------------------- composition


def test_mixin_composes_into_user_database(db):
    """Sanity: the mixin's methods are actually on the composed instance."""
    assert hasattr(db, "start_assessment")
    assert hasattr(db, "submit_response")
    assert hasattr(db, "finish_assessment")
    assert hasattr(db, "get_latest_scores")
    assert hasattr(db, "get_reassessment_status")
