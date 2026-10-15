"""Regression: a Study Recommendation opens its entries (#829).

The rows had a pointer cursor and a hover highlight, and a click ran a handler
whose whole body was a ``console.log``. Owner, 2026-10-14: a click opens the
entries. Since #824 a recommendation is one of the heatmap's cells, so it opens
the same entry-browser list a click on that cell does -- both subjects, AND
mode, children included. Enter does the same, on a row reached by Tab order.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from _helpers.anki_settings import poll_true
from _helpers.two_axis_exam import seed_two_axis_exam
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

ROW = '#dimensionInsights-recommendations .recommendation-item'


def _open_analytics(page, exam_id):
    page.goto('analytics', query={'exam': exam_id})
    assert poll_true(page, f"document.querySelectorAll('{ROW}').length === 1", timeout_ms=30000), \
        'the single recommended pair never drew'
    page.eval_js("window.__stillAnalytics = true")


def _landed(page):
    assert poll_true(page, "!window.__stillAnalytics && location.pathname.endsWith('entry_browser.html')",
                     timeout_ms=15000), f'did not open the entry browser: {page.eval_js("location.href")}'
    return parse_qs(urlparse(page.eval_js('location.href')).query)


@pytest.mark.slow
@pytest.mark.regression
def test_a_click_and_enter_both_open_the_pairs_entries(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    exam_id, _, ids = seed_two_axis_exam(wimi_session.user.db, ['Cardio'], ['Diagnosis'], per_pair=2)
    expected = {'exam': [str(exam_id)], 'subjects': [f"{ids['Cardio']},{ids['Diagnosis']}"],
                'subject_mode': ['and'], 'include_children': ['true']}

    _open_analytics(wimi_page, exam_id)
    wimi_page.locator(css=ROW).click()
    assert _landed(wimi_page) == expected

    _open_analytics(wimi_page, exam_id)
    assert wimi_page.eval_js(f"document.querySelector('{ROW}').tabIndex") == 0, \
        'the row cannot take focus, so a keyboard cannot reach it'
    wimi_page.eval_js(f"document.querySelector('{ROW}').focus()")
    for kind in ('keyDown', 'keyUp'):
        wimi_page.tab.Input.dispatchKeyEvent(type=kind, key='Enter', code='Enter',
                                             windowsVirtualKeyCode=13)
    assert _landed(wimi_page) == expected
