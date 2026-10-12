"""Regression: a retired relation type leaves the picker, its relations stay.

Owner's decision, 2026-10-03 (#14; m026): a relation type in use is
**renamed or retired, never deleted**. Retiring removes it from the
choices for a new relation; every relation already using it keeps
rendering with its label.

The two halves pull in opposite directions -- one read must hide retired
types, the other must show them -- which is exactly the shape #210 warned
about. A page that filtered both would lose the relation; a page that
filtered neither would offer the retired type. So both are asserted on the
same page, in the same session.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


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
def test_a_retired_type_leaves_the_picker_and_its_relation_still_renders(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name='Relation Retired Type Exam',
        exam_description='m026 -- retire, never delete',
    )
    drug = db.create_subject_node(
        exam_context=exam.exam_name, name='RT Penicillamine', level_type='Topic')
    disease = db.create_subject_node(
        exam_context=exam.exam_name, name='RT Wilson disease', level_type='Topic')
    treats = next(t['id'] for t in db.get_relation_types(exam.id)
                  if t['label'] == 'treats')
    db.create_subject_relation(
        drug.id, disease.id, 'Chelates copper.', relation_type_id=treats)
    db.retire_relation_type(treats)
    db.conn.commit()

    # ---- Act ---------------------------------------------------------
    wimi_page.goto('subject-deep-dive', query={'subject': drug.id, 'exam': exam.id})
    label = _wait_for(
        wimi_page,
        "(() => { const el = document.querySelector("
        "'[data-testid=\"deep-dive-relations-list\"] .relation-direction'); "
        "return el ? el.textContent.trim() : null; })()",
    )

    # ---- Assert: the existing relation still renders ------------------
    assert label == 'Treats', (
        f'A relation using a retired type must keep rendering: {label!r}')

    # ---- Assert: the picker no longer offers the type ------------------
    wimi_page.locator(testid='deep-dive-relations-add').click()
    options = _wait_for(
        wimi_page,
        "(() => { const s = document.querySelector("
        "'[data-testid=\"relation-direction\"]'); "
        "return s ? Array.from(s.options).map(o => o.textContent.trim()) : null; })()",
    )
    assert options, 'The modal did not render its Relation choices'
    assert not any(' treats' in o or 'treated by' in o for o in options), (
        f'A retired type is still offered for new relations: {options!r}')
    assert any('causes' in o for o in options), (
        f'The active types are missing from the picker: {options!r}')
