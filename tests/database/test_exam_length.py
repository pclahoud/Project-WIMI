"""Tests for the Stage 4 exam-length triple operations.

Covers ``ExamContextMixin.update_exam_length`` /  ``get_exam_length`` /
``seed_known_exam_lengths`` validation invariants and idempotency. See
``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`` §3.2 for the
canonical design and ``WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md`` Stage
4 for the implementation scope.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from database.base_db import BaseDatabaseError
from database.user_db import UserDatabase
from database.domains.exam_contexts import KNOWN_EXAM_LENGTHS


@pytest.fixture
def user_db(tmp_path: Path) -> UserDatabase:
    """Spin up an isolated UserDatabase with all migrations applied."""
    db_path = tmp_path / "user_001_test.db"
    db = UserDatabase(db_path=db_path, user_id=1, username="tester")
    yield db
    try:
        db.close()
    except Exception:
        pass


@pytest.fixture
def exam_id(user_db: UserDatabase) -> int:
    ctx = user_db.create_exam_context(
        exam_name="USMLE Step 1",
        exam_description="Stage 4 fixture exam",
    )
    return ctx.id


# ---------------------------------------------------------------- validation


def test_update_fixed_requires_min_eq_max_eq_typical(user_db, exam_id):
    """kind='fixed' must have min == max == typical."""
    user_db.update_exam_length(exam_id, 'fixed', 280, 280, 280, None)
    length = user_db.get_exam_length(exam_id)
    assert length == {
        'kind': 'fixed', 'min': 280, 'max': 280, 'typical': 280, 'note': None,
    }


def test_update_fixed_rejects_mismatched_values(user_db, exam_id):
    with pytest.raises(BaseDatabaseError, match="min == max == typical"):
        user_db.update_exam_length(exam_id, 'fixed', 280, 290, 280, None)
    with pytest.raises(BaseDatabaseError, match="min == max == typical"):
        user_db.update_exam_length(exam_id, 'fixed', 280, 280, 285, None)


def test_update_fixed_rejects_missing_value(user_db, exam_id):
    with pytest.raises(BaseDatabaseError, match="length_min, length_max"):
        user_db.update_exam_length(exam_id, 'fixed', None, 280, 280, None)
    with pytest.raises(BaseDatabaseError, match="length_min, length_max"):
        user_db.update_exam_length(exam_id, 'fixed', 280, None, 280, None)


def test_update_range_requires_min_le_typical_le_max(user_db, exam_id):
    """kind='range' invariant: min <= typical <= max."""
    user_db.update_exam_length(exam_id, 'range', 85, 150, 100, "CAT")
    length = user_db.get_exam_length(exam_id)
    assert length == {
        'kind': 'range', 'min': 85, 'max': 150, 'typical': 100, 'note': "CAT",
    }


def test_update_range_rejects_typical_below_min(user_db, exam_id):
    with pytest.raises(BaseDatabaseError, match="min <= typical <= max"):
        user_db.update_exam_length(exam_id, 'range', 85, 150, 80, None)


def test_update_range_rejects_typical_above_max(user_db, exam_id):
    with pytest.raises(BaseDatabaseError, match="min <= typical <= max"):
        user_db.update_exam_length(exam_id, 'range', 85, 150, 200, None)


def test_update_range_rejects_missing_value(user_db, exam_id):
    with pytest.raises(BaseDatabaseError, match="length_min, length_max"):
        user_db.update_exam_length(exam_id, 'range', None, 150, 100, None)


def test_update_unknown_requires_all_null(user_db, exam_id):
    """kind='unknown' enforces all three numeric fields are NULL."""
    user_db.update_exam_length(exam_id, 'unknown', None, None, None, None)
    length = user_db.get_exam_length(exam_id)
    assert length == {
        'kind': 'unknown', 'min': None, 'max': None, 'typical': None, 'note': None,
    }


def test_update_unknown_rejects_populated_value(user_db, exam_id):
    with pytest.raises(BaseDatabaseError, match="all be NULL"):
        user_db.update_exam_length(exam_id, 'unknown', 100, None, None, None)
    with pytest.raises(BaseDatabaseError, match="all be NULL"):
        user_db.update_exam_length(exam_id, 'unknown', None, None, 100, None)


def test_update_invalid_kind(user_db, exam_id):
    with pytest.raises(BaseDatabaseError, match="Invalid length_kind"):
        user_db.update_exam_length(exam_id, 'parasonic', 100, 100, 100, None)


def test_update_unknown_exam_context_raises(user_db):
    with pytest.raises(BaseDatabaseError, match="not found"):
        user_db.update_exam_length(99999, 'unknown', None, None, None, None)


def test_get_unknown_exam_context_raises(user_db):
    with pytest.raises(BaseDatabaseError, match="not found"):
        user_db.get_exam_length(99999)


# ---------------------------------------------------------------- defaults


def test_get_returns_unknown_for_freshly_created(user_db, exam_id):
    """New exam_contexts default to length_kind='unknown'."""
    length = user_db.get_exam_length(exam_id)
    assert length == {
        'kind': 'unknown', 'min': None, 'max': None, 'typical': None, 'note': None,
    }


def test_exam_context_config_includes_length_fields(user_db, exam_id):
    """get_exam_context_config now returns the length fields."""
    user_db.update_exam_length(exam_id, 'fixed', 280, 280, 280, None)
    config = user_db.get_exam_context_config(exam_id)
    assert config.length_kind == 'fixed'
    assert config.length_min == 280
    assert config.length_max == 280
    assert config.length_typical == 280
    assert config.length_note is None


# ---------------------------------------------------------------- seeder


def test_seed_known_exam_lengths_writes_fixed_for_step1(user_db):
    """Seeder fills USMLE Step 1 with the canonical 280/280/280."""
    ctx = user_db.create_exam_context(exam_name="USMLE Step 1")
    updated = user_db.seed_known_exam_lengths()
    assert updated >= 1

    length = user_db.get_exam_length(ctx.id)
    assert length['kind'] == 'fixed'
    assert length['min'] == 280
    assert length['max'] == 280
    assert length['typical'] == 280


def test_seed_known_exam_lengths_writes_range_for_nclex(user_db):
    """Seeder fills NCLEX-RN with the canonical 85/150/100 range."""
    ctx = user_db.create_exam_context(exam_name="NCLEX-RN")
    user_db.seed_known_exam_lengths()

    length = user_db.get_exam_length(ctx.id)
    assert length['kind'] == 'range'
    assert length['min'] == 85
    assert length['max'] == 150
    assert length['typical'] == 100
    assert length['note']  # non-empty note for CAT context


def test_seed_known_exam_lengths_is_idempotent(user_db):
    """Re-running the seeder does not clobber a fixed-length record."""
    ctx = user_db.create_exam_context(exam_name="USMLE Step 1")

    # First run writes the canonical values.
    first = user_db.seed_known_exam_lengths()
    assert first >= 1

    # User overrides — pretend they edited typical to 275 (within fixed
    # constraint we can't test directly, but the gate is "kind != unknown",
    # so anchoring with 'fixed' is enough to prove the seeder respects
    # existing data).
    pre = user_db.get_exam_length(ctx.id)

    # Second run should be a no-op (length_kind != 'unknown').
    second = user_db.seed_known_exam_lengths()
    post = user_db.get_exam_length(ctx.id)
    assert post == pre
    # Updated count should be 0 — the row's no longer 'unknown'.
    assert second == 0


def test_seed_known_exam_lengths_skips_custom_exam(user_db):
    """A custom exam name not in KNOWN_EXAM_LENGTHS is left as 'unknown'."""
    ctx = user_db.create_exam_context(exam_name="My Personal Custom Quiz")

    user_db.seed_known_exam_lengths()
    length = user_db.get_exam_length(ctx.id)
    assert length['kind'] == 'unknown'


def test_seed_known_exam_lengths_is_case_insensitive(user_db):
    """Exam name matching is case-insensitive."""
    ctx = user_db.create_exam_context(exam_name="usmle step 1")  # lowercase
    user_db.seed_known_exam_lengths()
    length = user_db.get_exam_length(ctx.id)
    assert length['kind'] == 'fixed'
    assert length['typical'] == 280


def test_seed_known_exam_lengths_does_not_clobber_user_edits(user_db):
    """If the user already set length_kind, the seeder leaves it alone."""
    ctx = user_db.create_exam_context(exam_name="USMLE Step 1")
    # User explicitly sets a different (non-canonical) value first.
    user_db.update_exam_length(ctx.id, 'fixed', 270, 270, 270, "Pilot exam")

    updated = user_db.seed_known_exam_lengths()
    # Seeder finds 'fixed' (not 'unknown') so it skips this row.
    assert updated == 0

    length = user_db.get_exam_length(ctx.id)
    assert length['typical'] == 270
    assert length['note'] == "Pilot exam"


# ---------------------------------------------------------------- known map


def test_get_known_exam_length_returns_canonical():
    """The static helper exposes the same map the seeder writes."""
    from database.domains.exam_contexts import ExamContextMixin

    spec = ExamContextMixin.get_known_exam_length("USMLE Step 1")
    assert spec is not None
    assert spec['kind'] == 'fixed'
    assert spec['typical'] == 280


def test_get_known_exam_length_unknown_name_returns_none():
    from database.domains.exam_contexts import ExamContextMixin
    assert ExamContextMixin.get_known_exam_length("not a real exam") is None
    assert ExamContextMixin.get_known_exam_length("") is None
    assert ExamContextMixin.get_known_exam_length(None) is None


def test_known_exam_lengths_table_well_formed():
    """Every entry in KNOWN_EXAM_LENGTHS satisfies the validation invariants."""
    for name, spec in KNOWN_EXAM_LENGTHS.items():
        assert spec['kind'] in ('fixed', 'range', 'unknown')
        if spec['kind'] == 'fixed':
            assert spec['min'] == spec['max'] == spec['typical'], (
                f"KNOWN_EXAM_LENGTHS[{name!r}] violates fixed invariant"
            )
        elif spec['kind'] == 'range':
            assert spec['min'] <= spec['typical'] <= spec['max'], (
                f"KNOWN_EXAM_LENGTHS[{name!r}] violates range invariant"
            )
