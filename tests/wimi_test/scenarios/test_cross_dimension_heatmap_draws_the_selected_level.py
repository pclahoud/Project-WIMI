"""Regression: the cross-dimension heatmap draws the level its pickers show (#799).

On the owner's own profile (a full published blueprint) the pickers showed
each axis at its top level while the heatmap drew topic-level rows: hundreds of
thousands of SVG shapes and a page dozens of screens tall. The page's first heatmap load ran before the level lists
arrived, queried with no level -- every subject at every depth -- and nothing
redrew it once the levels came. On a profile that size the level lists are
simply slower than the rest of the page's first load.

This scenario makes that ordering deterministic instead of waiting for a big
profile: a hook installed before the page's first script holds every
``getHierarchyLevelsForDimension`` call for 2.5 s, so the levels land after the
first heatmap load exactly as they did for the owner. Two axes, each with a
top level and one level beneath it; the heatmap must show the top-level names
and none of the ones beneath.

The exam's level list is Top/Beneath, which none of the subjects use, so
the order comes from tree depth (#818): System before Topic on one axis, Topic
before Subtopic on the other. This file is about the heatmap drawing the level
its pickers show, whichever that is.

The control: with the heatmap not waiting for the levels, the beneath-level
names are drawn and stay drawn (measured on the unfixed tree).

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

from datetime import date

import pytest

from _helpers.anki_settings import poll_true
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

LEVELS_DELAY_MS = 2500

# Wraps only getHierarchyLevelsForDimension, at the moment _loader.js assigns
# window.api -- the shape of w114_form_ready's slow bridge, narrowed to one call.
SLOW_LEVELS = """
(() => {
  let real;
  Object.defineProperty(window, 'api', {
    configurable: true,
    get() { return real; },
    set(value) {
      if (value && typeof value.getHierarchyLevelsForDimension === 'function') {
        const fn = value.getHierarchyLevelsForDimension;
        value.getHierarchyLevelsForDimension = function (...args) {
          return new Promise(r => setTimeout(r, %d)).then(() => fn.apply(value, args));
        };
        window.__slowLevels = true;
      }
      real = value;
    }
  });
})();
""" % LEVELS_DELAY_MS

TOP = ('Cardio Sys', 'Renal Sys', 'Dx Task', 'Rx Task')
BENEATH = ('HTN Topic', 'AKI Topic', 'Labs Step', 'Drug Step')
HEATMAP_TEXT = "(document.getElementById('dimensionHeatmap') || {}).textContent || ''"


def _w(lo, hi):
    return {'low': lo, 'high': hi}


def _seed(db) -> int:
    exam = db.create_exam_context(exam_name='H799', exam_description='',
                                  hierarchy_levels=['Top', 'Beneath'])
    db.apply_whole_exam_import(exam.id, [
        {'id': 'sys', 'name': 'System', 'display_order': 1, 'is_required': True,
         'allow_multiple': False, 'root_nodes': [
             {'id': 'cv', 'name': 'Cardio Sys', 'level_type': 'System', 'weight': _w(10, 20),
              'children': [{'id': 'htn', 'name': 'HTN Topic', 'level_type': 'Topic',
                            'weight': _w(5, 8)}]},
             {'id': 'rn', 'name': 'Renal Sys', 'level_type': 'System', 'weight': _w(10, 20),
              'children': [{'id': 'aki', 'name': 'AKI Topic', 'level_type': 'Topic',
                            'weight': _w(5, 8)}]}]},
        {'id': 'task', 'name': 'Task', 'display_order': 2, 'is_required': True,
         'allow_multiple': False, 'root_nodes': [
             {'id': 'dx', 'name': 'Dx Task', 'level_type': 'Topic', 'weight': _w(30, 40),
              'children': [{'id': 'labs', 'name': 'Labs Step', 'level_type': 'Subtopic',
                            'weight': _w(10, 20)}]},
             {'id': 'rx', 'name': 'Rx Task', 'level_type': 'Topic', 'weight': _w(30, 40),
              'children': [{'id': 'drug', 'name': 'Drug Step', 'level_type': 'Subtopic',
                            'weight': _w(10, 20)}]}]},
    ])
    ids = {r['name']: r['id'] for r in db.fetchall(
        "SELECT id, name FROM subject_nodes WHERE status = 'active'")}
    session = db.create_review_session(exam_context_id=exam.id, total_questions=10,
                                       total_incorrect=2, session_name='H799',
                                       date_encountered=date.today())
    for topic, step in (('HTN Topic', 'Labs Step'), ('AKI Topic', 'Drug Step')):
        db.create_question_entry(session.id, 'A', 'B', question_id=topic,
                                 primary_subject_ids=[ids[topic], ids[step]])
    return exam.id


@pytest.mark.slow
@pytest.mark.regression
def test_the_heatmap_draws_the_level_the_pickers_show(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    exam_id = _seed(wimi_session.user.db)
    wimi_page.tab.Page.enable()
    wimi_page.tab.Page.addScriptToEvaluateOnNewDocument(source=SLOW_LEVELS)
    wimi_page.goto('analytics', query={'exam': exam_id})

    assert poll_true(wimi_page, "window.__slowLevels === true"), \
        'the hook never wrapped the levels call, so nothing below is measured'
    assert poll_true(wimi_page, f"['Cardio Sys', 'Dx Task'].every(n => ({HEATMAP_TEXT}).includes(n))",
                     timeout_ms=30000), \
        f'the heatmap never drew its top level: {wimi_page.eval_js(HEATMAP_TEXT)!r}'

    # Give the levels, and any stale unlevelled response, time to land.
    wimi_page.wait_for_timeout(LEVELS_DELAY_MS + 1500)
    assert wimi_page.eval_js("document.getElementById('heatmapLevelA').value") == 'System'
    assert wimi_page.eval_js("document.getElementById('heatmapLevelB').value") == 'Topic'
    drawn = wimi_page.eval_js(HEATMAP_TEXT)
    for name in TOP:
        assert name in drawn, (name, drawn)
    for name in BENEATH:
        assert name not in drawn, (
            f'{name!r} is a level below the one the pickers show: the heatmap drew '
            f'every level ({drawn!r})')
