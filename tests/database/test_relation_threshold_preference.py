"""The student's relation-proposal cutoff as a preference (#60, decided on #380).

0.80 by default, 0.10-0.95, stored in ``user_preferences`` (m028) so it
travels with the profile. ``update_preferences`` enforces the range; the
extraction runtime enforces the same range again where it takes the value,
and ``tests/app/test_relation_extraction_runtime.py`` asserts that the two
range definitions and the Settings slider agree.

Run with: pytest tests/database/test_relation_threshold_preference.py --no-cov -v
"""
import pytest

from database.exceptions import ValidationError
from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    db = UserDatabase(str(tmp_path / "relations.db"), user_id=1, username="rel_user")
    yield db
    db.close()


def test_a_fresh_profile_starts_at_the_decided_default(db):
    assert db.get_preferences().relation_confidence_threshold == 0.8


def test_both_ends_of_the_range_are_accepted(db):
    assert db.update_preferences(relation_confidence_threshold=0.10).relation_confidence_threshold == 0.10
    assert db.update_preferences(relation_confidence_threshold=0.95).relation_confidence_threshold == 0.95


@pytest.mark.parametrize('outside', [0.05, 0.0999, 0.951, 1.0, 0.0, -0.5])
def test_a_value_outside_the_range_is_refused_and_nothing_changes(db, outside):
    db.update_preferences(relation_confidence_threshold=0.6)
    with pytest.raises(ValidationError, match='relation_confidence_threshold'):
        db.update_preferences(relation_confidence_threshold=outside)
    assert db.get_preferences().relation_confidence_threshold == 0.6


def test_it_reaches_the_flat_settings_object_the_page_reads(db):
    """``getUserPreferences`` serves ``get_all_settings()``; the slider reads it."""
    db.update_preferences(relation_confidence_threshold=0.35)
    assert db.get_all_settings()['relation_confidence_threshold'] == 0.35


def test_update_settings_routes_it_to_user_preferences(db):
    """The page saves through ``update_settings``, which splits by store."""
    db.update_settings(relation_confidence_threshold=0.9)
    assert db.get_preferences().relation_confidence_threshold == 0.9
