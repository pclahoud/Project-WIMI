"""Regression: the entry page's prev/next bar needs the open entry in its list.

Forgejo issue #526 -- "The entry page keeps a stale prev/next list when the
open entry is not in it".

Why it failed: the entry browser leaves its result list in
``sessionStorage.entryNavContext`` for ``entry_detail.js`` to step through.
``loadNavContext`` re-pointed ``index`` only when the open entry was IN that
list; when it was not, it kept the list and its old ``index``, so any route
that opens an entry other than the browser -- after a browse earlier in the
session -- drew an "N of M" bar for an unrelated list, with Prev/Next
stepping through it.

What the fix changes: ``loadNavContext`` is the one place that decides. A
list that does not contain the open entry is discarded (and removed from
sessionStorage), so no bar is drawn. One fix for every route, rather than
each caller clearing the key as PR #524 does for the deep dive.

The control: a list that DOES contain the entry still draws the bar at the
entry's own position -- recomputed, not the stored ``index``, which is
planted wrong on purpose -- and real clicks on Next and Prev move through it.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import centre_of, real_click
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# ``marker`` tells a freshly committed document from the one before it;
# ``ready`` is showContent(), after which updateNavigationUI runs before
# any further task can observe the page.
NAV = """(() => { const main = document.getElementById('main-content');
  const bar = document.querySelector('.entry-navigation');
  return JSON.stringify({
    marker: window.__w526 === 1,
    ready: !!main && getComputedStyle(main).display !== 'none',
    id: window.entryDetail ? window.entryDetail.entryId : null,
    bar: bar ? getComputedStyle(bar).display : null,
    position: document.getElementById('position-indicator').textContent.trim(),
    stored: sessionStorage.getItem('entryNavContext') }); })()"""


def _shown(page: WimiPage, entry_id: int, timeout_ms: int = 10000) -> dict:
    elapsed, last = 0, {}
    while elapsed < timeout_ms:
        try:
            last = json.loads(page.eval_js(NAV))
        except Exception:  # context torn down mid-navigation
            last = {}
        if last.get('ready') and not last.get('marker') and last.get('id') == entry_id:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    raise AssertionError(f"entry {entry_id} never finished rendering: {last}")


def _open(page: WimiPage, entry_id: int) -> dict:
    page.eval_js('window.__w526 = 1')
    page.goto('entry-detail', query={'id': entry_id})
    return _shown(page, entry_id)


def _plant(page: WimiPage, ids: list[int], index: int) -> None:
    page.eval_js("sessionStorage.setItem('entryNavContext', JSON.stringify(%s))"
                 % json.dumps({'ids': ids, 'index': index, 'total': len(ids)}))


def _press(page: WimiPage, selector: str, entry_id: int) -> dict:
    page.eval_js('window.__w526 = 1')
    real_click(page, centre_of(page, selector))
    return _shown(page, entry_id)


@pytest.mark.slow
@pytest.mark.regression
def test_prev_next_bar_only_for_a_list_holding_the_open_entry(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W526 Exam", exam_description="#526")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=4, total_incorrect=4,
        session_name="W526", date_encountered=date.today())
    a, b, c, outsider = (db.create_question_entry(
        review_session_id=session.id, user_answer=f"W526 answer {n}",
        correct_answer="B", reflection="r", explanation="e").id for n in range(4))

    # Any entry page first, so the planted list lives in the page's storage.
    first = _open(wimi_page, a)
    assert first['bar'] == 'none', first

    # 1. A browse list that does NOT hold the opened entry: no bar.
    _plant(wimi_page, [a, b, c], 2)
    got = _open(wimi_page, outsider)
    assert got['bar'] == 'none', (
        f"entry {outsider} drew a prev/next bar ({got['position']!r}) from a "
        f"list it is not in -- the stale-context defect, #526: {got}")
    assert got['stored'] is None, (
        f"the stale list was left in sessionStorage for a later page: {got}")

    # 2. Control: a list that holds it draws the bar at the entry's own
    #    position, not the stored index (planted wrong on purpose)...
    _plant(wimi_page, [a, b, c], 0)
    got = _open(wimi_page, b)
    assert (got['bar'], got['position']) == ('flex', '2 of 3'), got

    # ...and real clicks on Next and Prev step through it.
    got = _press(wimi_page, '#next-entry-btn', c)
    assert (got['bar'], got['position']) == ('flex', '3 of 3'), got
    got = _press(wimi_page, '#prev-entry-btn', b)
    assert (got['bar'], got['position']) == ('flex', '2 of 3'), got
    got = _press(wimi_page, '#prev-entry-btn', a)
    assert (got['bar'], got['position']) == ('flex', '1 of 3'), got
