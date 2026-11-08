"""Review Entries stops the study timer, and completes the session only when
nothing in it is unfinished.

The bug (``docs/bugs/bugs.md``, *Question Review Timer does not stop when
user selects the complete review button*): the session-complete modal's
``#complete-review`` handler closed the modal and left the timer running.
It now calls ``autoSuspendTimerForNavigation()`` and marks the session
``completed`` -- but only while no entry slot is unfinished (#714,
``firstUnfinishedSlot(getEntrySlotCount()) === -1`` in ``showSessionComplete``).

**Why this file was flaky, and why it is two tests now (#917).** It used to
seed a one-slot session with NO saved entry, open the modal straight after
``goto`` and assert the session became ``completed``. Once the page has
loaded the session that slot is unfinished, so #714 correctly leaves the
session ``in_progress``: measured 5 failures in 5 runs with a wait for the
form. It passed only when the click beat the page's own load, while
``EntryState.session`` was still empty and the slot count read 0 -- about
8 runs in 10. So the test asserted the behaviour #714 forbids, and passed
by racing the load. Both tests now wait for the form, and the session's
state is chosen on purpose: one finished entry (completes) and one
unfinished slot (the timer stops, the session stays open).

**The timer half had never been tested either.** The seeded session had no
``session_duration_minutes``, so ``initSessionTimer()`` returned before any
round was running and "the timer is stopped" was true from the start:
deleting ``autoSuspendTimerForNavigation()`` from the handler left the old
test green. The seed now sets a duration, each test first asserts a round
is running on the page, and the check reads the paused round in the page's
state and in ``session_timer_rounds``.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from _helpers.w114_form_ready import wait_for_form_ready
from wimi_test.db.assertions import assert_session_completed
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

FULL = dict(user_answer="a", correct_answer="b", reflection="<p>R</p>",
            explanation="<p>E</p>")

def _assert_round_paused(page: WimiPage, db: Any, round_id: int) -> None:
    """The press paused the running round: in the page's state and in the
    database (autoSuspendTimerForNavigation -> pauseRoundTimer). Polled,
    because the bridge write is asynchronous (#84)."""
    for _ in range(50):
        if page.eval_js("EntryState.timerPaused === true") \
                and db.get_timer_round(round_id).timer_paused_at:
            return
        page.wait_for_timeout(100)
    raise AssertionError(
        "the timer was not stopped: page timerPaused="
        f"{page.eval_js('EntryState.timerPaused')}, round timer_paused_at="
        f"{db.get_timer_round(round_id).timer_paused_at!r}")


def _seed(db: Any, name: str, *, finished: bool) -> tuple[int, int]:
    """A one-slot session with a running timer round; the slot holds a
    finished entry, or nothing at all."""
    exam = db.create_exam_context(exam_name=f"{name} Exam", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name=f"{name} session", date_encountered=date.today(),
        # Without a duration initSessionTimer() returns at once, so no round
        # is running on the page and a timer assertion can only pass. The
        # old version of this file had exactly that gap (#917).
        session_duration_minutes=30)
    if finished:
        subj = db.create_subject_node(exam_context=exam.exam_name,
                                      name=f"{name} Cardiology", level_type="System")
        entry = db.create_question_entry(review_session_id=session.id,
                                         primary_subject_ids=[subj.id], **FULL)
        assert not entry.is_draft, "the seeded entry must be finished"
    rnd = db.create_timer_round(session_id=session.id, duration_minutes=30)
    db.conn.commit()
    return session.id, rnd.id


def _press_review_entries(page: WimiPage, session_id: int) -> None:
    page.goto("entry-form", query={"session_id": session_id})
    # The whole point of #917: act on the LOADED page, never ahead of it.
    wait_for_form_ready(page)
    assert page.eval_js("getEntrySlotCount()") == 1, "the session did not load"
    # Positive control: a round is running on the page before the press, so
    # a passing timer assertion below means the press stopped it.
    running = page.eval_js("!!EntryState.activeRound && !EntryState.timerPaused"
                           " && !EntryState.timerExpired")
    assert running, "no running timer round on the page before the press"
    # showSessionComplete() is the state a save of the last entry reaches;
    # the modal's fade is forced off so the button is in place at once.
    page.eval_js("""(() => {
        showSessionComplete();
        const m = document.getElementById('complete-modal');
        m.style.transition = 'none'; m.style.opacity = '1';
        m.style.visibility = 'visible';
    })()""")
    # A JS click: the handler under test is the one showSessionComplete()
    # just bound, and QtWebEngine drops the CDP click on this forced modal.
    page.eval_js("document.getElementById('complete-review').click()")


@pytest.mark.slow
@pytest.mark.regression
def test_review_entries_stops_the_timer_and_completes_a_finished_session(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    session_id, round_id = _seed(db, "W917 done", finished=True)

    _press_review_entries(wimi_page, session_id)

    _assert_round_paused(wimi_page, db, round_id)
    # The status write is the handler's last await; wait for it to land.
    for _ in range(50):
        if db.get_review_session(session_id).session_status == "completed":
            break
        wimi_page.wait_for_timeout(100)
    assert_session_completed(db, session_id)


@pytest.mark.slow
@pytest.mark.regression
def test_review_entries_stops_the_timer_but_leaves_an_unfinished_session_open(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The control, and #714's rule: an unfinished slot keeps the session
    open, while the timer still stops."""
    db = wimi_session.user.db
    session_id, round_id = _seed(db, "W917 open", finished=False)

    _press_review_entries(wimi_page, session_id)

    _assert_round_paused(wimi_page, db, round_id)
    # Give a wrong completion every chance to land before asserting it did not.
    wimi_page.wait_for_timeout(1500)
    status = db.get_review_session(session_id).session_status
    assert status == "in_progress", (
        f"a session with an unfinished slot was marked {status!r} (#714)")
