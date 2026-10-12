"""Regression: Quick Analytics names an empty exam as text (#548).

The dashboard's Quick Analytics card says *"No entries logged yet for <exam>"*
when the exam picked in its filter has no entries. Stage 2 escaped the exam's
name in the filter's options and trigger, but this sentence interpolated the
same name unescaped -- so an exam called ``X <img src=x onerror=...>`` (an exam
name is typed in the wizard or carried in by a profile import) ran its handler
the moment the student picked it. Same value, same card, two sinks, one missed.

Driven by a real click on the filter's option, the path a student takes.
Checked both ways: nothing fires and no ``<img>`` appears, AND the sentence
reads the exam's name exactly.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

EXAM_NAME = 'Boards <img src=x onerror="window.__preview_exam=1">'

STATE = """
(() => {
  const box = document.querySelector('.analytics-preview-empty-state');
  return JSON.stringify({
    fired: window.__preview_exam === 1,
    imgs: box ? box.querySelectorAll('img').length : null,
    text: box ? box.querySelector('p').textContent : null,
  });
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_the_empty_state_names_the_exam_as_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name=EXAM_NAME, exam_description='#548')
    db.conn.commit()

    wimi_page.goto('dashboard')
    option = ('document.querySelector(\'.analytics-exam-select .custom-select-option'
              '[data-value="%d"]\')' % exam.id)
    assert poll(wimi_page, f'{option} !== null', timeout_ms=30000), (
        'the Quick Analytics filter never listed the exam')
    wimi_page.eval_js(f'{option}.dispatchEvent(new MouseEvent("click", {{bubbles: true}}))')
    assert poll(wimi_page, "(document.querySelector('.analytics-preview-empty-state p') || {})"
                           ".textContent?.includes('No entries logged yet for') === true",
                timeout_ms=20000), f'no empty state for the exam: {wimi_page.eval_js(STATE)}'
    wimi_page.wait_for_timeout(300)   # a broken <img>'s onerror fires async
    state = json.loads(wimi_page.eval_js(STATE))

    assert not state['fired'], f'the exam name executed as markup: {state}'
    assert state['imgs'] == 0, state
    assert state['text'] == f'No entries logged yet for {EXAM_NAME}', state
