"""Weight confidence is not part of the efficiency score (settled in #133).

One test per decision, in the shape of
``test_draft_policy_by_surface.py`` and
``test_subject_import_weight_semantics.py`` — and for the same reason.
Three of these decisions are enforced by an **absence**, so they are easy
to "fix" back by someone reading a docstring that no longer exists:

* ``weight_source`` does not appear in the score's arithmetic;
* neither does the range width (the old ``range_confidence``);
* and the uncertainty that remains is *rendered*, never priced in.

The bug the absences prevent: Stage 9 multiplied each subject's
**penalty** by a confidence factor, so a weight WIMI could not vouch for
produced a *smaller* penalty and therefore a *higher* score. The
``min(range_confidence, source_confidence)`` written so "the less
certain signal dominates" systematically selected whichever factor
inflated the score most. Inverting was considered and rejected in #133:
it would lower a student's score because their blueprint lacked
provenance metadata, blaming a data problem on the person.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator

import pytest

from database.master_db import MasterDatabase
from database.user_db import UserDatabase


# ==================== Fixtures ====================


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir: Path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def user_db(master_db: MasterDatabase) -> Generator[UserDatabase, None, None]:
    user = master_db.create_user(
        username="test_student",
        display_name="Test Student",
        user_types=["student"],
    )
    db = UserDatabase(
        db_path=master_db.ensure_user_database(user.id),
        user_id=user.id,
        username=user.username,
        device_id=master_db.get_device_id(),
    )
    yield db
    db.close()


# The fixture from #133's own bug report. Three subjects, no ranges,
# no ``weight_source``. Pre-Stage-9 it scored 76.0; Stage 9 made it 88.0,
# which crosses ``_get_efficiency_rating``'s ``>= 85`` boundary and
# reported a complete misallocation of study effort as "Excellent".
ISSUE_FIXTURE = [
    {'mistake_percentage': 10.0, 'exam_weight': 50.0},
    {'mistake_percentage': 50.0, 'exam_weight': 10.0},
    {'mistake_percentage': 40.0, 'exam_weight': 40.0},
]

ALL_SOURCES = (
    'official', 'user_explicit', 'user_defined', 'derived', 'user_estimate',
)


def _with_source(rows, source):
    return [dict(row, weight_source=source) for row in rows]


# ==================== the arithmetic ====================


def test_the_issue_fixture_scores_76_again(user_db):
    """`100 - Σ(deviation × weight_factor)`, with nothing else in it.

    20.0 + 4.0 + 0.0 = 24.0 penalty. This is the number
    ``test_complete_mismatch_gives_low_score`` has asserted since before
    Stage 9 existed; its ``< 80.0`` bound was never a stale threshold.
    """
    assert user_db._calculate_efficiency_score(ISSUE_FIXTURE) == 76.0


@pytest.mark.parametrize("source", ALL_SOURCES)
def test_weight_source_does_not_change_the_score(user_db, source):
    """**The regression guard.** Provenance must be inert in the score.

    The same fixture with every ``weight_source`` value, and with the
    field absent entirely, must produce one number. Reintroducing any
    per-source multiplier — in either direction — fails here.
    """
    bare = user_db._calculate_efficiency_score(ISSUE_FIXTURE)
    tagged = user_db._calculate_efficiency_score(
        _with_source(ISSUE_FIXTURE, source)
    )
    assert tagged == bare, (
        f"weight_source={source!r} changed the efficiency score "
        f"({tagged} vs {bare}); #133 took provenance out of the arithmetic."
    )


def test_the_best_provenance_no_longer_scores_worst(user_db):
    """The tell from the bug report, pinned.

    Adding ``official`` to every subject used to *drop* 88.0 to 76.0:
    the best-provenance input scored worst. Now the two agree.
    """
    assert (
        user_db._calculate_efficiency_score(_with_source(ISSUE_FIXTURE, 'official'))
        == user_db._calculate_efficiency_score(ISSUE_FIXTURE)
        == 76.0
    )


def test_range_width_does_not_change_the_score_either(user_db):
    """``range_confidence`` had the identical direction problem.

    ``max(0.5, 1 - range_width/20)`` meant a vaguer range was penalised
    *less*, so the fix had to cover both terms. Two subjects with the
    same midpoint and the same distance-to-nearest-bound, one stated as
    a point and one as a wide band, must score the same.
    """
    narrow = [{'mistake_percentage': 40.0,
               'exam_weight': 20.0,
               'exam_weight_low': 20.0, 'exam_weight_high': 20.0}]
    wide = [{'mistake_percentage': 50.0,
             'exam_weight': 20.0,
             'exam_weight_low': 10.0, 'exam_weight_high': 30.0}]
    # Both deviate by 20 from the nearest bound, at midpoint 20.
    assert user_db._calculate_efficiency_score(narrow) == 96.0
    assert user_db._calculate_efficiency_score(wide) == 96.0


def test_inside_the_published_range_is_measured_from_the_midpoint(user_db):
    """A range is a claim about where the truth lies, so being inside it
    is not a miss — but the midpoint is still the best single guess."""
    inside = [{'mistake_percentage': 12.0, 'exam_weight': 10.0,
               'exam_weight_low': 8.0, 'exam_weight_high': 14.0}]
    # deviation = |12 - 11| = 1, weight_factor = 0.11
    assert user_db._calculate_efficiency_score(inside) == pytest.approx(99.89)


def test_perfect_alignment_still_scores_100(user_db):
    """Unchanged by #133, and worth pinning next to the rest."""
    aligned = [
        {'mistake_percentage': 50.0, 'exam_weight': 50.0},
        {'mistake_percentage': 30.0, 'exam_weight': 30.0},
        {'mistake_percentage': 20.0, 'exam_weight': 20.0},
    ]
    assert user_db._calculate_efficiency_score(aligned) == 100.0


def test_empty_subject_list_is_zero_not_one_hundred(user_db):
    assert user_db._calculate_efficiency_score([]) == 0


def test_the_score_never_goes_below_zero(user_db):
    """Without confidence damping the penalty can exceed 100; the clamp
    is what stops a negative score reaching ``_get_efficiency_rating``."""
    awful = [
        {'mistake_percentage': 100.0, 'exam_weight': 0.0},
        {'mistake_percentage': 0.0, 'exam_weight': 100.0},
    ]
    assert user_db._calculate_efficiency_score(awful) == 0


def test_the_confidence_tables_are_gone(user_db):
    """Deleted, not merely unused — an unused table invites a caller."""
    from database.domains import analytics_advanced as mod

    assert not hasattr(mod, '_WEIGHT_SOURCE_CONFIDENCE')
    assert not hasattr(mod, '_WEIGHT_SOURCE_DEFAULT_CONFIDENCE')


# ==================== the band is a rendering ====================


def test_all_official_weights_give_a_zero_width_band(user_db):
    """Nothing to be uncertain about: the band sits on the score."""
    band = user_db._build_efficiency_band(
        _with_source(ISSUE_FIXTURE, 'official'), 76.0
    )
    assert band['half_width'] == 0.0
    assert band['low'] == band['high'] == 76.0
    assert band['unverified_weight_pct'] == 0.0
    assert band['unverified_share'] == 0.0


@pytest.mark.parametrize(
    "source", ['user_explicit', 'user_defined', 'derived', 'user_estimate'],
)
def test_anything_but_official_widens_the_band(user_db, source):
    """"Verified" means "came off a published blueprint", full stop.

    ``user_explicit`` is a deliberate act by the student, but it is
    still not the blueprint, and the setting's copy says exactly that:
    "some are copied from the official exam blueprint, and others you
    typed in or WIMI worked out".
    """
    band = user_db._build_efficiency_band(
        _with_source(ISSUE_FIXTURE, source), 76.0
    )
    assert band['half_width'] > 0
    assert band['unverified_share'] == 1.0


def test_an_absent_weight_source_counts_as_unverified(user_db):
    """No recorded provenance is not provenance."""
    band = user_db._build_efficiency_band(ISSUE_FIXTURE, 76.0)
    assert band['unverified_share'] == 1.0
    # 50² + 10² + 40² over 100.
    assert band['half_width'] == pytest.approx(42.0)


def test_the_band_does_not_collapse_at_perfect_alignment(user_db):
    """The point of taking the width from the weights and not the
    deviations. A student perfectly aligned against weights somebody
    typed by hand has the least trustworthy 100 on offer."""
    aligned = [
        {'mistake_percentage': 50.0, 'exam_weight': 50.0},
        {'mistake_percentage': 30.0, 'exam_weight': 30.0},
        {'mistake_percentage': 20.0, 'exam_weight': 20.0},
    ]
    band = user_db._build_efficiency_band(aligned, 100.0)
    assert band['half_width'] > 0
    assert band['high'] == 100.0  # clamped
    assert band['low'] < 100.0


def test_a_more_granular_blueprint_narrows_the_band(user_db):
    """Twenty 5% buckets say far more per bucket than four 25% ones, and
    the width falls out of that rather than being tuned to it."""
    coarse = [{'mistake_percentage': 25.0, 'exam_weight': 25.0}] * 4
    fine = [{'mistake_percentage': 5.0, 'exam_weight': 5.0}] * 20
    assert (
        user_db._build_efficiency_band(fine, 100.0)['half_width']
        < user_db._build_efficiency_band(coarse, 100.0)['half_width']
    )


def test_the_band_is_clamped_to_the_score_scale(user_db):
    band = user_db._build_efficiency_band(ISSUE_FIXTURE, 5.0)
    assert band['low'] == 0.0
    assert 0.0 <= band['high'] <= 100.0


def test_an_empty_subject_list_has_a_zero_band(user_db):
    band = user_db._build_efficiency_band([], 0)
    assert band == {
        'low': 0.0, 'high': 0.0, 'half_width': 0.0,
        'unverified_weight_pct': 0.0, 'unverified_share': 0.0,
    }


# ==================== the preference ====================


def test_the_toggle_defaults_off(user_db):
    """The rating bands (``>= 85`` Excellent) assume a scalar, so the
    band is opt-in. "Off" is not degraded — ``weight_source_distribution``
    is in the payload either way."""
    assert user_db.get_preferences().efficiency_show_confidence_band is False
    assert user_db.get_all_settings()['efficiency_show_confidence_band'] is False


def test_the_toggle_round_trips_through_update_settings(user_db):
    """The acceptance criterion from #133."""
    updated = user_db.update_settings(efficiency_show_confidence_band=True)
    assert updated['efficiency_show_confidence_band'] is True
    assert user_db.get_all_settings()['efficiency_show_confidence_band'] is True
    assert user_db.get_preferences().efficiency_show_confidence_band is True

    back = user_db.update_settings(efficiency_show_confidence_band=False)
    assert back['efficiency_show_confidence_band'] is False


def test_the_toggle_is_user_level_not_device_local(user_db):
    """#126/#129's test is whether the value *denotes a machine*. It does
    not — it is a stated display preference, the same class as
    ``pane_open_mode``, and it must travel in a ``.wimi``."""
    from database.device_local import DEVICE_LOCAL_SETTING_FIELDS

    assert 'efficiency_show_confidence_band' not in DEVICE_LOCAL_SETTING_FIELDS
    # It reaches user_preferences, so update_preferences accepts it
    # directly rather than raising the device-local ValidationError.
    prefs = user_db.update_preferences(efficiency_show_confidence_band=True)
    assert prefs.efficiency_show_confidence_band is True
    row = user_db.fetchone(
        "SELECT efficiency_show_confidence_band FROM user_preferences "
        "WHERE user_id = ?",
        (user_db.user_id,),
    )
    assert row['efficiency_show_confidence_band'] == 1
