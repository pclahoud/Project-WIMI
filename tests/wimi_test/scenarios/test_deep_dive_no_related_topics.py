"""Regression: the subject deep dive shows no "Related Topics" panel.

Forgejo issue #14, interim decision (owner, 2026-09-14):

    Hide "Related Topics (Siblings)" on the subject deep dive until the
    relation feature exists. The panel is wrong today for any
    multi-parent subject, and it is wrong in a way the user cannot
    detect — it presents legacy single-parent siblings as though they
    were meaningful relations. Showing something misleading is worse
    than showing nothing.

The owner's "siblings" are semantic relations between topics
("hypertension leads to hypertensive nephrosclerosis"), not "shares a
parent in the tree". That feature is still parked pending a design
discussion about the authoring workflow; nothing here anticipates it.

The subject seeded below is deliberately the case the old panel handled
worst: two parents, each with a peer carrying entries, so before the
change the panel rendered two or three rows whose membership depended on
which parent the view happened to be scoped to. The assertions are that
the card, its heading, its list container and its empty state are all
gone — a hidden-but-present container, or a lone "Related Topics" heading
over nothing, would be the obvious half-fix.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _seed(db) -> tuple[int, int]:
    """Multi-parent subject with a peer under each parent.

    Returns ``(exam_context_id, subject_id)``.
    """
    exam = db.create_exam_context(
        exam_name='Related Topics Removal Exam',
        exam_description='issue #14 — the sibling panel is gone',
    )

    cardio = db.create_subject_node(
        exam_context=exam.exam_name, name='RTR Cardiovascular',
        level_type='System', exam_weight_low=20, exam_weight_high=20,
    )
    renal = db.create_subject_node(
        exam_context=exam.exam_name, name='RTR Renal',
        level_type='System', exam_weight_low=15, exam_weight_high=15,
    )
    # The subject under test: one node, two parents.
    hypertension = db.create_subject_node(
        exam_context=exam.exam_name, name='RTR Hypertension',
        level_type='Topic', parent_id=cardio.id,
    )
    db.add_edge(renal.id, hypertension.id, is_primary=False)

    # A peer under each parent, each with an entry, so the old panel had
    # rows to draw no matter which parent context the page was in.
    peers = [
        db.create_subject_node(
            exam_context=exam.exam_name, name='RTR Heart Failure',
            level_type='Topic', parent_id=cardio.id,
        ),
        db.create_subject_node(
            exam_context=exam.exam_name, name='RTR Nephrotic Syndrome',
            level_type='Topic', parent_id=renal.id,
        ),
    ]

    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=3, total_incorrect=3,
        session_name='RTR session', date_encountered=date.today(),
    )
    for subject in peers + [hypertension]:
        db.create_question_entry(
            review_session_id=session.id,
            user_answer='A', correct_answer='B', perceived_difficulty=3,
            reflection='Mixed up the mechanism.',
            explanation='Renin-angiotensin.',
            primary_subject_ids=[subject.id],
        )
    db.conn.commit()
    return exam.id, hypertension.id


@pytest.mark.slow
@pytest.mark.regression
def test_deep_dive_renders_no_related_topics_panel(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    exam_id, subject_id = _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto('subject-deep-dive', query={'subject': subject_id, 'exam': exam_id})

    # Wait for the page to finish rendering rather than guessing: the
    # Recommendations card is the surviving half of the same section, so
    # its arrival means renderRelatedTopics' old slot has been passed.
    rendered = None
    for _ in range(100):
        rendered = wimi_page.eval_js(
            "(() => { const el = document.querySelector("
            "'[data-testid=\"deep-dive-list-recommendations\"]'); "
            "return !!el; })()"
        )
        if rendered:
            break
        wimi_page.wait_for_timeout(100)
    assert rendered, 'The deep dive never finished rendering its Recommendations card'

    # ---- Assert ------------------------------------------------------
    leftovers = wimi_page.eval_js(
        """
        (() => ({
            list: !!document.getElementById('relatedTopicsList'),
            listTestid: !!document.querySelector(
                '[data-testid="deep-dive-list-related-topics"]'),
            emptyState: !!document.querySelector(
                '[data-testid="deep-dive-empty-state-related-topics"]'),
            item: !!document.querySelector('[data-testid^="deep-dive-related-topic-"]'),
            card: !!document.querySelector('.related-card'),
            heading: Array.from(document.querySelectorAll('h1, h2, h3, h4'))
                .some(h => /related topics/i.test(h.textContent || '')),
        }))()
        """
    )

    assert leftovers == {
        'list': False,
        'listTestid': False,
        'emptyState': False,
        'item': False,
        'card': False,
        'heading': False,
    }, (
        'The deep dive still carries part of the Related Topics panel. '
        'Issue #14 removed it outright — an empty container or a stray '
        f'heading is the half-fix it warns about: {leftovers!r}'
    )

    # ...and the page it was removed from is still whole: the surviving
    # card in the same section renders, and the header did too.
    subject_name = wimi_page.eval_js(
        "(() => { const el = document.getElementById('subjectTitle'); "
        "return el ? el.textContent.trim() : null; })()"
    )
    assert subject_name == 'RTR Hypertension', (
        f'Deep dive did not render its subject after the removal: {subject_name!r}'
    )
