"""Regression: the dashboard's weight analysis shows subject names as text (#548).

``weight_analysis.js`` built the quadrant lists and the recommendations by
concatenating ``subject.subject_name`` straight into ``innerHTML`` -- the same
defect as #324, #525 and #546, on the analytics dashboard's "Exam Weight vs
Mistakes" card. A subject name is whatever the student typed or the subject
importer was handed, so a name carrying ``<img src=x onerror=...>`` ran on
every visit to the dashboard.

The page did not load ``escape.js`` at all, because nothing on it used
``WimiEscape`` yet; ``tests/test_web_escaping.py`` holds the link now that
something does.

Three-sided, like the tree editor's scenario: the handler did not run, no
``<img>`` reached either panel, and the name reads back exactly.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PAYLOAD = 'X "><img src=x onerror="window.__d=1">'

_RENDER_JS = """
(async () => {
    await window.api.ready();
    const dash = window.analyticsDashboard || window.dashboard || null;
    if (!dash) return {error: 'no dashboard global'};
    // The dashboard draws the same name elsewhere on load -- the subject
    // legend, which is not this file's (#548 found it there too). Let that
    // settle, then clear the flag, so only what THIS card draws can set it.
    for (let i = 0; i < 30; i += 1) {
        const legend = document.querySelector('#subjectLegend');
        if (legend && legend.textContent.trim()) break;
        await new Promise(r => setTimeout(r, 100));
    }
    await new Promise(r => setTimeout(r, 500));
    window.__d = 0;
    dash.currentExamFilter = %d;
    await dash.loadWeightAnalysis();
    await new Promise(r => setTimeout(r, 500));
    for (let i = 0; i < 50; i += 1) {
        const q = document.querySelector('#quadrantAnalysis');
        if (q && q.textContent.trim()) break;
        await new Promise(r => setTimeout(r, 100));
    }
    const read = sel => Array.from(document.querySelectorAll(sel))
        .map(el => el.textContent.trim());
    const imgs = sel => Array.from(document.querySelectorAll(sel))
        .reduce((n, el) => n + el.querySelectorAll('img').length, 0);
    return {
        fired: window.__d === 1,
        names: read('#quadrantAnalysis .subject-name'),
        recs: read('#recommendations .rec-subject'),
        imgs: imgs('#quadrantAnalysis') + imgs('#recommendations'),
    };
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_quadrants_and_recommendations_show_names_as_text(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db._ensure_phase2_schema()
    exam = db.create_exam_context(exam_name="V548 analysis",
                                  exam_description="")
    for name, low, high in ((PAYLOAD, 30, 40), ("V548 Renal", 10, 20)):
        db.create_subject_node_with_weight(
            exam_context=exam.exam_name, name=name, level_type='System',
            exam_weight_low=low, exam_weight_high=high,
            weight_source='user_defined',
        )

    wimi_page.goto("analytics")
    state = wimi_page.eval_js(_RENDER_JS % exam.id, await_promise=True)
    # Positive control first: the payload subject must actually be drawn,
    # or every assertion below passes against an empty card.
    assert state.get("names"), f"the quadrant list did not render: {state!r}"
    assert not state["fired"], f"the onerror handler RAN: {state!r}"
    assert state["imgs"] == 0, f"an <img> reached the card: {state!r}"
    assert PAYLOAD in state["names"], (
        f"the subject's name must read back exactly: {state['names']!r}")
    assert PAYLOAD in state["recs"], (
        f"the recommendation must name the subject exactly: {state['recs']!r}")
