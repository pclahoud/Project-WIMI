"""Regression: a symmetric relation type reads the same from both subjects.

Owner's decision, 2026-10-03 (#14, #60; m026): relations get types, and a
type may be **symmetric** -- "confused with" has no direction. It is stored
once, in canonical order, and both deep dives render it with the same
label and no arrow.

Exercised through the modal rather than seeded, because the modal is where
direction used to be chosen: a symmetric choice that still sent a
direction, or a panel that still labelled one end "Caused by", would pass
a database-only test.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


REASON = 'Both are pigmented and "stuck on"; the ABCDEs tell them apart.'


def _seed(db) -> tuple[int, int, int]:
    exam = db.create_exam_context(
        exam_name='Relation Symmetric Exam',
        exam_description='m026 -- a symmetric type has no direction',
    )
    sk = db.create_subject_node(
        exam_context=exam.exam_name, name='SY Seborrheic keratosis', level_type='Topic')
    mel = db.create_subject_node(
        exam_context=exam.exam_name, name='SY Melanoma', level_type='Topic')
    db.conn.commit()
    return exam.id, sk.id, mel.id


def _wait_for(page: WimiPage, expression: str, *, tries: int = 100) -> object:
    value = None
    for _ in range(tries):
        value = page.eval_js(expression)
        if value:
            return value
        page.wait_for_timeout(100)
    return value


def _goto_deep_dive(page: WimiPage, subject_id: int, exam_id: int) -> None:
    page.eval_js("window.__relationScenarioMark = true")
    page.goto('subject-deep-dive', query={'subject': subject_id, 'exam': exam_id})
    for _ in range(100):
        if not page.eval_js("!!window.__relationScenarioMark"):
            return
        page.wait_for_timeout(100)
    raise AssertionError('The deep dive never navigated to the second subject')


_ROW_JS = """
    (() => {
        const row = document.querySelector(
            '[data-testid="deep-dive-relations-list"] .relation-item');
        if (!row) return null;
        return {
            direction: row.getAttribute('data-direction'),
            label: row.querySelector('.relation-direction').textContent.trim(),
            subject: row.querySelector('.relation-subject').textContent.trim(),
        };
    })()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_a_symmetric_relation_reads_the_same_from_both_subjects(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    exam_id, sk_id, mel_id = _seed(wimi_session.user.db)
    # Author from the subject with the LARGER id, so canonical ordering
    # has to swap the pair -- the case that would store it twice.
    here, there = max(sk_id, mel_id), min(sk_id, mel_id)
    there_name = 'SY Seborrheic keratosis' if there == sk_id else 'SY Melanoma'
    here_name = 'SY Melanoma' if there == sk_id else 'SY Seborrheic keratosis'
    wimi_page.goto('subject-deep-dive', query={'subject': here, 'exam': exam_id})
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-add\"]')",
    ), 'The Related Topics add action never rendered'

    # ---- Act ---------------------------------------------------------
    wimi_page.locator(testid='deep-dive-relations-add').click()
    assert _wait_for(
        wimi_page, "!!document.querySelector('[data-testid=\"relation-modal\"]')")
    chose = wimi_page.eval_js(
        """
        (() => {
            const select = document.querySelector('[data-testid="relation-direction"]');
            const opt = Array.from(select.options)
                .find(o => o.value.endsWith('|symmetric'));
            if (!opt) return null;
            select.value = opt.value;
            select.dispatchEvent(new Event('change'));
            return opt.textContent.trim();
        })()
        """
    )
    assert chose and 'confused with' in chose, (
        f'The modal offered no symmetric "confused with" choice: {chose!r}')
    wimi_page.locator(testid='relation-search').fill(there_name[3:9])
    assert _wait_for(
        wimi_page,
        f"!!document.querySelector('[data-testid=\"relation-result-{there}\"]')",
    ), 'The picker did not offer the other subject'
    wimi_page.eval_js(
        f"document.querySelector('[data-testid=\"relation-result-{there}\"]').click()")
    wimi_page.locator(testid='relation-reason').fill(REASON)
    wimi_page.locator(testid='relation-save').click()

    # ---- Assert: the authoring end -------------------------------------
    authoring = _wait_for(wimi_page, _ROW_JS)
    assert authoring == {
        'direction': 'symmetric', 'label': 'Confused with', 'subject': there_name,
    }, f'The authoring end rendered it wrong: {authoring!r}'

    # ---- Assert: the other end -----------------------------------------
    _goto_deep_dive(wimi_page, there, exam_id)
    other = _wait_for(wimi_page, _ROW_JS)
    assert other == {
        'direction': 'symmetric', 'label': 'Confused with', 'subject': here_name,
    }, f'The other end rendered it wrong: {other!r}'

    rows = wimi_session.user.db.fetchall(
        "SELECT from_subject_id, to_subject_id FROM subject_relations")
    assert [(r['from_subject_id'], r['to_subject_id']) for r in rows] == [(there, here)], (
        'A symmetric relation must be stored once, in canonical order.')
