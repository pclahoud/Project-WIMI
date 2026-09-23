"""Regression: a cycle between two subjects is accepted and both render.

Forgejo issue #14, decision 7 (owner, 2026-09-14):

    Cycles are allowed. Math Academy's scarring cycle lesson was about
    *prerequisites*, where a cycle is incoherent. These are semantic: A
    causes B while B exacerbates A can both be true. Do not inherit a
    validator that would reject valid content.

Hypertension causes chronic kidney disease; chronic kidney disease
worsens hypertension. Both are true, both get written, and each
subject's panel has to show two rows — one outgoing, one incoming —
rather than collapsing them or refusing the second.

The second relation is authored through the modal, on the *second*
subject, which is the path a real student takes: they write one, read
it from the other end, and find they have something to add there too.
A cycle validator borrowed from prerequisite-graph thinking would refuse
exactly that click.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _seed(db):
    exam = db.create_exam_context(
        exam_name='Relation Cycle Exam',
        exam_description='issue #14 — cycles are valid content',
    )
    htn = db.create_subject_node(
        exam_context=exam.exam_name, name='CY Hypertension', level_type='Topic',
    )
    ckd = db.create_subject_node(
        exam_context=exam.exam_name, name='CY Chronic Kidney Disease',
        level_type='Topic',
    )
    # The first half of the cycle, seeded.
    db.create_subject_relation(htn.id, ckd.id, 'Hypertension damages the glomerulus.')
    db.conn.commit()
    return exam.id, htn.id, ckd.id


def _wait_for(page: WimiPage, expression: str, *, tries: int = 100) -> object:
    value = None
    for _ in range(tries):
        value = page.eval_js(expression)
        if value:
            return value
        page.wait_for_timeout(100)
    return value


_ROWS_JS = """
    (() => Array.from(document.querySelectorAll(
        '[data-testid="deep-dive-relations-list"] .relation-item'
    )).map(row => ({
        direction: row.getAttribute('data-direction'),
        subject: row.querySelector('.relation-subject').textContent.trim(),
        label: row.querySelector('.relation-direction').textContent.trim(),
    })))()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_a_cycle_between_two_subjects_is_accepted_and_both_render(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    exam_id, htn_id, ckd_id = _seed(wimi_session.user.db)
    wimi_page.goto('subject-deep-dive', query={'subject': ckd_id, 'exam': exam_id})
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-panel\"]')",
    ), 'The seeded relation did not render on the receiving subject'

    # ---- Act: close the loop from the other end ------------------------
    wimi_page.locator(testid='deep-dive-relations-add').click()
    assert _wait_for(
        wimi_page, "!!document.querySelector('[data-testid=\"relation-modal\"]')"
    )
    wimi_page.locator(testid='relation-search').fill('Hypertension')
    assert _wait_for(
        wimi_page,
        f"!!document.querySelector('[data-testid=\"relation-result-{htn_id}\"]')",
    ), (
        'The picker did not offer hypertension as a candidate. A subject '
        'already related in the other direction is still a legitimate '
        'target for the reverse statement.'
    )
    wimi_page.eval_js(
        f"document.querySelector('[data-testid=\"relation-result-{htn_id}\"]').click()"
    )
    wimi_page.locator(testid='relation-reason').fill(
        'Failing kidneys retain salt, which drives the pressure back up.'
    )
    wimi_page.locator(testid='relation-save').click()

    # ---- Assert -------------------------------------------------------
    rows = None
    for _ in range(100):
        rows = wimi_page.eval_js(_ROWS_JS)
        if rows and len(rows) == 2:
            break
        wimi_page.wait_for_timeout(100)

    error = wimi_page.eval_js(
        "(() => { const el = document.querySelector("
        "'[data-testid=\"relation-error\"]'); "
        "return el && !el.hidden ? el.textContent.trim() : null; })()"
    )
    assert error is None, (
        f'Closing the cycle was refused: {error!r}. Decision 7 is explicit '
        f'— A causes B while B exacerbates A can both be true, and the '
        f'prerequisite-graph lesson does not transfer.'
    )
    assert rows is not None and len(rows) == 2, (
        f'The second half of the cycle did not render: {rows!r}'
    )
    assert {row['direction'] for row in rows} == {'outgoing', 'incoming'}
    assert {row['label'] for row in rows} == {'Leads to', 'Caused by'}
    assert {row['subject'] for row in rows} == {'CY Hypertension'}

    # Two rows in the database, and the panel on the *other* subject sees
    # the same pair from the mirrored side.
    assert wimi_session.user.db.fetchone(
        "SELECT COUNT(*) AS n FROM subject_relations"
    )['n'] == 2

    wimi_page.eval_js("window.__relationScenarioMark = true")
    wimi_page.goto('subject-deep-dive', query={'subject': htn_id, 'exam': exam_id})
    assert _wait_for(wimi_page, "!window.__relationScenarioMark"), (
        'The deep dive never navigated to the other subject'
    )
    assert _wait_for(
        wimi_page,
        "(() => document.querySelectorAll("
        "'[data-testid=\"deep-dive-relations-list\"] .relation-item'"
        ").length === 2)()",
    ), 'The cycle did not render on hypertension as two rows'
