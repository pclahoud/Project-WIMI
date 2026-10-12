"""Regression: Study Recommendations on an exam with unweighted subjects (#469).

Every new exam starts unweighted, and ``get_weighted_study_recommendations``
raised on it (``None / 2``): the bridge returned ``success=false`` and the page
caught that into ``console.error`` only, so the student saw the heading
STUDY RECOMMENDATIONS with nothing under it.

Two tests, one per half of the fix:

* the real path, no fakes: an exam whose subjects carry no weight now draws
  recommendations, and the ``Weight:`` row is omitted rather than printing the
  ranking fallback as if it were the student's figure;
* the failure path: when the call fails for any reason, the card says so. That
  one fakes the bridge call to reject, because after the backend fix nothing
  real makes it fail -- and it is the half #174 is about.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

SECTION = '#dimensionInsights-recommendations'

_LOAD_JS = """
(async () => {
    await window.api.ready();
    const dash = window.dashboard;
    dash.currentExamFilter = %d;
    await dash.initializeDimensionAnalytics();
    %s
    await dash.loadStudyRecommendations();
    const box = document.querySelector('%s');
    return JSON.stringify({
        uses_dimensions: !!(dash.dimensionAnalytics
            && dash.dimensionAnalytics.examUsesDimensions()),
        text: box ? box.innerText.trim() : null,
        items: box ? box.querySelectorAll('.recommendation-item').length : -1,
        weight_rows: box ? Array.from(box.querySelectorAll('.stat-label'))
            .filter(l => l.textContent.trim() === 'Weight:').length : -1,
        error_box: !!document.querySelector(
            '[data-testid="study-recommendations-error"]'),
    });
})()
"""


def _seed(db):
    """Two dimensions, one subject in each, three entries tagged on both.

    No weights anywhere -- the default state of a new exam, and exactly what
    raised. ``min_entries=2`` in the cross-dimension query needs at least two
    entries in a cell, so three is the smallest honest number.
    """
    exam = db.create_exam_context(
        exam_name='Unweighted Exam',
        exam_description='#469 -- nothing weighted yet')
    dims = [db.create_dimension(exam.id, 'System', 1),
            db.create_dimension(exam.id, 'Task', 2)]
    cardio = db.create_subject_node(
        exam_context=exam.exam_name, name='Cardio', level_type='System',
        dimension_id=dims[0])
    diagnosis = db.create_subject_node(
        exam_context=exam.exam_name, name='Diagnosis', level_type='System',
        dimension_id=dims[1])
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=3, total_incorrect=3,
        session_name='Unweighted session', date_encountered=date.today())
    for _ in range(3):
        entry = db.create_question_entry(session.id, 'A', 'B', perceived_difficulty=3)
        for node in (cardio, diagnosis):
            db.conn.execute(
                "INSERT INTO entry_subject_mappings "
                "(question_entry_id, subject_node_id, mapping_type) "
                "VALUES (?, ?, 'primary')", (entry.id, node.id))
    db.conn.commit()
    return exam.id


def _load(page: WimiPage, exam_id: int, before: str = '') -> dict:
    page.goto('analytics')
    return json.loads(page.eval_js(_LOAD_JS % (exam_id, before, SECTION),
                                   await_promise=True))


@pytest.mark.slow
@pytest.mark.regression
def test_an_unweighted_exam_still_gets_recommendations(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    exam_id = _seed(wimi_session.user.db)

    state = _load(wimi_page, exam_id)

    assert state['uses_dimensions'], (
        'the dashboard did not see a dimensional exam, so nothing below '
        'would have exercised the section')
    assert state['items'] >= 1, (
        f'Study Recommendations drew no recommendation on an unweighted exam; '
        f'its text was {state["text"]!r}')
    assert state['weight_rows'] == 0, (
        'a Weight: row was printed for subjects that have no weight -- that '
        'figure is the ranking fallback, not the student\'s')
    assert not state['error_box']


@pytest.mark.slow
@pytest.mark.regression
def test_a_failed_load_says_so_in_the_card(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    exam_id = _seed(wimi_session.user.db)

    state = _load(
        wimi_page, exam_id,
        "window.api.getWeightedStudyRecommendations = () => "
        "Promise.reject(new Error('probe failure'));")

    assert state['error_box'], (
        'a failed load left the card with no message -- the bare heading #469 '
        f'reported. Its text was {state["text"]!r}')
    assert 'probe failure' in state['text']
    assert 'Error loading study recommendations' in state['text']
