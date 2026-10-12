"""Regression: the analytics dashboard draws no efficiency score (#146).

Replaces ``test_efficiency_band_toggle.py``, which asserted #133's band
rendering. That scenario cannot run any more and was not merely adjusted:
its whole subject -- whether the score is drawn as one number or as a
range -- is moot while the score is not drawn at all.

Why the score is gone
---------------------
#146 measured that it **cannot report a bad result**. On a realistic 15-row
blueprint every distribution a student could plausibly produce scores 88-99
and rates *Excellent*; `Fair` and `Needs Improvement` are unreachable, and
perfect alignment scores 99.1 rather than 100 because real blueprints do not
total 100% and #64 forbids rescaling them. The owner's decision, 2026-10-05,
is **none of #146's five proposed fixes**: *"We have yet to discuss this.
The feature should be disabled for the time being."*

So the score is hidden pending a discussion, and `#146` stays open.

The trap this is written around
-------------------------------
**An absence assertion is vacuous without a positive control.** A test that
merely found no `[data-testid="efficiency-score-value"]` would pass against:

* a dashboard that never loaded,
* a weight-analysis call that threw,
* an exam with no subjects, where `renderEmpty()` draws nothing either,
* a typo in the selector.

None of those is the decision. So this asserts the card **did** render --
quadrant analysis and recommendations are both present and non-empty -- and
only then is the missing score a finding. That is #121's lesson: an
assertion that a page does not say something passes whether or not the page
could ever have said it.

The second control is the arithmetic. The payload still carries
`efficiency_score`, because #146 is disabled rather than resolved, and this
asserts that too. A version of this change that stripped the backend would
pass every DOM assertion here while making the pending discussion
unevaluable.

Companion: ``tests/test_efficiency_score_is_disabled.py`` pins the switch at
the source level, because ``EFFICIENCY_SCORE_ENABLED`` is a top-level
``const`` -- a script-scope binding, invisible as ``window.`` -- so no
scenario can read the flag itself.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

#: Load the weight analysis, then report what the card actually drew.
#:
#: Waits on the **quadrant panel** rather than on the score, which is the
#: whole point: the old scenario waited for the score to appear and would
#: now time out, reporting "score never rendered" as a failure when it is
#: the expected state. Here the card's surviving half is the readiness
#: signal and the score's absence is the measurement.
_RENDER_JS = """
(async () => {
    try {
        await window.api.ready();
        const dash = window.analyticsDashboard || window.dashboard || null;
        if (!dash) return {ok: false, error: 'no dashboard global'};
        dash.currentExamFilter = %d;
        await dash.loadWeightAnalysis();

        const quadrant = () => document.querySelector('#quadrantAnalysis');
        for (let i = 0; i < 50; i += 1) {
            const q = quadrant();
            if (q && q.textContent.trim()) break;
            await new Promise(r => setTimeout(r, 100));
        }
        const q = quadrant();
        const recs = document.querySelector('#recommendations');
        const layout = document.querySelector('.weight-analysis-layout');
        return {
            ok: true,
            // --- the positive control: the card really did render ---
            quadrant_drawn: !!(q && q.textContent.trim()),
            recommendations_drawn: !!(recs && recs.textContent.trim()),
            layout_present: !!layout,
            // --- the decision ---
            score_value: !!document.querySelector(
                '[data-testid="efficiency-score-value"]'),
            band_note: !!document.querySelector(
                '[data-testid="efficiency-band-note"]'),
            info_icon: !!document.querySelector(
                '[data-testid="efficiency-confidence-info"]'),
            header: !!document.querySelector('.efficiency-header'),
            // Any leftover empty container would still take a grid row.
            layout_children: layout ? layout.children.length : -1,
            // innerText excludes display:none subtrees, so this catches a
            // score that is painted but not query-able by testid.
            says_efficiency: (layout ? layout.innerText : '')
                .toUpperCase().includes('EFFICIENCY SCORE'),
        };
    } catch (e) {
        return {ok: false, error: String(e)};
    }
})()
"""


def _seed(db):
    """An exam whose weights are all ``user_defined`` -- i.e. unverified.

    Kept from the #133 scenario this replaces. That is the realistic case
    (the subject importer writes ``user_defined`` for every imported
    subject) and it is the shape that used to produce the widest band, so
    if anything were going to draw a score for this exam, it would.
    """
    exam = db.create_exam_context(
        exam_name="Efficiency Score Disabled",
        exam_description="Regression for #146's disable",
    )
    for name, low, high in (
        ("ESD Cardio", 20, 30),
        ("ESD Renal", 10, 20),
        ("ESD Neuro", 5, 15),
    ):
        db.create_subject_node_with_weight(
            exam_context=exam.exam_name, name=name, level_type='System',
            exam_weight_low=low, exam_weight_high=high,
            weight_source='user_defined',
        )
    return exam


@pytest.mark.slow
@pytest.mark.regression
def test_the_dashboard_draws_no_efficiency_score(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db._ensure_phase2_schema()
    exam = _seed(db)

    wimi_page.goto("analytics")
    assert wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.getSubjectExamWeightAnalysis === 'function')()"
    ), "window.api.getSubjectExamWeightAnalysis is missing; see api/_loader.js."

    state = wimi_page.eval_js(_RENDER_JS % exam.id, await_promise=True)
    assert state.get('ok'), f"the probe failed: {state!r}"

    # ---- the positive control, first --------------------------------
    # Without these three, every assertion below passes against a card
    # that never rendered at all.
    assert state['layout_present'], (
        'the weight-analysis layout is absent, so nothing could have drawn '
        'a score whatever #146 decided -- this says nothing about the '
        'decision')
    assert state['quadrant_drawn'], (
        'the quadrant analysis is empty, so the card did not really render '
        'and the missing score below is not evidence of anything')
    assert state['recommendations_drawn'], (
        'the recommendations panel is empty; same problem. #146 hid the '
        'score ONLY -- the card around it must still work, since the issue '
        'itself says the quadrant analysis is the part that is actionable')

    # ---- the decision -----------------------------------------------
    assert not state['score_value'], (
        'the analytics dashboard is drawing an efficiency score. #146 is an '
        'OPEN product question and the score cannot report a bad result, so '
        'it shows every student "Excellent" including the ones it should '
        'not. Re-enable only with a decision recorded on #146.')
    assert not state['header'], (
        'the .efficiency-header container is in the DOM. Even empty it '
        'takes a row of .weight-analysis-layout -- the gap a disabled '
        'feature must not occupy')
    assert not state['band_note'], 'the band note is drawn'
    assert not state['info_icon'], (
        "the score's info affordance is drawn with no score to explain")

    # A painted-but-not-queryable score would slip past every selector
    # above. innerText excludes display:none subtrees, which is the
    # distinction that makes this a second instrument rather than a
    # restatement (#121, #127).
    assert not state['says_efficiency'], (
        'the card still paints the words "EFFICIENCY SCORE" somewhere the '
        'testid selectors do not reach')

    # The card is the two panels and nothing else.
    assert state['layout_children'] == 1, (
        f"expected .weight-analysis-layout to hold exactly the content "
        f"grid, found {state['layout_children']} children -- an extra one "
        f"is a leftover container from the hidden score")


@pytest.mark.slow
@pytest.mark.regression
def test_the_score_is_still_computed_behind_the_scenes(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """"Disabled for the time being" is not "deleted" (#146).

    The owner's words leave the discussion open, so the arithmetic has to
    remain measurable. This is the control for the test above in the other
    direction: a change that hid the score by stripping the backend would
    satisfy every DOM assertion there and quietly make #146's five options
    unevaluable.

    It also keeps the hide honest about where it lives. This is a frontend
    decision; the payload is untouched.
    """
    db = wimi_session.user.db
    db._ensure_phase2_schema()
    exam = _seed(db)

    wimi_page.goto("analytics")
    payload = wimi_page.eval_js(
        """
        (async () => {
            await window.api.ready();
            const d = await window.api.getSubjectExamWeightAnalysis(
                {examContextId: %d});
            return {
                has_score: typeof d.efficiency_score === 'number',
                has_rating: typeof d.efficiency_rating === 'string',
                has_band: !!d.efficiency_band,
                score: d.efficiency_score,
            };
        })()
        """ % exam.id,
        await_promise=True,
    )

    assert payload['has_score'], (
        'efficiency_score is gone from the payload. #146 was disabled in '
        'the page, not removed from the product -- deleting the arithmetic '
        'is a larger decision nobody has taken')
    assert payload['has_rating'], 'efficiency_rating is gone from the payload'
    assert payload['has_band'], (
        'efficiency_band is gone. #133 made it unconditional in the payload '
        'so that "off" is never a path that stops computing something')
