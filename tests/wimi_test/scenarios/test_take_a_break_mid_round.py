"""Regression: a student can take a break in the middle of a round (#504).

The owner's answer on #504 was a feature, not a setting: *"I would like for a
true break feature to exist, where a user could take a break in the middle
of a session."* Before this, the only break was the one offered when a
round's clock ran out.

* **Take a break** beside the timer opens a short dialog; starting the break
  stops the round's clock through the same path as Pause, so the break is
  recorded in the round's ``total_break_seconds``.
* During the break the same button reads **End break**; ending it, early or
  on time, starts the round's clock again.
* ``manual_break_control`` -- *Only take breaks when I ask* -- now decides
  only whether the end of a round offers a break by itself.

Every assertion reads the database as well as the page: a button that
changed its label without stopping the clock would be the inert-setting bug
in a new place.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

FORM_READY = "typeof EntryState !== 'undefined' && EntryState.isLoading === false"
BREAK_LABEL = "document.getElementById('btn-take-break').getAttribute('aria-label')"
OVERLAY_SHOWN = ("getComputedStyle(document.getElementById('round-complete-overlay'))"
                 ".display !== 'none'")


def _poll(page: WimiPage, read, want, *, timeout_ms: int = 15000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if last == want:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def _seed(db, *, minutes_ago: int = 0):
    exam = db.create_exam_context(exam_name="Break Exam")
    # The timer only mounts for a session with a duration.
    session = db.create_review_session(exam_context_id=exam.id, total_questions=10,
                                       total_incorrect=1, session_name="Break Session",
                                       session_duration_minutes=30)
    round_ = db.create_timer_round(session_id=session.id, duration_minutes=30)
    if minutes_ago:
        with db.transaction():
            db.execute("UPDATE session_timer_rounds SET started_at = datetime('now', ?) WHERE id = ?",
                       (f"-{minutes_ago} minutes", round_.id))
    return session, round_


def _open_form(page: WimiPage, session_id: int) -> None:
    page.goto("entry-form", query={"session_id": session_id})
    assert _poll(page, lambda: page.eval_js(FORM_READY), True) is True, "the entry form never got ready"


@pytest.mark.slow
@pytest.mark.regression
def test_a_mid_round_break_stops_the_clock_and_ending_it_starts_it_again(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    session, round_ = _seed(db)
    _open_form(wimi_page, session.id)
    assert wimi_page.eval_js(BREAK_LABEL) == "Take a break"
    assert db.get_timer_round(round_.id).timer_paused_at is None, "control: the round is running"

    wimi_page.eval_js("document.getElementById('btn-take-break').click()")
    assert _poll(wimi_page, lambda: wimi_page.eval_js(
        "getComputedStyle(document.getElementById('take-break-dialog-overlay')).display !== 'none'"),
        True) is True, "Take a break opened no dialog"
    wimi_page.eval_js("document.getElementById('take-break-duration').value = '1'")
    wimi_page.eval_js(
        "document.querySelector('[data-testid=\"entry-form-take-break-start-button\"]').click()")

    assert _poll(wimi_page, lambda: db.get_timer_round(round_.id).timer_paused_at is not None,
                 True) is True, "the break did not stop the round's clock"
    assert _poll(wimi_page, lambda: wimi_page.eval_js(BREAK_LABEL), "End break") == "End break"
    assert wimi_page.eval_js(
        "document.getElementById('session-timer').classList.contains('timer-break')")

    wimi_page.wait_for_timeout(1500)  # so the break has a measurable length
    wimi_page.eval_js("document.getElementById('btn-take-break').click()")

    assert _poll(wimi_page, lambda: db.get_timer_round(round_.id).timer_paused_at is None,
                 True) is True, "ending the break did not start the round's clock again"
    assert (db.get_timer_round(round_.id).total_break_seconds or 0) >= 1, (
        "the break was not recorded against the round")
    assert _poll(wimi_page, lambda: wimi_page.eval_js(BREAK_LABEL), "Take a break") == "Take a break"
    assert wimi_page.eval_js(
        "getComputedStyle(document.getElementById('btn-timer-pause')).display !== 'none'"), (
        "the pause button did not come back after the break")


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("manual, offered", [(False, True), (True, False)])
def test_the_end_of_a_round_offers_a_break_unless_the_student_said_not_to(
    wimi_session: WimiTestSession, wimi_page: WimiPage, manual: bool, offered: bool,
) -> None:
    db = wimi_session.user.db
    db.update_settings(manual_break_control=manual)
    session, _ = _seed(db, minutes_ago=40)  # a 30-minute round, already over

    _open_form(wimi_page, session.id)

    assert _poll(wimi_page, lambda: wimi_page.eval_js(
        "document.getElementById('session-timer').classList.contains('timer-expired')"),
        True) is True, "control: the seeded round never read as over"
    wimi_page.wait_for_timeout(500)
    assert wimi_page.eval_js(OVERLAY_SHOWN) is offered, (
        f"manual_break_control={manual}: the round-end break offer "
        f"{'did not appear' if offered else 'appeared anyway'}")
    assert wimi_page.eval_js(BREAK_LABEL) == "Take a break", "the button stays either way"


@pytest.mark.slow
@pytest.mark.regression
def test_the_dialog_names_the_state_the_student_is_actually_in(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The message is rewritten per state, not static (#504, #174/#289).

    It shipped as fixed markup reading "The round's clock stops while you are
    away and starts again when the break ends." That is true mid-round and
    false between rounds, where there is no clock to stop -- and the break
    itself works there, so the only wrong thing was the sentence. The #174
    class: a surface stating something it does not know.

    **Both arms are asserted and the mid-round one is the control.** Without it
    this passes against a dialog that always shows the between-rounds wording,
    which would be the same defect pointing the other way.
    """
    db = wimi_session.user.db
    read = lambda: wimi_page.eval_js(
        "(document.getElementById('take-break-message') || {}).textContent || ''")
    open_dialog = lambda: wimi_page.eval_js("openTakeBreakDialog(); true")

    # --- between rounds: the round is ended before the form opens ----------
    session, round_ = _seed(db)
    db.end_timer_round(round_.id)
    _open_form(wimi_page, session.id)
    open_dialog()
    between = _poll(wimi_page, read, None, timeout_ms=2000) or read()

    assert "clock stops" not in between, (
        f"no round is running, so nothing claims a clock stops: {between!r}")
    assert "no clock to stop" in between, between

    # --- mid-round: the control -------------------------------------------
    # A second session on the SAME exam: exam_contexts is unique per name per
    # user, so _seed cannot be called twice.
    exam = db.get_exam_context_by_name("Break Exam")
    session2 = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=1,
        session_name="Break Session 2", session_duration_minutes=30)
    db.create_timer_round(session_id=session2.id, duration_minutes=30)
    _open_form(wimi_page, session2.id)
    open_dialog()
    mid = _poll(wimi_page, read, None, timeout_ms=2000) or read()

    assert "clock stops" in mid, (
        f"a round IS running, so the clock sentence is the right one: {mid!r}")
    assert mid != between, "the message is static again"
