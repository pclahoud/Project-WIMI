"""Regression: the weight analysis shows one dimension at one level (#820).

Owner's request, 2026-10-14: the card should follow the dimension selection and
offer the dimension's levels. Owner's decisions: when the Settings default is
*All Dimensions* the card asks for one rather than mixing them; at a level, a
subject's mistakes include the entries beneath it.

Every entry here is tagged on a child only, so the top level's rows carry
mistakes only through that roll-up.

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

NAMES = ("JSON.stringify(Array.from(document.querySelectorAll("
         "'#quadrantAnalysis .subject-name')).map(e => e.textContent).sort())")
CARD_TEXT = "document.getElementById('weightAnalysis').innerText"


def _choose(page, select_id, value):
    page.eval_js(f"""(() => {{
        const s = document.getElementById('{select_id}');
        s.value = {json.dumps(str(value))};
        s.dispatchEvent(new Event('change'));
    }})()""")


def _names(page):
    return json.loads(page.eval_js(NAMES))


@pytest.mark.slow
@pytest.mark.regression
def test_all_dimensions_asks_then_each_level_lists_its_own_subjects(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    exam_id, dims, _ = seed_two_axis_exam(
        wimi_session.user.db, ['Cardio', 'Renal'], ['Diagnosis'])
    wimi_page.goto('analytics', query={'exam': exam_id})

    assert poll_true(wimi_page, "!document.getElementById('weightScope').hidden", timeout_ms=20000), \
        'the pickers never appeared on an exam with dimensions'
    assert poll_true(wimi_page, f"{CARD_TEXT}.includes('Choose a dimension')"), (
        'with Settings on All Dimensions the card must ask, not mix the axes: '
        f'{wimi_page.eval_js(CARD_TEXT)!r}')
    assert wimi_page.eval_js("document.querySelectorAll('#quadrantAnalysis .subject-name').length") == 0

    _choose(wimi_page, 'weightDim', dims['System'])
    assert poll_true(wimi_page, f"{NAMES} === '[\"Cardio\",\"Renal\"]'"), _names(wimi_page)
    assert wimi_page.eval_js("document.getElementById('weightLevel').value") == 'System'
    # Rolled up: nothing is tagged on Cardio itself, and it is half the exam.
    # The row names both figures and the count behind the share (#827), and
    # its bar puts them on the card's scale: the largest figure is 50%, so
    # the scale runs 0-60% in steps of 20, the dot sits at 50/60 and the
    # band 10-20% starts at 10/60.
    row = json.loads(wimi_page.eval_js("""(() => {
        const li = Array.from(document.querySelectorAll('#quadrantAnalysis .band-row'))
            .find(r => r.querySelector('.subject-name').textContent === 'Cardio');
        return JSON.stringify({
            count: li.querySelector('.band-row-count').textContent,
            exam: li.querySelector('.band-stat-exam').textContent.trim(),
            share: li.querySelector('.band-stat-share').textContent.trim(),
            dot: li.querySelector('.share-mark').style.getPropertyValue('--share'),
            band: li.querySelector('.band-mark').style.getPropertyValue('--band-left'),
            ticks: Array.from(document.querySelectorAll('#quadrantAnalysis .band-tick'))
                .map(t => t.textContent),
        });
    })()"""))
    assert row['count'] == '1 mistake', row
    assert row['exam'] == '10-20% of the exam', row
    assert row['share'] == '50% of your mistakes', row
    assert row['dot'].strip() == '83.333%' and row['band'].strip() == '16.667%', row
    assert row['ticks'] == ['0%', '20%', '40%', '60%'], row

    _choose(wimi_page, 'weightLevel', 'Topic')
    assert poll_true(wimi_page, f"{NAMES} === '[\"Cardio child\",\"Renal child\"]'"), _names(wimi_page)

    _choose(wimi_page, 'weightDim', dims['Task'])
    assert poll_true(wimi_page, f"{NAMES} === '[\"Diagnosis\"]'"), _names(wimi_page)
    assert wimi_page.eval_js("document.getElementById('weightLevel').value") == 'Topic', \
        'a new dimension starts at its own top level'


@pytest.mark.slow
@pytest.mark.regression
def test_the_settings_default_dimension_is_where_the_card_starts(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam_id, dims, _ = seed_two_axis_exam(db, ['Cardio'], ['Diagnosis', 'Treatment'])
    db.update_exam_analytics_config(exam_id, {'default_dimension_id': dims['Task']})
    wimi_page.goto('analytics', query={'exam': exam_id})

    assert poll_true(wimi_page, f"{NAMES} === '[\"Diagnosis\",\"Treatment\"]'", timeout_ms=20000), \
        _names(wimi_page)
    assert wimi_page.eval_js("document.getElementById('weightDim').value") == str(dims['Task'])
