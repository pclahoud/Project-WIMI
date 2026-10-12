"""Regression: a Date preset click changes nothing until Apply.

Forgejo issue #521 -- "A Date preset click applies its range before Apply,
so a closed dropdown still filters".

Why it failed: ``handleDatePreset`` -- the preset buttons' click handler --
wrote ``filters.dateFrom`` / ``dateTo`` on the click itself. Closing the
dropdown without Apply left that range in ``filters``, so the NEXT unrelated
filter change (a tag Apply here) sent it to the backend: the list lost its
entries and a "Date range" chip appeared while the Date button still read
All Time. The dropdown also reopened on the clicked-but-never-applied
preset, so it showed a state that was not in force.

What the fix changes: a preset click only moves the highlight and shows or
hides the custom panel. ``applyDateFilter`` (#475) already derives the range
from the highlighted preset, and is now the only writer of the range apart
from ``resetDateControls``. Opening the dropdown puts the highlight (and the
custom panel and its inputs) back on what was last applied.

The seeded entry's session is 30 days old, so Last 7 Days excludes it: a
leaked range empties the list rather than just setting a field.

Everything is driven with real CDP clicks.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from _helpers.w114_form_ready import centre_of, poll, real_click
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

VISIBLE = ("(() => { const g = document.getElementById('entryGrid');"
           " return g.style.display === 'none' ? 0"
           " : g.querySelectorAll('[data-entry-id]').length; })()")
STATE = """JSON.stringify({
  label: document.getElementById('dateFilterValue').textContent.trim(),
  active: (document.querySelector('.date-preset.active') || {dataset: {}}).dataset.range || null,
  custom: document.getElementById('customDateRange').style.display,
  from: document.getElementById('dateFrom').value,
  open: !!document.querySelector('#dateFilterBtn').closest('.filter-group.open'),
  filterFrom: entryBrowser.filters.dateFrom, filterTo: entryBrowser.filters.dateTo,
  tags: entryBrowser.filters.tagIds,
  chips: Array.from(document.querySelectorAll('#filterChips .filter-chip'))
    .map(c => c.dataset.testid) })"""


def _state(page: WimiPage) -> dict:
    return json.loads(page.eval_js(STATE))


def _click(page: WimiPage, selector: str) -> None:
    real_click(page, centre_of(page, selector))


def _close_without_apply(page: WimiPage) -> None:
    """Close the dropdown by clicking outside it, as a student would."""
    _click(page, '.page-title')
    assert poll(page, "!document.querySelector('.filter-group.open')", timeout_ms=3000), (
        f"the dropdown did not close on an outside click: {_state(page)}")


def _reopen_shows(page: WimiPage, active: str, how: str) -> None:
    _click(page, '#dateFilterBtn')
    s = _state(page)
    assert s['open'], s
    assert s['active'] == active and s['custom'] == 'none', (
        f"after {how} the reopened dropdown highlights {s['active']!r} "
        f"(custom panel {s['custom']!r}), but {active!r} is what is in force: {s}")
    _close_without_apply(page)


@pytest.mark.slow
@pytest.mark.regression
def test_date_preset_click_changes_nothing_until_apply(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Preset Exam", exam_description="")
    group = db.create_tag_group(exam_context="Preset Exam", group_name="Errors")
    tag = db.create_hierarchical_tag(
        exam_context="Preset Exam", tag_name="Misread", group_id=group.id)
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=1,
        session_name="A month ago", date_encountered=date.today() - timedelta(days=30))
    db.create_question_entry(
        review_session_id=session.id, user_answer="A", correct_answer="B",
        reflection="r", explanation="e", tag_ids=[tag.id])

    wimi_page.goto('entry-browser', query={'exam': exam.id})
    assert poll(wimi_page, f"{VISIBLE} === 1", timeout_ms=15000), "the seeded card never rendered"
    assert poll(wimi_page, f"!!document.querySelector('[data-testid=\"browser-tag-item-{tag.id}\"]')",
                timeout_ms=10000), "the seeded tag never reached the Tags dropdown"

    # 1. Click Last 7 Days, close without Apply: nothing is in force.
    _click(wimi_page, '#dateFilterBtn')
    _click(wimi_page, '.date-preset[data-range="7days"]')
    _close_without_apply(wimi_page)
    s = _state(wimi_page)
    assert (s['filterFrom'], s['filterTo']) == (None, None), (
        f"a preset click with no Apply set the date filter: {s}")

    # 2. An unrelated filter change must not carry the unapplied range.
    _click(wimi_page, '#tagFilterBtn')
    _click(wimi_page, f'[data-testid="browser-tag-item-{tag.id}"] input')
    _click(wimi_page, '#applyTags')
    assert poll(wimi_page, f"entryBrowser.filters.tagIds.includes({tag.id})", timeout_ms=5000)
    assert poll(wimi_page, f"{VISIBLE} === 1", timeout_ms=10000), (
        f"applying a tag also applied the never-applied Last 7 Days: {_state(wimi_page)}")
    s = _state(wimi_page)
    assert (s['filterFrom'], s['filterTo'], s['label']) == (None, None, 'All Time'), s
    assert 'browser-filter-chip-date' not in s['chips'], (
        f"a Date range chip appeared with no date Apply: {s}")
    assert 'browser-filter-chip-tag' in s['chips'], s  # control: the tag chip did

    # 3. Reopening shows what is in force, not the abandoned click --
    #    including an abandoned Custom Range, whose panel must not stay open.
    _reopen_shows(wimi_page, 'all', 'abandoning Last 7 Days')
    _click(wimi_page, '#dateFilterBtn')
    _click(wimi_page, '.date-preset[data-range="custom"]')
    assert _state(wimi_page)['custom'] == 'block', "Custom Range did not show its panel"
    _close_without_apply(wimi_page)
    _reopen_shows(wimi_page, 'all', 'abandoning Custom Range')

    # 4. Control: preset + Apply still filters, and an abandoned click on
    #    another preset afterwards leaves the applied one in force.
    _click(wimi_page, '#dateFilterBtn')
    _click(wimi_page, '.date-preset[data-range="7days"]')
    _click(wimi_page, '#applyDate')
    assert poll(wimi_page, f"{VISIBLE} === 0", timeout_ms=10000), (
        f"Last 7 Days + Apply did not filter the month-old entry: {_state(wimi_page)}")
    applied = _state(wimi_page)
    assert applied['label'] == 'Last 7 Days' and applied['filterFrom'], applied
    assert 'browser-filter-chip-date' in applied['chips'], applied

    _click(wimi_page, '#dateFilterBtn')
    _click(wimi_page, '.date-preset[data-range="all"]')
    _close_without_apply(wimi_page)
    s = _state(wimi_page)
    assert (s['filterFrom'], s['filterTo']) == (applied['filterFrom'], applied['filterTo']), (
        f"clicking All Time without Apply changed the range in force: {s}")
    _reopen_shows(wimi_page, '7days', 'abandoning All Time over an applied Last 7 Days')
    assert wimi_page.eval_js(VISIBLE) == 0
