"""Regression: the weight card's minimum is set per exam in Settings (#828).

Owner, 2026-10-14: *"make it adjustible for users in the analytics page
settings"*. It lives under Per-Exam Analytics Configuration and saves with that
section's own button. A value outside 1-50 is refused with a sentence and not
saved.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from _helpers.anki_settings import poll_true
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

INPUT = '[data-testid="settings-analytics-min-mistakes"]'
SAVE = '[data-testid="settings-analytics-save-exam-config"]'


def _choose_exam(page, exam_id):
    page.goto('settings')
    assert poll_true(page, "!document.querySelector('[data-page-gated]')?.inert", timeout_ms=20000)
    page.eval_js("document.querySelector('.settings-nav-item[data-panel=\"dashboard_analytics\"]').click()")
    page.eval_js(f"""(() => {{ const s = document.getElementById('analytics_exam_selector');
        s.value = '{exam_id}'; s.dispatchEvent(new Event('change')); }})()""")
    assert poll_true(page, f"document.querySelector('{INPUT}')?.value === '3'"), \
        f"the field did not show the default: {page.eval_js(f'document.querySelector(`{INPUT}`)?.value')!r}"


@pytest.mark.slow
@pytest.mark.regression
def test_the_minimum_saves_per_exam_and_refuses_nonsense(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='M828', exam_description='')
    other = db.create_exam_context(exam_name='Other828', exam_description='')

    _choose_exam(wimi_page, exam.id)
    wimi_page.locator(css=INPUT).fill('5')
    wimi_page.locator(css=SAVE).click()
    # Read back from the database: a promise polled through poll_true is
    # always truthy, so it could not fail.
    page = wimi_page
    saved = None
    for _ in range(100):
        saved = db.get_exam_analytics_config(exam.id)['min_mistakes_to_flag']
        if saved == 5:
            break
        page.wait_for_timeout(100)
    assert saved == 5, f'the minimum was not saved: {saved!r}'
    assert db.get_exam_analytics_config(other.id)['min_mistakes_to_flag'] == 3, \
        'saving one exam changed another'

    page.locator(css=INPUT).fill('0')
    page.locator(css=SAVE).click()
    assert poll_true(page, "Array.from(document.querySelectorAll('.settings-toast'))"
                           ".some(t => t.textContent.includes('whole number from 1 to 50'))"), \
        'a refused value must say why'
    page.wait_for_timeout(500)
    assert db.get_exam_analytics_config(exam.id)['min_mistakes_to_flag'] == 5
