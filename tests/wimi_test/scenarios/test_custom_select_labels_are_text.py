"""Regression: CustomSelect renders option labels as text (#548 stage 3b).

``custom-select.js`` built its trigger and option list with ``innerHTML``
and interpolated each option's ``label`` and ``value`` raw. Session setup
feeds it the student's question sources, so a ``source_name`` -- typed in
the sources modal or delivered by a profile import -- carrying
``<img onerror=...>`` became an element whose handler ran as soon as the
page drew the source picker. #324's class, in a shared component.

The source is seeded through the database rather than typed, because an
import can deliver a name that never passed through the sources modal.
Both render paths are covered: the constructor's ``render()`` (first draw)
and ``setOptions()`` (every later reload of the source list).
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PAYLOAD = 'Bank <img src=x onerror="window.__cs_src=1"> & "Co"'

STATE = """
(() => {
  const sel = document.getElementById('session-source');
  if (!sel) return null;
  const opts = Array.from(sel.querySelectorAll('.custom-select-option'));
  const mine = opts.find(o => o.textContent.includes('Bank'));
  if (!mine) return null;
  return JSON.stringify({
    fired: window.__cs_src === 1,
    imgs: sel.querySelectorAll('img').length,
    label: mine.textContent.trim(),
    children: mine.children.length,
  });
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_source_select_labels_are_shown_not_executed(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='CS Exam', exam_description='#548')
    db.create_question_source(PAYLOAD, exam_context=exam.exam_name)
    db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='CS session', date_encountered=date.today())
    db.conn.commit()

    wimi_page.goto('session-setup', query={'exam_id': exam.id})
    assert poll(wimi_page, '(%s) !== null' % STATE.strip(), timeout_ms=20000), (
        'the source picker never drew the seeded source')
    wimi_page.wait_for_timeout(300)   # a broken <img>'s onerror fires async
    first = json.loads(wimi_page.eval_js(STATE))

    # setOptions() is the second render path: reload the list in place.
    wimi_page.eval_js("delete window.__cs_src; SessionState.sourceSelect.setOptions("
                      "SessionState.sourceSelect.options.slice())")
    wimi_page.wait_for_timeout(300)
    second = json.loads(wimi_page.eval_js(STATE))

    for label, state in (('render()', first), ('setOptions()', second)):
        assert not state['fired'], f'{label}: the source name executed as markup'
        assert state['imgs'] == 0, (label, state)
        # The other half: the student's text is shown exactly, not mangled.
        assert state['label'] == PAYLOAD, (label, state)
        assert state['children'] == 0, (label, state)
