"""Memory estimates from a review log, against golden values (#784 decision 11)."""

from __future__ import annotations

import math

import pytest

from app.anki import fsrs
from app.anki.fsrs import (
    MS_PER_DAY,
    ease_percent,
    estimate,
    retrievability,
    stability_from_interval,
)


class TestTheCurve:
    def test_the_constants_are_fsrs_4_5(self):
        assert fsrs.DECAY == -0.5
        assert fsrs.FACTOR == pytest.approx(19 / 81)
        # FACTOR is derived from the 90% definition, not a magic number.
        assert fsrs.FACTOR == pytest.approx(0.9 ** (1 / fsrs.DECAY) - 1)

    def test_recall_is_ninety_percent_at_the_stability(self):
        for s in (0.5, 1, 7, 365):
            assert retrievability(s, s) == pytest.approx(0.9)

    def test_golden_values(self):
        # (1 + 19/81 * t/S) ** -0.5, worked by hand.
        assert retrievability(0, 10) == 1.0
        assert retrievability(10, 10) == pytest.approx(0.9)
        assert retrievability(40, 10) == pytest.approx((1 + 76 / 81) ** -0.5)
        assert retrievability(40, 10) == pytest.approx(0.718, abs=5e-4)

    def test_it_is_not_the_v4_curve(self):
        """The plugin's constants; agree at t = S and nowhere else."""
        def v4(t, s):
            return (1 + t / (9 * s)) ** -1
        assert retrievability(10, 10) == pytest.approx(v4(10, 10))
        assert not math.isclose(retrievability(40, 10), v4(40, 10), rel_tol=1e-3)

    def test_a_future_review_does_not_exceed_certainty(self):
        assert retrievability(-3, 10) == 1.0

    def test_stability_must_be_positive(self):
        with pytest.raises(ValueError):
            retrievability(1, 0)


class TestFromTheLog:
    @pytest.mark.parametrize('ivl, days', [
        (10, 10.0),
        (-600, 600 / 86400),   # a ten-minute learning step, in seconds
        (0, None),             # reset to new
        (None, None),
        (True, None),
    ])
    def test_stability_from_interval(self, ivl, days):
        result = stability_from_interval(ivl)
        if days is None:
            assert result is None
        else:
            assert result == pytest.approx(days)

    @pytest.mark.parametrize('factor, pct', [(2500, 250.0), (1300, 130.0), (0, None), (None, None)])
    def test_ease_is_the_factor_as_a_percentage(self, factor, pct):
        assert ease_percent(factor) == pct

    def test_no_reviews_means_no_figures(self):
        result = estimate([], now_ms=10 * MS_PER_DAY)
        assert result.review_count == 0
        assert result.stability_days is None and result.retrievability is None

    def test_the_latest_review_by_id_decides_regardless_of_order(self):
        day = MS_PER_DAY
        rows = [
            {'id': 5 * day, 'ivl': 10, 'factor': 2500, 'time': 4000},
            {'id': 1 * day, 'ivl': 1, 'factor': 2300, 'time': 6000},
        ]
        result = estimate(rows, now_ms=15 * day)
        assert result.review_count == 2
        assert result.total_time_ms == 10_000
        assert result.latest_review_ms == 5 * day
        assert result.latest_ivl == 10 and result.latest_factor == 2500
        assert result.stability_days == 10.0
        assert result.retrievability == pytest.approx(0.9)
        assert result.ease_percent == 250.0

    def test_a_reset_card_has_no_stability_and_none_is_invented(self):
        rows = [{'id': MS_PER_DAY, 'ivl': 0, 'factor': 0, 'time': 0}]
        result = estimate(rows, now_ms=3 * MS_PER_DAY)
        assert result.stability_days is None
        assert result.retrievability is None
        assert result.ease_percent is None

    def test_rows_without_an_integer_id_are_ignored(self):
        rows = [{'id': 'x', 'ivl': 99}, {'ivl': 99}, {'id': MS_PER_DAY, 'ivl': 2, 'time': 1}]
        result = estimate(rows, now_ms=3 * MS_PER_DAY)
        assert result.review_count == 1 and result.latest_ivl == 2

    def test_to_dict_carries_every_figure(self):
        keys = set(estimate([], now_ms=0).to_dict())
        assert keys == {
            'review_count', 'total_time_ms', 'latest_review_ms', 'latest_ivl',
            'latest_factor', 'stability_days', 'retrievability', 'ease_percent',
        }
