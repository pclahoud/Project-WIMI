"""Regression: a relation created from one subject renders on both.

Forgejo issue #14, decision 4 (owner, 2026-09-14):

    Directional, rendered from both ends. Store one direction; show
    "leads to" on one subject and "caused by" on the other.

and the acceptance line it produces:

    A relation created from one subject renders on both subjects'
    panels, with the correct direction on each.

The whole chain is exercised rather than seeded: the modal on
hypertension's deep dive writes the row through the bridge, and then
hypertensive nephrosclerosis's own deep dive — a separate document, a
separate read — has to show the *same* relation with the direction
reversed. One stored row, two faces. A per-subject copy, or a panel that
only ever looked at ``from_subject_id``, would pass an assertion made on
the authoring page alone.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

REASON = 'Chronic hypertension scleroses the afferent arteriole.'


def _seed(db) -> tuple[int, int, int]:
    exam = db.create_exam_context(
        exam_name='Relation Both Ends Exam',
        exam_description='issue #14 — one row, two faces',
    )
    htn = db.create_subject_node(
        exam_context=exam.exam_name, name='BE Hypertension', level_type='Topic',
    )
    hn = db.create_subject_node(
        exam_context=exam.exam_name, name='BE Nephrosclerosis',
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


def _goto_deep_dive(page: WimiPage, subject_id: int, exam_id: int) -> None:
    """Navigate, and wait for the *new* document to be the one answering.

    A second ``goto`` to the same HTML file returns before the new
    document commits, so the marker is set on the outgoing document and
    the wait is for its disappearance.
    """
    page.eval_js("window.__relationScenarioMark = true")
    page.goto('subject-deep-dive', query={'subject': subject_id, 'exam': exam_id})
    for _ in range(100):
        if not page.eval_js("!!window.__relationScenarioMark"):
            return
        page.wait_for_timeout(100)
    raise AssertionError('The deep dive never navigated to the second subject')


@pytest.mark.slow
@pytest.mark.regression
def test_a_relation_renders_on_both_subjects_with_the_right_direction(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    exam_id, htn_id, hn_id = _seed(wimi_session.user.db)
    wimi_page.goto('subject-deep-dive', query={'subject': htn_id, 'exam': exam_id})
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-add\"]')",
    ), 'The Related Topics add action never rendered'

    # ---- Act: author the relation through the modal -------------------
    wimi_page.locator(testid='deep-dive-relations-add').click()
    assert _wait_for(
        wimi_page, "!!document.querySelector('[data-testid=\"relation-modal\"]')"
    )
    wimi_page.locator(testid='relation-search').fill('Nephro')
    assert _wait_for(
        wimi_page,
        f"!!document.querySelector('[data-testid=\"relation-result-{hn_id}\"]')",
    ), 'The picker did not offer the other subject'
    wimi_page.eval_js(
        f"document.querySelector('[data-testid=\"relation-result-{hn_id}\"]').click()"
    )
    wimi_page.locator(testid='relation-reason').fill(REASON)
    wimi_page.locator(testid='relation-save').click()

    # ---- Assert: the authoring end ------------------------------------
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-panel\"]')",
    ), 'The panel did not appear after saving the first relation'

    outgoing = wimi_page.eval_js(
        """
        (() => {
            const row = document.querySelector(
                '[data-testid=\"deep-dive-relations-list\"] .relation-item');
            if (!row) return null;
            return {
                direction: row.getAttribute('data-direction'),
                label: row.querySelector('.relation-direction').textContent.trim(),
                subject: row.querySelector('.relation-subject').textContent.trim(),
                reason: row.querySelector('.relation-reason').textContent.trim(),
            };
        })()
        """
    )
    assert outgoing == {
        'direction': 'outgoing',
        'label': 'Leads to',
        'subject': 'BE Nephrosclerosis',
        'reason': REASON,
    }, f'The authoring end rendered the relation wrong: {outgoing!r}'

    # ---- Assert: the other end ----------------------------------------
    _goto_deep_dive(wimi_page, hn_id, exam_id)
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-panel\"]')",
    ), (
        'The relation did not render on the other subject at all. It is one '
        'stored row read from both ends — a panel that only queries '
        'from_subject_id looks correct until you open the other page.'
    )

    incoming = wimi_page.eval_js(
        """
        (() => {
            const row = document.querySelector(
                '[data-testid=\"deep-dive-relations-list\"] .relation-item');
            if (!row) return null;
            return {
                direction: row.getAttribute('data-direction'),
                label: row.querySelector('.relation-direction').textContent.trim(),
                subject: row.querySelector('.relation-subject').textContent.trim(),
                reason: row.querySelector('.relation-reason').textContent.trim(),
            };
        })()
        """
    )
    assert incoming == {
        'direction': 'incoming',
        'label': 'Caused by',
        'subject': 'BE Hypertension',
        'reason': REASON,
    }, f'The receiving end rendered the relation wrong: {incoming!r}'

    # One row in the database, not two.
    assert wimi_session.user.db.fetchone(
        "SELECT COUNT(*) AS n FROM subject_relations"
    )['n'] == 1
