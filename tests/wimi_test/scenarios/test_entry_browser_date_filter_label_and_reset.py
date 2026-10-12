"""Regression: the Date filter names its preset, and a typed range comes off.

Forgejo issue #475 -- "The entry browser's Date filter labels every preset
'Custom', and once a custom range is typed All Time cannot be restored from
the dropdown".

Why it failed: ``applyDateFilter`` read ``#dateFrom`` / ``#dateTo`` on every
Apply and only ever *added* a bound, then labelled the button ``Custom``
whenever any bound was set. So Last 7 Days read ``Custom``; and once a range
had been typed, All Time nulled the filter and the very next statement put
the stale inputs back. ``clearAllFilters`` and the date chip's cross left the
inputs (and, for the chip, the active preset) alone, so the next Apply undid
them too.

What the fix changes: the ACTIVE preset decides. The inputs are read only
for Custom Range and cleared for every other preset; the button names the
preset (``Last 7 Days``), ``Custom`` only for a typed range. Clear all and
the chip's cross go through one ``resetDateControls()``.

Everything is driven with real CDP input -- clicks on the controls and key
events into the native date inputs -- because ``el.value = ...`` is exactly
the kind of write that cannot tell a working control from a broken one.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from _helpers.w114_form_ready import (
    centre_of, poll, real_click,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# Cards actually on screen: showEmpty() hides the grid rather than emptying it.
VISIBLE = ("(() => { const g = document.getElementById('entryGrid');"
           " return g.style.display === 'none' ? 0"
           " : g.querySelectorAll('[data-entry-id]').length; })()")
STATE = """JSON.stringify({
  label: document.getElementById('dateFilterValue').textContent.trim(),
  from: document.getElementById('dateFrom').value,
  to: document.getElementById('dateTo').value,
  active: (document.querySelector('.date-preset.active') || {dataset: {}}).dataset.range || null,
  filterFrom: entryBrowser.filters.dateFrom, filterTo: entryBrowser.filters.dateTo })"""

# A range a year back: the one seeded entry (today) is outside it.
RANGE_FROM = date.today() - timedelta(days=400)
RANGE_TO = date.today() - timedelta(days=370)


def _state(page: WimiPage) -> dict:
    return json.loads(page.eval_js(STATE))


def _click(page: WimiPage, selector: str) -> None:
    real_click(page, centre_of(page, selector))


def _type_date(page: WimiPage, selector: str, when: date) -> None:
    """Click the field's first segment and type the digits as key events."""
    raw = page.eval_js(
        "(() => { const el = document.querySelector(%s);"
        " el.scrollIntoView({block: 'center'});"
        " const r = el.getBoundingClientRect();"
        " const x = Math.round(r.left + 10), y = Math.round(r.top + r.height / 2);"
        " return JSON.stringify({x, y, hit: document.elementFromPoint(x, y) === el}); })()"
        % json.dumps(selector))
    point = json.loads(raw)
    assert point['hit'], f"{selector} is covered at {point}; a click would miss it"
    real_click(page, point)
    for ch in when.strftime('%m%d%Y'):
        key = dict(key=ch, code=f'Digit{ch}', windowsVirtualKeyCode=ord(ch))
        page.tab.Input.dispatchKeyEvent(type='keyDown', text=ch, **key)
        page.tab.Input.dispatchKeyEvent(type='keyUp', **key)
    page.wait_for_timeout(100)
    got = page.eval_js("document.querySelector(%s).value" % json.dumps(selector))
    assert got == when.isoformat(), (
        f"typing into {selector} produced {got!r}, not {when.isoformat()!r}; "
        "the field's segment order is not the mm/dd/yyyy this assumes")


def _apply_preset(page: WimiPage, preset: str) -> None:
    _click(page, '#dateFilterBtn')
    _click(page, f'.date-preset[data-range="{preset}"]')
    _click(page, '#applyDate')


def _apply_custom_range(page: WimiPage) -> None:
    _click(page, '#dateFilterBtn')
    _click(page, '.date-preset[data-range="custom"]')
    _type_date(page, '#dateFrom', RANGE_FROM)
    _type_date(page, '#dateTo', RANGE_TO)
    _click(page, '#applyDate')
    assert poll(page, f"{VISIBLE} === 0", timeout_ms=10000), (
        f"the typed range never emptied the list: {_state(page)}")
    assert _state(page)['label'] == 'Custom'


def _reopen_and_apply_all_time_is_in_force(page: WimiPage, how: str) -> None:
    s = _state(page)
    assert (s['from'], s['to'], s['active']) == ('', '', 'all'), (
        f"after {how} the dropdown still holds {s}: a range the filter no "
        f"longer applies, which the next Apply may put back")
    _click(page, '#dateFilterBtn')
    _click(page, '#applyDate')
    assert poll(page, f"{VISIBLE} === 1", timeout_ms=10000), (
        f"after {how} and a plain Apply the list is filtered again: {_state(page)}")
    assert _state(page)['label'] == 'All Time'


@pytest.mark.slow
@pytest.mark.regression
def test_date_filter_names_presets_and_lets_a_range_go(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Date Exam", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=1,
        session_name="Today", date_encountered=date.today())
    db.create_question_entry(
        review_session_id=session.id, user_answer="A", correct_answer="B",
        reflection="r", explanation="e")

    wimi_page.goto('entry-browser')
    assert poll(wimi_page, f"{VISIBLE} === 1", timeout_ms=15000), "the seeded card never rendered"

    # 1. A preset is named by its own name.
    _apply_preset(wimi_page, '7days')
    assert poll(wimi_page, f"{VISIBLE} === 1", timeout_ms=10000)
    assert _state(wimi_page)['label'] == 'Last 7 Days', _state(wimi_page)

    # 2. A typed range is Custom; All Time then takes it off.
    _apply_custom_range(wimi_page)
    _apply_preset(wimi_page, 'all')
    assert poll(wimi_page, f"{VISIBLE} === 1", timeout_ms=10000), (
        f"All Time + Apply left the typed range in force: {_state(wimi_page)}")
    s = _state(wimi_page)
    assert (s['label'], s['from'], s['to'], s['filterFrom'], s['filterTo']) == (
        'All Time', '', '', None, None), s

    # 3. The chip's cross, then a plain Apply, stays at All Time.
    _apply_custom_range(wimi_page)
    _click(wimi_page, '[data-testid="browser-filter-chip-date-remove"]')
    assert poll(wimi_page, f"{VISIBLE} === 1", timeout_ms=10000)
    _reopen_and_apply_all_time_is_in_force(wimi_page, "the date chip's cross")

    # 4. Clear all, then a plain Apply, stays at All Time.
    _apply_custom_range(wimi_page)
    _click(wimi_page, '#clearAllFilters')
    assert poll(wimi_page, f"{VISIBLE} === 1", timeout_ms=10000)
    _reopen_and_apply_all_time_is_in_force(wimi_page, "Clear all")
