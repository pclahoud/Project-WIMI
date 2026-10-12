"""Regression: the analytics dashboard renders stored names as text (#546, #548).

Every card on this page that names something names a thing the student typed
or imported: subjects and dimension values (the subject-tree importer, a
profile or ``.wimi`` import), and tags (the same). Before this fix they went
into ``innerHTML`` unescaped, so an ``<img src=x onerror=...>`` in a name ran
when the dashboard opened -- #324's class, found here a third time as #546:

* **Insights** (``renderInsights``, #546) -- the backend writes the tag's name
  into the title and the suggested action;
* the **subject** and **tag legends** (``renderLegend``) -- the label, and the
  tag's stored colour, which went into a ``style="..."`` attribute;
* the **cross-dimension heatmap** tooltip and the drill-down **breadcrumb**;
* **Study Recommendations** (``rec.combination``, ``rec.recommendation``) and
  **Interaction Effects** (``dim_a_value`` x ``dim_b_value``).

Measured on the stage-3 gate (cd19396) before the fix, this test's seed fired
20 handlers, from ``insight-title``, ``insight-description``,
``insight-action``, both legends' label spans, ``legend-color`` (the colour
broke out of its attribute), ``tooltip-header``, ``breadcrumb-link``,
``recommendation-combination``, ``recommendation-text`` and
``interaction-combination``; 19 ``<img>`` elements were parsed into the six
containers.

The flat subject donut (``_renderSimpleDonut``) was escaped in the same change
but is not driven here: it draws only when no exam is selected, and the exam
filter has no "all exams" option -- with any exam present the page selects the
first -- so it cannot be reached with data to render.

Each payload's handler records the class of the element it landed in, so a
failure says which card executed it. Every surface is checked both ways: the
handler did not run and no ``<img>`` arrived, AND the student's text is shown
exactly -- an escape that mangles the name fails too.

Seeded through the database, not typed: an importer delivers a name that never
passed a form, and a profile import carries the ``tags`` row (colour included)
as stored.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# The class of the nearest ANCESTOR that has one, not of the direct parent:
# a payload that lands in a bare <span> (the legend label) has a parent with
# no class, and recorded '' -- a failure message naming nothing. The `||`
# keeps the push unconditional: if `closest` found nothing it would throw,
# and a throw inside onerror records nothing while the payload ran.
HANDLER = 'onerror="(window.__x=window.__x||[]).push((this.parentNode.closest(\'[class]\') || this.parentNode).className)"'
A_NAME = f'Cardio <img src=x {HANDLER}>'
B_NAME = f'Diagnosis <img src=x {HANDLER}>'
TAG_NAME = f'Misread <img src=x {HANDLER}>'
TAG_COLOR = f'#123456"><img src=x {HANDLER}>'

STATE = """
(() => {
  const box = id => document.getElementById(id);
  const txt = el => el ? el.textContent.replace(/\\s+/g, ' ').trim() : null;
  const imgs = id => box(id) ? box(id).querySelectorAll('img').length : null;
  const tip = document.getElementById('heatmap-tooltip');
  return JSON.stringify({
    fired: window.__x || [],
    imgs: Object.fromEntries(['insightsContainer', 'subjectLegend', 'tagLegend',
      'heatmapBreadcrumb', 'dimensionInsights-recommendations',
      'dimensionInsights-interactions'].map(id => [id, imgs(id)])),
    insights: txt(box('insightsContainer')),
    subjects: [...document.querySelectorAll('#subjectLegend .legend-label span')].map(txt),
    tags: [...document.querySelectorAll('#tagLegend .legend-label span')].map(txt),
    tag_swatch: (document.querySelector('#tagLegend .legend-color') || {}).style?.backgroundColor ?? null,
    recs: [...document.querySelectorAll('#dimensionInsights-recommendations .recommendation-combination')].map(txt),
    rec_text: [...document.querySelectorAll('#dimensionInsights-recommendations .recommendation-text')].map(txt),
    effects: [...document.querySelectorAll('#dimensionInsights-interactions .interaction-combination')].map(txt),
    tooltip: tip ? {imgs: tip.querySelectorAll('img').length,
                    header: txt(tip.querySelector('.tooltip-header'))} : null,
    crumbs: [...document.querySelectorAll('#breadcrumbPathA .breadcrumb-link')].map(txt),
  });
})()
"""


def _seed(db) -> dict:
    db._ensure_phase2_schema()
    db._ensure_phase4_schema()
    exam = db.create_exam_context(exam_name='W546 Exam', exam_description='#546',
                                  hierarchy_levels=['System', 'Topic'])
    dim_a = db.create_dimension(exam_id=exam.id, name='System', display_order=1)
    dim_b = db.create_dimension(exam_id=exam.id, name='Task', display_order=2)

    def node(name, dim, parent=None, level='System'):
        return db.create_subject_node(exam_context=exam.exam_name, name=name,
                                      level_type=level, parent_id=parent,
                                      dimension_id=dim).id

    a1 = node(A_NAME, dim_a)
    a1_topic = node('Heart Failure', dim_a, a1, 'Topic')
    a2 = node('Renal', dim_a)
    a2_topic = node('AKI', dim_a, a2, 'Topic')
    b1 = node(B_NAME, dim_b)
    b2 = node('Management', dim_b)
    tag = db.create_tag(exam.exam_name, 'Misread')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=10,
        session_name='W546 session', date_encountered=date.today())
    # Unbalanced on purpose: interaction effects need the cells to differ
    # from what the margins predict, and a recommendation needs >= 2.
    for a, b, n in ((a1_topic, b1, 4), (a1_topic, b2, 1), (a2_topic, b1, 1), (a2_topic, b2, 4)):
        for _ in range(n):
            db.create_question_entry(session.id, 'a', 'b', perceived_difficulty=3,
                                     primary_subject_ids=[a, b], tag_ids=[tag.id])
    with db.transaction():
        db.execute('UPDATE tags SET tag_name = ?, color_hex = ? WHERE id = ?',
                   (TAG_NAME, TAG_COLOR, tag.id))
    db.conn.commit()
    return {'exam': exam.id, 'a1': a1, 'b1': b1}


def _state(page: WimiPage) -> dict:
    page.wait_for_timeout(300)   # a broken <img>'s onerror fires async
    return json.loads(page.eval_js(STATE))


def _clean(state: dict) -> None:
    assert state['fired'] == [], f"a stored name executed as markup in: {state['fired']} ({state})"
    dirty = {k: v for k, v in state['imgs'].items() if v}
    assert not dirty, f'an <img> was parsed out of a stored name: {dirty}'


@pytest.mark.slow
@pytest.mark.regression
def test_dashboard_cards_show_stored_names_as_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    ids = _seed(wimi_session.user.db)
    wimi_page.goto('analytics', query={'exam': ids['exam']})
    ready = ("document.querySelectorAll('#insightsContainer .insight-card').length > 0"
             " && document.querySelectorAll('#tagLegend .legend-item').length > 0"
             " && document.querySelectorAll('#dimensionInsights-recommendations .recommendation-item').length > 0"
             " && document.querySelectorAll('#dimensionInsights-interactions .interaction-card').length > 0"
             " && document.querySelector('[data-testid=\"analytics-cross-dim-row-header-%d\"]') !== null"
             % ids['a1'])
    assert poll(wimi_page, ready, timeout_ms=30000), (
        f'the dashboard never drew its cards: {wimi_page.eval_js(STATE)}')

    # Hover the payload x payload heatmap cell, then drill into the payload row.
    cell = 'analytics-cross-dim-cell-%d-%d' % (ids['a1'], ids['b1'])
    wimi_page.eval_js("document.querySelector('[data-testid=\"%s\"]')"
                      ".dispatchEvent(new MouseEvent('mouseenter'))" % cell)
    tip = _state(wimi_page)['tooltip']
    wimi_page.eval_js("document.querySelector('[data-testid=\"analytics-cross-dim-row-header-%d\"]')"
                      ".dispatchEvent(new MouseEvent('click', {bubbles: true}))" % ids['a1'])
    assert poll(wimi_page, "document.querySelectorAll('#breadcrumbPathA .breadcrumb-link').length > 0",
                timeout_ms=15000), 'drilling into the row never drew a breadcrumb'
    state = _state(wimi_page)
    state['tooltip'] = tip
    _clean(state)

    assert TAG_NAME in state['insights'], state['insights']          # #546
    assert A_NAME in state['subjects'], state['subjects']
    assert state['tags'] == [TAG_NAME], state['tags']
    assert state['tag_swatch'] == '', (
        f'a colour that is not a colour should paint nothing: {state["tag_swatch"]!r}')
    assert f'{A_NAME} × {B_NAME}' in state['recs'], state['recs']
    assert any(A_NAME in t and B_NAME in t for t in state['rec_text']), state['rec_text']
    assert f'{A_NAME} × {B_NAME}' in state['effects'], state['effects']
    assert tip is not None and tip['imgs'] == 0, tip
    assert tip['header'] == f'{A_NAME} × {B_NAME}', tip
    assert state['crumbs'] == [A_NAME], state['crumbs']

