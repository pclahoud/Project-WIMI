"""Over-represented is measured from the middle of the weight band (#827).

Owner, 2026-10-14: *"instead of the higher end of the range, make it the
median"*. A subject is over-represented when the student's share of mistakes
is above 1.3 x the middle of its band -- it was 1.3 x the top -- and a share
inside the band is still never over-represented, which was not part of the
decision and is kept. Heavy is still a middle of 10% or more.

Each case is one the old rule filed differently, except the in-band ones,
which pin the exemption that stays.
"""
from __future__ import annotations

import pytest

from database.domains.analytics_advanced import AdvancedAnalyticsMixin

pytestmark = pytest.mark.database

categorize = AdvancedAnalyticsMixin._categorize_subject_quadrant


@pytest.mark.parametrize('share, low, high, expected, old', [
    # 20-30%: the cut is 32.5%, was 39%.
    (33.0, 20, 30, 'priority', 'well-maintained'),
    (32.0, 20, 30, 'well-maintained', 'well-maintained'),
    # 2-4%: the cut is 3.9%, was 5.2%.
    (5.0, 2, 4, 'reduce-focus', 'low-priority'),
    # 5-15%: the cut is 13%, but 13-15% is inside the band.
    (14.0, 5, 15, 'well-maintained', 'well-maintained'),
    (16.0, 5, 15, 'priority', 'well-maintained'),
])
def test_the_cut_is_one_point_three_times_the_middle(share, low, high, expected, old):
    assert categorize(None, share, low, high) == expected, (
        f'{share}% against {low}-{high}%: the old rule (1.3 x the top) gave {old!r}')
