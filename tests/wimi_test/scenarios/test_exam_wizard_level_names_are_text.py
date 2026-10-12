"""Regression: the exam wizard draws an exam's hierarchy level names as text (#548).

Editing an exam loads its stored ``default_hierarchy_levels`` into the
wizard, and two places interpolated each name into ``innerHTML``: the
Hierarchy step's level list (``renderHierarchyLevels``) and the Review
step's chain (``updateSummary``). The wizard itself only ever offers a
template's levels or the defaults, but the stored list is whatever the
exam's database holds -- a profile import or another computer's folder-sync
copy carries it as written -- so the names are the student's data, not the
code's.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

LEVEL = 'Organ <img src=x onerror="window.__lvl_img=1">'
LEVELS = [LEVEL, 'Topic', 'Subtopic']
# Readiness waits on 'Organ', which only this exam's stored list has. The
# wizard draws its own defaults until the stored list arrives, and both of the
# other two names are in those defaults -- 'Topic' is in all ten templates as
# well, 'Subtopic' in eight -- so a poll on either is satisfied while the list
# on screen is still somebody else's, and the Review chain below then captures
# that list instead of this one (#756).
READY = ("(() => { try { return [...document.querySelectorAll("
         "'#hierarchy-levels .level-name')].some(e => e.textContent.includes('Organ')); }"
         " catch (e) { return false; } })()")

STATE = """
(() => {
  const names = [...document.querySelectorAll('#hierarchy-levels .level-name')]
    .map(e => e.textContent);
  if (!names.some(n => n.includes('Organ'))) return null;
  return JSON.stringify({
    fired: window.__lvl_img === 1,
    imgs: document.querySelectorAll('#hierarchy-levels img, #summary-hierarchy img').length,
    names: names,
    summary: [...document.querySelectorAll('#summary-hierarchy .hierarchy-item')]
      .map(e => e.textContent),
  });
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_stored_level_names_are_shown_not_executed(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='Levels Exam', exam_description='#548',
                                  hierarchy_levels=LEVELS)
    db.conn.commit()

    wimi_page.goto('exam-wizard', query={'edit': exam.id})
    assert poll(wimi_page, READY, timeout_ms=20000), (
        "the wizard never drew the exam's stored levels")
    # The Review step's chain, drawn the way the Review step draws it.
    wimi_page.eval_js('window.examWizard.updateSummary()')
    wimi_page.wait_for_timeout(300)   # a broken <img>'s onerror fires async
    state = json.loads(wimi_page.eval_js(STATE))

    assert not state['fired'], 'a hierarchy level name executed as markup (#548)'
    assert state['imgs'] == 0, state
    assert state['names'] == LEVELS, state
    assert state['summary'] == LEVELS, state
