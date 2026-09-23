"""Regression: the weekly goal card advances when an entry is logged.

Forgejo issue #70. ``get_user_goals`` returned the **stored**
``goal_periods.achieved_value`` whenever a period row existed for the
current week, and ``set_weekly_goal`` writes that row. The achievement
was therefore stamped at the moment the goal was created and nothing
refreshed it: ``update_goal_progress``, the notifier meant to, had no
callers anywhere in the repo, and re-saving the goal did not help either.
So the card froze at whatever the student had logged when they set the
goal, for the rest of that week -- the week they are most likely to be
watching it.

This scenario is the *screen* half of the fix: the card re-renders
against the same document, with no navigation, and must show the new
number. Backend: ``tests/database/test_goal_progress_is_live.py``.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import re
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


SESSION_QUESTIONS = 40
SEEDED_ENTRIES = 1
LOGGED_LATER = 2
TARGET = 20
MARKER = '__issue70_same_document'


def _log_entry(db, session_id: int, subject_id: int):
    entry = db.create_question_entry(
        review_session_id=session_id,
        user_answer='A',
        correct_answer='B',
        perceived_difficulty=3,
        reflection='I confused preload with afterload.',
        explanation='Starling curve.',
        primary_subject_ids=[subject_id],
    )
    assert not entry.is_draft, 'seed produced a draft, not a finished entry'
    return entry


def _seed(db) -> tuple[int, int, int]:
    """One exam, a 40-question session, one finished entry, then the goal.

    The goal is set *after* the first entry so a period row exists for
    this week with a stamp in it -- the exact state that used to freeze.
    Returns ``(exam_id, session_id, subject_id)``.
    """
    exam = db.create_exam_context(
        exam_name='Live Goal Progress Exam',
        exam_description='issue #70 — goal progress must not freeze',
    )
    subject = db.create_subject_node(
        exam_context=exam.exam_name,
        name='LGP Cardio',
        level_type='Topic',
        exam_weight_low=10,
        exam_weight_high=10,
    )
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=SESSION_QUESTIONS,
        total_incorrect=5,
        session_name='LGP session',
        date_encountered=date.today(),
    )
    for _ in range(SEEDED_ENTRIES):
        _log_entry(db, session.id, subject.id)

    db.set_weekly_goal(target_questions=TARGET, exam_context_id=exam.id)
    db.conn.commit()
    return exam.id, session.id, subject.id


def _progress(page: WimiPage) -> int | None:
    """The ``N/TARGET`` reading on the goal card, or None if not rendered."""
    text = page.eval_js(
        "(() => { const el = document.getElementById('goalWidget'); "
        "return el ? el.textContent.trim() : ''; })()"
    )
    match = re.search(r'(\d+)/%d' % TARGET, text or '')
    return int(match.group(1)) if match else None


@pytest.mark.slow
@pytest.mark.regression
def test_goal_card_advances_when_an_entry_is_logged(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The card goes 1/20 → 3/20 in the same document, with no navigation."""
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam_id, session_id, subject_id = _seed(db)

    wimi_page.goto('analytics', query={'exam': exam_id})

    initial = None
    for _ in range(100):
        initial = _progress(wimi_page)
        if initial is not None:
            break
        wimi_page.wait_for_timeout(100)

    assert initial == SEEDED_ENTRIES, (
        f'The weekly goal card did not start at {SEEDED_ENTRIES}/{TARGET}: '
        f'{initial!r}. A reading of {SESSION_QUESTIONS} means the goal is '
        'counting questions answered (issue #58), not entries logged.'
    )
    # Stamp the document so a reload cannot masquerade as a re-render.
    wimi_page.eval_js(f"window.{MARKER} = true")

    # ---- Act ---------------------------------------------------------
    for _ in range(LOGGED_LATER):
        _log_entry(db, session_id, subject_id)
    db.conn.commit()

    wimi_page.eval_js(f"window.goalWidget.load({exam_id})", await_promise=True)

    after = None
    for _ in range(100):
        after = _progress(wimi_page)
        if after != initial:
            break
        wimi_page.wait_for_timeout(100)

    # ---- Assert ------------------------------------------------------
    assert after == SEEDED_ENTRIES + LOGGED_LATER, (
        f'The weekly goal card still reads {after}/{TARGET} after '
        f'{LOGGED_LATER} more entries were logged this week. Before the '
        'fix it returned the achieved_value stamped into goal_periods '
        'when set_weekly_goal ran, so the card was frozen for the rest '
        'of the week the goal was set in (issue #70).'
    )
    assert wimi_page.eval_js(f"window.{MARKER} === true") is True, (
        'The document was replaced, so this proves nothing about a live '
        'card — only that a fresh page load reads the right number.'
    )

    # Bug context: the number came from a row written once, at
    # goal-creation time, that nothing refreshed. Progress is recounted
    # on every read now, which is why a re-render alone is enough.
