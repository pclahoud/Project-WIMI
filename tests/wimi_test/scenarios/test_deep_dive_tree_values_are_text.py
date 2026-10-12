"""Regression: the deep dive draws subject and error-type names as text (#548).

#525 fixed the Recent Entries rows; four more sinks on the same page still
interpolated a stored name into ``innerHTML``:

* the **"Show as part of"** selector -- each parent's name as an
  ``<option>``, and again in the "(also: ...)" hint;
* the **Child Subjects** rows -- ``child.subject_name``;
* the **Common Mistake Types** rows -- the tag's name, in the text and in
  a ``data-testid`` attribute (it also wrote the tag's colour into a
  ``style`` attribute, but that path is unreachable today: the page reads
  ``type.color`` and the payload's key is ``color_hex``, so it is not
  asserted here);
* the **Recommendations** -- the child-focus line quotes the top child's
  name.

Subject and tag names are seeded through the database because the subject
importer and a profile import deliver them without passing through the tree
editor or the entry form.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PARENT_NAME = 'Cardio <img src=x onerror="window.__dd_parent=1">'
CHILD_NAME = 'Murmurs <img src=x onerror="window.__dd_child=1">'
TAG_NAME = 'Misread <img src=x onerror="window.__dd_tag=1">'

SELECTOR = """
(() => {
  const box = document.getElementById('multiParentSelector');
  const sel = document.getElementById('multiParentSelectorControl');
  if (!sel) return null;
  return JSON.stringify({
    fired: window.__dd_parent === 1,
    imgs: box.querySelectorAll('img').length,
    options: [...sel.options].map(o => o.textContent),
    also: (box.querySelector('.also-list') || {}).textContent || null,
  });
})()
"""

PARENT_PAGE = """
(() => {
  const row = document.querySelector('[data-testid="deep-dive-child-row-%d"]');
  const badge = document.querySelector('.mistake-type-badge');
  const rec = document.querySelector('[data-testid="deep-dive-recommendation-child-focus"]');
  if (!row || !badge || !rec) return null;
  const page = document.querySelector('.page-container');
  return JSON.stringify({
    child_fired: window.__dd_child === 1,
    tag_fired: window.__dd_tag === 1,
    imgs: page.querySelectorAll('img').length,
    child: row.querySelector('.child-subject-name').textContent,
    tag: badge.textContent.trim(),
    rec: rec.querySelector('.recommendation-text').textContent,
  });
})()
"""


def _seed(db):
    exam = db.create_exam_context(exam_name='Deep Dive Names', exam_description='#548')
    cardio = db.create_subject_node(exam.exam_name, PARENT_NAME, 'System')
    renal = db.create_subject_node(exam.exam_name, 'Renal', 'System')
    shared = db.create_subject_node(exam.exam_name, 'Hypertension', 'Topic', parent_id=cardio.id)
    db.add_edge(renal.id, shared.id, is_primary=False)
    child = db.create_subject_node(exam.exam_name, CHILD_NAME, 'Topic', parent_id=cardio.id)

    group = db.create_tag_group(exam_context=exam.exam_name, group_name='Errors')
    tag = db.create_hierarchical_tag(exam_context=exam.exam_name, tag_name=TAG_NAME,
                                     group_id=group.id)

    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=2, total_incorrect=2,
        session_name='Names session', date_encountered=date.today())
    for _ in range(2):
        db.create_question_entry(session.id, 'a', 'b', reflection='r',
                                 primary_subject_ids=[child.id], tag_ids=[tag.id])
    db.conn.commit()
    return exam.id, cardio.id, shared.id, child.id


@pytest.mark.slow
@pytest.mark.regression
def test_deep_dive_names_are_shown_not_executed(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    exam_id, cardio_id, shared_id, child_id = _seed(wimi_session.user.db)

    # --- A two-parent subject: the selector names its parents ------------
    wimi_page.goto('subject-deep-dive', query={'subject': shared_id, 'exam': exam_id})
    assert poll(wimi_page, '(%s) !== null' % SELECTOR.strip(), timeout_ms=20000), (
        'the "Show as part of" selector never drew')
    wimi_page.wait_for_timeout(300)   # a broken <img>'s onerror fires async
    sel = json.loads(wimi_page.eval_js(SELECTOR))
    assert not sel['fired'], 'a parent name executed as markup in the selector (#548)'
    assert sel['imgs'] == 0, sel
    assert PARENT_NAME in sel['options'], sel
    assert sel['also'] == f'(also: {PARENT_NAME}, Renal)', sel

    # --- The parent: child rows, mistake types, recommendations ----------
    wimi_page.eval_js('window.__old_document = 1')
    wimi_page.goto('subject-deep-dive', query={'subject': cardio_id, 'exam': exam_id})
    assert poll(wimi_page, "window.__old_document === undefined", timeout_ms=10000)
    expr = PARENT_PAGE % child_id
    assert poll(wimi_page, '(%s) !== null' % expr.strip(), timeout_ms=20000), (
        'the parent deep dive never drew its child row, mistake type and recommendation')
    wimi_page.wait_for_timeout(300)
    state = json.loads(wimi_page.eval_js(expr))
    assert not state['child_fired'], 'a child subject name executed as markup (#548)'
    assert not state['tag_fired'], 'an error-type name executed as markup (#548)'
    assert state['imgs'] == 0, state
    assert state['child'] == CHILD_NAME, state
    assert state['tag'] == TAG_NAME, state
    assert f'"{CHILD_NAME}"' in state['rec'], state
