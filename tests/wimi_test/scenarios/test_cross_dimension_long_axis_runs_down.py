"""Regression: the cross-dimension diagram is drawn readable (#821).

On the owner's profile, 3 values against 36 drew a grid shrunk to the card's
width -- unreadable text, with hundreds of pixels of empty space above and
below -- and row labels cut at 18 characters under the axis title. Owner's
decision: the dimension with more values runs down the side.

Here axis A (System) has 2 values and axis B (Task) has 6, one of them with a
long name. The pickers keep A and B as chosen; the drawing turns.

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

LONG = 'Applying foundational science concepts'
TASKS = [LONG, 'Diagnosis', 'Treatment', 'Prognosis', 'Prevention', 'Screening']

ROWS = ("JSON.stringify(Array.from(document.querySelectorAll("
        "'#dimensionHeatmap .row-headers text')).map(e => e.firstChild.textContent))")


@pytest.mark.slow
@pytest.mark.regression
def test_the_longer_axis_is_rows_and_the_grid_is_not_shrunk(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    exam_id, dims, ids = seed_two_axis_exam(wimi_session.user.db, ['Cardio', 'Renal'], TASKS)
    wimi_page.goto('analytics', query={'exam': exam_id})

    assert poll_true(wimi_page, "document.querySelectorAll('#dimensionHeatmap .row-headers text').length > 0",
                     timeout_ms=30000), 'the heatmap never drew'
    assert wimi_page.eval_js("document.getElementById('heatmapDimA').value") == str(dims['System'])
    assert wimi_page.eval_js("document.getElementById('heatmapDimB').value") == str(dims['Task'])

    rows = json.loads(wimi_page.eval_js(ROWS))
    assert sorted(rows) == sorted(TASKS), (
        f'the six-value axis must run down the side, with full names: {rows!r}')
    cols = wimi_page.eval_js("document.querySelectorAll('#dimensionHeatmap .col-headers text').length")
    assert cols == 2

    # No row label may reach into the rotated axis title's strip.
    overlap = wimi_page.eval_js("""(() => {
        const svg = document.querySelector('#dimensionHeatmap svg').getBoundingClientRect();
        const left = Math.min(...Array.from(document.querySelectorAll('#dimensionHeatmap .row-headers text'))
            .map(t => t.getBoundingClientRect().left));
        return left - svg.left;
    })()""")
    assert overlap >= 25, f'row labels start {overlap:.0f}px into the svg, under the axis title'

    # Drawn at its own size, not scaled into the card.
    drawn, declared = json.loads(wimi_page.eval_js("""(() => {
        const s = document.querySelector('#dimensionHeatmap svg');
        return JSON.stringify([s.getBoundingClientRect().width, +s.getAttribute('width')]);
    })()"""))
    assert abs(drawn - declared) < 1, f'svg drawn {drawn}px wide for a {declared}px drawing'

    # A row heading belongs to Task, so it drills Task.
    wimi_page.eval_js(f"""document.querySelector(
        '[data-testid="analytics-cross-dim-row-header-{ids["Diagnosis"]}"]')
        .dispatchEvent(new MouseEvent('click', {{bubbles: true}}))""")
    assert poll_true(wimi_page, f"window.dashboard.drilldownState.parentNodeB?.id === {ids['Diagnosis']}"), \
        'clicking a Task row must drill into Task'
    assert wimi_page.eval_js("window.dashboard.drilldownState.parentNodeA") is None


@pytest.mark.slow
@pytest.mark.regression
def test_a_grid_wider_than_the_card_scrolls_instead_of_shrinking(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The owner's shape: more columns than the card holds. It must keep its
    size and scroll, where it used to scale down inside a letterbox."""
    systems = [f'System {n:02d}' for n in range(30)]
    tasks = [f'Task {n:02d}' for n in range(31)]
    exam_id, _, _ = seed_two_axis_exam(wimi_session.user.db, systems, tasks, every_pair=False)
    wimi_page.goto('analytics', query={'exam': exam_id})
    assert poll_true(wimi_page, "document.querySelectorAll('#dimensionHeatmap .col-headers text').length === 30",
                     timeout_ms=30000), 'the heatmap never drew 30 columns'

    drawn, declared, scroll, client = json.loads(wimi_page.eval_js("""(() => {
        const box = document.getElementById('dimensionHeatmap');
        const s = box.querySelector('svg');
        return JSON.stringify([s.getBoundingClientRect().width, +s.getAttribute('width'),
                               box.scrollWidth, box.clientWidth]);
    })()"""))
    assert declared > client, f'the fixture must be wider than the card ({declared} <= {client})'
    assert abs(drawn - declared) < 1, f'svg shrunk to {drawn}px for a {declared}px drawing'
    assert scroll > client, 'a grid wider than the card must scroll'
