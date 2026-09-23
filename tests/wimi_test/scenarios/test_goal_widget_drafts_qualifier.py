"""Regression: the weekly goal names the drafts it is not counting.

Forgejo issue #12. The owner's decision was "drafts count everywhere,
except goals" — a goal of "log 20 entries this week" means 20 *finished*
entries, so goals keep their ``is_draft = FALSE``. The decision attached
a condition to that exemption:

    Goals gain a qualifier showing the outstanding drafts alongside the
    goal progress [...] The qualifier is part of this issue, not a
    follow-up. A goal that silently ignores three drafts is the same
    information gap this issue is about, just moved.

Backend coverage lives in ``tests/database/test_draft_policy_by_surface.py``
(``get_user_goals`` carries ``drafts_remaining``; ``_count_entries_in_period``
still excludes drafts). This scenario proves the other half — that the
number reaches the screen. A payload field nothing renders would satisfy
the letter of the decision and none of it.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _seed(db) -> int:
    """One exam, one weekly goal, one finished entry and two drafts.

    The drafts carry a primary subject, which is what a real unfinished
    entry usually has — it is the reflection that is missing. Returns the
    exam context id.
    """
    exam = db.create_exam_context(
        exam_name='Goal Drafts Qualifier Exam',
        exam_description='issue #12 — goals name their outstanding drafts',
    )
    subject = db.create_subject_node(
        exam_context=exam.exam_name,
        name='GDQ Renal',
        level_type='Topic',
        exam_weight_low=10,
        exam_weight_high=10,
    )
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=5,
        total_incorrect=3,
        session_name='GDQ session',
        date_encountered=date.today(),
    )

    db.create_question_entry(
        review_session_id=session.id,
        user_answer='A',
        correct_answer='B',
        perceived_difficulty=3,
        reflection='I confused the two nephron segments.',
        explanation='Loop of Henle vs distal tubule.',
        primary_subject_ids=[subject.id],
    )
    for _ in range(2):
        draft = db.create_question_entry(
            review_session_id=session.id,
            user_answer='A',
            correct_answer='C',
            perceived_difficulty=4,
            explanation='Started, never reflected on.',
            primary_subject_ids=[subject.id],
        )
        assert draft.is_draft, 'seed produced a finished entry, not a draft'

    db.set_weekly_goal(target_questions=20, exam_context_id=exam.id)
    db.conn.commit()
    return exam.id


@pytest.mark.slow
@pytest.mark.regression
def test_goal_widget_shows_outstanding_drafts(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The analytics dashboard's weekly goal card says "2 drafts remaining"."""
    # ---- Arrange -----------------------------------------------------
    exam_id = _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    # ``?exam=`` is what sets the dashboard's currentExamFilter, which is
    # then handed to the goal widget's load().
    wimi_page.goto('analytics', query={'exam': exam_id})

    # The dashboard fans out a dozen bridge calls in parallel; poll for
    # the goal card rather than guessing a settle time.
    qualifier = None
    for _ in range(100):
        qualifier = wimi_page.eval_js(
            "(() => { const el = document.querySelector("
            "'[data-testid=\"goal-drafts-remaining\"]'); "
            "return el ? el.textContent.trim() : null; })()"
        )
        if qualifier:
            break
        wimi_page.wait_for_timeout(100)

    # ---- Assert ------------------------------------------------------
    goal_html = wimi_page.eval_js(
        "(() => { const el = document.getElementById('goalWidget'); "
        "return el ? el.textContent.trim() : null; })()"
    )
    assert qualifier, (
        'The weekly goal card rendered no drafts qualifier. Two of the '
        'three entries this week are drafts and the goal silently '
        'excludes them, which is the information gap issue #12 is about. '
        f'Goal card text was: {goal_html!r}'
    )
    assert '2 drafts remaining' in qualifier, (
        f'Qualifier did not report the two outstanding drafts: {qualifier!r}'
    )

    # The exclusion itself is unchanged: progress still reads from the
    # finished work only, so the qualifier adds information rather than
    # quietly redefining what the goal means.
    assert goal_html and '/20' in goal_html, (
        f'Goal progress is missing from the card entirely: {goal_html!r}'
    )

    # Bug context: before the fix, get_user_goals returned no
    # ``drafts_remaining`` at all and GoalWidget had nothing to render —
    # the card showed progress against a target while saying nothing
    # about the two entries it had declined to count. The assertion
    # above fails on the unfixed tree because the element does not
    # exist, not because its text differs.
