"""Regression: Study Recommendations ranks what the heatmap above it shows (#824).

It ranked the exam's first two dimensions at every level at once, so a system
and its own topics competed for the same five places, and it never changed
when the heatmap's pickers did. Owner, 2026-10-14: *"file it as an issue and
fix it"*.

Two systems and one task, each with a child; two entries per pair, tagged on
the children (a cell needs two to be recommended).

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from _helpers.anki_settings import poll_true
from _helpers.two_axis_exam import seed_two_axis_exam
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

COMBOS = ("JSON.stringify(Array.from(document.querySelectorAll("
          "'#dimensionInsights-recommendations .recommendation-combination'))"
          ".map(e => e.textContent).sort())")


def _combos(page):
    return json.loads(page.eval_js(COMBOS))


@pytest.mark.slow
@pytest.mark.regression
def test_recommendations_rank_the_heatmaps_cells_and_follow_its_level(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    exam_id, _, _ = seed_two_axis_exam(
        wimi_session.user.db, ['Cardio', 'Renal'], ['Diagnosis'], per_pair=2)
    wimi_page.goto('analytics', query={'exam': exam_id})

    top = ['Cardio × Diagnosis', 'Renal × Diagnosis']
    assert poll_true(wimi_page, f"{COMBOS} === {json.dumps(json.dumps(top, ensure_ascii=False, separators=(',', ':')))}", timeout_ms=30000), (
        f'expected only the top-level pairs the heatmap shows, got {_combos(wimi_page)}')

    wimi_page.eval_js("""(() => {
        const s = document.getElementById('heatmapLevelA');
        s.value = 'Topic';
        s.dispatchEvent(new Event('change'));
    })()""")
    below = ['Cardio child × Diagnosis', 'Renal child × Diagnosis']
    assert poll_true(wimi_page, f"{COMBOS} === {json.dumps(json.dumps(below, ensure_ascii=False, separators=(',', ':')))}"), (
        f'the recommendations did not follow the heatmap down a level: {_combos(wimi_page)}')
