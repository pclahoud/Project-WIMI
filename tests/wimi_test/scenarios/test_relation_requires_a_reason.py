"""Regression: a subject relation cannot be saved without a reason.

Forgejo issue #14, decision 2 (owner, 2026-09-14):

    A written reason is mandatory. No relation exists without the
    student's sentence. It is both the anti-rubber-stamp mechanism and
    the g = 0.72 benefit. No "explain later" state — that is how a
    backlog of unexplained pairs is born, and an unexplained link reads
    as "people who bought this also bought".

This is the decision that makes the feature metacognitive rather than a
bookmarking one, so it is guarded at both layers it could leak through:
the Save button in the modal, and the bridge slot underneath it. A UI
that merely disables a button is one paste-and-delete away from writing
a blank row, and a backend guard alone would let the modal look broken.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _seed(db) -> tuple[int, int, int]:
    """Two topics in one exam. Returns ``(exam_context_id, htn, hn)``."""
    exam = db.create_exam_context(
        exam_name='Relation Reason Exam',
        exam_description='issue #14 — the reason is mandatory',
    )
    htn = db.create_subject_node(
        exam_context=exam.exam_name, name='RR Hypertension', level_type='Topic',
    )
    hn = db.create_subject_node(
        exam_context=exam.exam_name, name='RR Hypertensive Nephrosclerosis',
        level_type='Topic',
    )
    db.conn.commit()
    return exam.id, htn.id, hn.id


def _wait_for(page: WimiPage, expression: str, *, tries: int = 100) -> object:
    value = None
    for _ in range(tries):
        value = page.eval_js(expression)
        if value:
            return value
        page.wait_for_timeout(100)
    return value


@pytest.mark.slow
@pytest.mark.regression
def test_a_relation_cannot_be_saved_without_a_reason(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    exam_id, subject_id, other_id = _seed(wimi_session.user.db)
    wimi_page.goto('subject-deep-dive', query={'subject': subject_id,
                                               'exam': exam_id})

    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-add\"]')",
    ), 'The Related Topics add action never rendered'

    # ---- Act ---------------------------------------------------------
    wimi_page.locator(testid='deep-dive-relations-add').click()
    assert _wait_for(
        wimi_page, "!!document.querySelector('[data-testid=\"relation-modal\"]')"
    ), 'The relation modal did not open'

    # Pick the other subject, and nothing else.
    wimi_page.locator(testid='relation-search').fill('Nephro')
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid^=\"relation-result-\"]')",
    ), 'The subject picker returned no candidates'
    wimi_page.eval_js(
        "document.querySelector('[data-testid^=\"relation-result-\"]').click()"
    )

    # ---- Assert ------------------------------------------------------
    # A chosen subject is not enough: the sentence is the payload.
    assert _wait_for(
        wimi_page,
        "(() => { const el = document.querySelector("
        "'[data-testid=\"relation-chosen\"]'); return el && !el.hidden; })()",
    ), 'Choosing a candidate did not register'
    assert wimi_page.eval_js(
        "document.querySelector('[data-testid=\"relation-save\"]').disabled"
    ) is True, (
        'Save was enabled with a subject chosen and no reason written. '
        'Decision 2 has no "explain later" state.'
    )

    # Writing one enables it...
    wimi_page.locator(testid='relation-reason').fill(
        'Chronic hypertension scleroses the afferent arteriole.'
    )
    assert wimi_page.eval_js(
        "document.querySelector('[data-testid=\"relation-save\"]').disabled"
    ) is False, 'Save stayed disabled after a reason was written'

    # ...and taking it away again disables it. This is the paste-then-
    # delete path, which a one-way check would miss.
    wimi_page.locator(testid='relation-reason').fill('   ')
    assert wimi_page.eval_js(
        "document.querySelector('[data-testid=\"relation-save\"]').disabled"
    ) is True, 'Save stayed enabled after the reason was blanked out'

    # And the guard is not only in the button: the bridge refuses too,
    # with a message written for the student rather than a traceback.
    refusal = wimi_page.eval_js(
        """
        (async () => {
            try {
                await window.api.createSubjectRelation({
                    fromSubjectId: %d, toSubjectId: %d, reason: '   '
                });
                return {refused: false};
            } catch (err) {
                return {refused: true, message: String(err && err.message || err)};
            }
        })()
        """ % (subject_id, other_id),
        await_promise=True,
    )
    assert refusal.get('refused') is True, (
        f'The bridge accepted a blank reason: {refusal!r}. The UI guard is '
        f'not the only thing standing between a student and an unexplained '
        f'link — an import or a future extractor arrives here too.'
    )
    assert 'reason' in (refusal.get('message') or '').lower()

    # Nothing was written.
    assert wimi_session.user.db.fetchone(
        "SELECT COUNT(*) AS n FROM subject_relations"
    )['n'] == 0
