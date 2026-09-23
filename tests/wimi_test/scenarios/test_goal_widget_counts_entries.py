"""Regression: the weekly goal card counts entries, not questions.

Forgejo issue #58. ``set_weekly_goal`` stores the goal as
``goal_type = 'weekly_entries'``, but every progress path used to send
that type to a counter that sums ``review_sessions.total_questions``.
The card therefore showed questions answered under a target the student
had set in entries, and logging an entry moved nothing.

Backend coverage is in ``tests/database/test_weekly_goal_counts_entries.py``
(one test per dispatch site, plus one proving the goal moves with entries
and not with questions). This scenario proves the corrected number reaches
the screen -- the seed keeps entries and questions far apart so the card
cannot show the right value by coincidence.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import re
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


SESSION_QUESTIONS = 12
FINISHED_ENTRIES = 3
TARGET = 20


def _seed(db) -> int:
    """One exam, a 12-question session, 3 finished entries and 1 draft.

    The goal is set after the entries exist, as a student would. Order
    used to matter -- ``set_weekly_goal`` stamped the week's period row
    on creation and nothing recomputed it later -- until issue #70 made
    progress a live count. Returns the exam context id.
    """
    exam = db.create_exam_context(
        exam_name='Goal Counts Entries Exam',
        exam_description='issue #58 — weekly goals count entries logged',
    )
    subject = db.create_subject_node(
        exam_context=exam.exam_name,
        name='GCE Cardio',
        level_type='Topic',
        exam_weight_low=10,
        exam_weight_high=10,
    )
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=SESSION_QUESTIONS,
        total_incorrect=4,
        session_name='GCE session',
        date_encountered=date.today(),
    )

    for _ in range(FINISHED_ENTRIES):
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer='A',
            correct_answer='B',
            perceived_difficulty=3,
            reflection='I confused preload with afterload.',
            explanation='Starling curve.',
            primary_subject_ids=[subject.id],
        )
        assert not entry.is_draft, 'seed produced a draft, not a finished entry'

    draft = db.create_question_entry(
        review_session_id=session.id,
        user_answer='A',
        correct_answer='C',
        perceived_difficulty=4,
        explanation='Started, never reflected on.',
        primary_subject_ids=[subject.id],
    )
    assert draft.is_draft, 'seed produced a finished entry, not a draft'

    db.set_weekly_goal(target_questions=TARGET, exam_context_id=exam.id)
    db.conn.commit()
    return exam.id


@pytest.mark.slow
@pytest.mark.regression
def test_goal_widget_counts_entries_not_questions(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The analytics dashboard's weekly goal card reads 3/20, not 12/20."""
    # ---- Arrange -----------------------------------------------------
    exam_id = _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    # ``?exam=`` sets the dashboard's currentExamFilter, which is handed
    # to the goal widget's load().
    wimi_page.goto('analytics', query={'exam': exam_id})

    # The dashboard fans out a dozen bridge calls in parallel; poll for
    # the goal card rather than guessing a settle time.
    target_text = None
    for _ in range(100):
        target_text = wimi_page.eval_js(
            "(() => { const el = document.querySelector("
            "'[data-testid=\"goal-target-text\"]'); "
            "return el ? el.textContent.trim() : null; })()"
        )
        if target_text:
            break
        wimi_page.wait_for_timeout(100)

    goal_text = wimi_page.eval_js(
        "(() => { const el = document.getElementById('goalWidget'); "
        "return el ? el.textContent.trim() : null; })()"
    )

    # ---- Assert ------------------------------------------------------
    assert target_text, f'The weekly goal card never rendered: {goal_text!r}'

    progress = re.search(r'(\d+)/%d' % TARGET, goal_text or '')
    assert progress, f'No progress reading on the goal card: {goal_text!r}'
    assert int(progress.group(1)) == FINISHED_ENTRIES, (
        'The weekly goal card reported '
        f'{progress.group(1)}/{TARGET}. The week holds '
        f'{FINISHED_ENTRIES} finished entries against a '
        f'{SESSION_QUESTIONS}-question session, so a reading of '
        f'{SESSION_QUESTIONS} means the goal is still counting questions '
        f'answered (issue #58). Card text: {goal_text!r}'
    )

    assert 'entries this week' in (target_text or ''), (
        'The goal card still names its target in questions while counting '
        f'entries: {target_text!r}'
    )

    # The draft exclusion (#12) rides on the same counter and only became
    # reachable once #58 routed the goal to it: the fourth entry of the
    # week is unfinished, so it is excluded and named rather than counted.
    assert '1 draft remaining' in (goal_text or ''), (
        f'The outstanding draft went unreported: {goal_text!r}'
    )
