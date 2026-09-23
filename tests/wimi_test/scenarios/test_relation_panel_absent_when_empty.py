"""Regression: with zero relations the deep dive renders no container.

Forgejo issue #14, decision 11 (owner, 2026-09-14):

    Degrade to absent, not to an empty card. Zero relations is the
    normal state for months. Render nothing, or a single unobtrusive
    "link a related topic" action — never a blank canvas. The
    open-learner-model literature found free-form editable models were
    the *least* favoured feature tested, because learners did not trust
    their own judgment.

and the acceptance line:

    With zero relations the panel does not render an empty container.

The assertion is **absence, not emptiness**: an empty card with a
heading over nothing is the obvious half-fix, and it is the shape the
old "Related Topics (Siblings)" panel had before issue #14 removed it.
What may exist at zero is exactly one quiet action and nothing else — no
section, no card, no heading, no empty-state text.

The subject seeded below has entries and children, so the rest of the
page is full: the panel being absent has to be a decision about
relations, not a page that failed to render.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _seed(db):
    exam = db.create_exam_context(
        exam_name='Relation Empty Exam',
        exam_description='issue #14 — zero relations renders nothing',
    )
    cardio = db.create_subject_node(
        exam_context=exam.exam_name, name='EM Cardiovascular',
        level_type='System', exam_weight_low=20, exam_weight_high=20,
    )
    htn = db.create_subject_node(
        exam_context=exam.exam_name, name='EM Hypertension',
        level_type='Topic', parent_id=cardio.id,
    )
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='EM session', date_encountered=date.today(),
    )
    db.create_question_entry(
        review_session_id=session.id, user_answer='A', correct_answer='B',
        perceived_difficulty=3, reflection='Mixed up the mechanism.',
        explanation='Renin-angiotensin.', primary_subject_ids=[htn.id],
    )
    db.conn.commit()
    return exam.id, htn.id


@pytest.mark.slow
@pytest.mark.regression
def test_zero_relations_renders_no_empty_container(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    exam_id, subject_id = _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto('subject-deep-dive', query={'subject': subject_id,
                                               'exam': exam_id})

    # The add action is the one thing that *is* allowed at zero, so its
    # arrival is also the signal that the panel has finished deciding.
    rendered = None
    for _ in range(100):
        rendered = wimi_page.eval_js(
            "!!document.querySelector('[data-testid=\"deep-dive-relations-add\"]')"
        )
        if rendered:
            break
        wimi_page.wait_for_timeout(100)
    assert rendered, 'The "link a related topic" action never rendered'

    # ---- Assert ------------------------------------------------------
    leftovers = wimi_page.eval_js(
        """
        (() => {
            const mount = document.getElementById('relationsMount');
            return {
                panel: !!document.querySelector(
                    '[data-testid="deep-dive-relations-panel"]'),
                list: !!document.querySelector(
                    '[data-testid="deep-dive-relations-list"]'),
                card: !!document.querySelector('.relations-card'),
                section: !!document.querySelector('.relations-section'),
                emptyState: !!(mount && mount.querySelector('.empty-state')),
                heading: Array.from(document.querySelectorAll('h1, h2, h3, h4'))
                    .some(h => /related topics/i.test(h.textContent || '')),
                mountChildren: mount ? mount.children.length : -1,
            };
        })()
        """
    )

    assert leftovers == {
        'panel': False,
        'list': False,
        'card': False,
        'section': False,
        'emptyState': False,
        'heading': False,
        'mountChildren': 1,
    }, (
        'The deep dive rendered a relations container with nothing in it. '
        'Decision 11 is "degrade to absent, not to an empty card" — a '
        'heading over nothing, or a card with an empty-state line, is the '
        f'half-fix it warns about: {leftovers!r}'
    )

    # ...and the rest of the page rendered, so the absence above is a
    # decision about relations rather than a page that never loaded.
    assert wimi_page.eval_js(
        "(() => { const el = document.getElementById('subjectTitle'); "
        "return el ? el.textContent.trim() : null; })()"
    ) == 'EM Hypertension'
    assert wimi_page.eval_js(
        "(() => { const el = document.getElementById('totalMistakes'); "
        "return el ? el.textContent.trim() : null; })()"
    ) == '1'
