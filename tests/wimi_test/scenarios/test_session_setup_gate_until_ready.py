"""Issue #120 - session setup swallows input and reverts the chosen date.

    "**The form gets stuck.** Every keystroke in that window is swallowed, so
    `validateForm()` never runs and `#btn-start-session` stays `disabled` on
    a form that visibly has every required field filled in. [...] **Two
    fields are reverted.** `session_setup.js:1193` unconditionally does
    `document.getElementById('session-date').value = getTodayDateString()`,
    and `initializeSessionDuration()` overwrites `#session-duration-preset`
    and `#session-duration-custom` from `api.getUserPreferences()` after its
    own `await`. A student who back-dated the session or picked a duration
    loses that choice."

The fix is #114's gate, applied as ``docs/guides/PAGE_GATE.md`` describes:
``.session-page`` ships ``inert`` and ``markSessionSetupReady()`` removes it,
from the init ``finally`` and from the pre-``try`` "no exam id" return.

The date reset has no cause other than this window
--------------------------------------------------
Worth stating because a gate stops a student *choosing* a value early and does
not by itself stop a reset. Measured by reading every write to that field:
``#session-date`` ships with no ``value`` attribute, so the assignment is the
page's *default*, not a correction of anything; nothing else in
``session_setup.js`` or ``session_import.js`` writes it (the import wizard owns
a separate ``#import-session-date``); ``startSession()`` navigates away rather
than resetting; and ``initializeSessionSetup`` is reached only from one
``DOMContentLoaded`` listener, so it runs once per document. The test below
pins the consequence: the default is already in the field *while the page is
still gated*, so no student input can precede it.

What that reading **did** turn up is a different defect in the same line:
``getTodayDateString()`` computes the date in UTC, so in a negative-offset
timezone the default is *tomorrow*. Filed as **#286** and deliberately not
fixed here — it is wrong with or without a gate.

Why these tests are built the way they are
------------------------------------------
``inert`` blocks hit-tested input and focus but **not** ``el.value = 'x'`` or
``el.click()``. A test written with those passes against a completely ungated
page, so every gesture here goes through ``Input.dispatchMouseEvent`` /
``Input.insertText`` and the window is widened by holding the page's bridge
calls from a document-start hook. See ``_helpers/w114_form_ready.py``.

``#session-date`` is a ``type="date"`` input, which cannot be driven by
``Input.insertText``. What is asserted about it is **focus**: a real click
reaches it after handover and is refused before. That is the same measurement
as the typing probe, through the one channel this control has.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from _helpers.page_gate import (
    assert_gate_can_be_heard,
    assert_still_gated,
    ax_mentions,
    ax_snapshot,
    ax_summary,
    enable_accessibility,
    gate_state,
    is_gated,
    wait_for_release,
)
from _helpers.w114_form_ready import (
    assert_slow_bridge_took,
    centre_of,
    install_slow_bridge,
    poll,
    real_click,
    real_type,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PAGE_RENDERED = "(() => !!document.getElementById('session-total-questions'))()"
DATE_VALUE = "document.getElementById('session-date').value"
QUESTIONS_VALUE = "document.getElementById('session-total-questions').value"
INCORRECT_VALUE = "document.getElementById('session-total-incorrect').value"
ACTIVE_ID = (
    "(() => document.activeElement ? document.activeElement.id"
    " || document.activeElement.tagName : null)()"
)
# `validateForm()` ran and found incorrect > total. This is the observable
# proof that a real keystroke reached a bound handler, and it needs no
# question source: the error branch is reached from the two counts alone.
FORM_ERROR_SHOWN = (
    "(() => { const c = document.getElementById('form-error');"
    " return !!c && !c.classList.contains('hidden'); })()"
)

HOLDING = "Preparing the session form"
READY = "Session form ready"

# A label only the gated container has.
PAGE_ONLY = "Start Session"


def _today_candidates() -> list[str]:
    """Today, as this host's clock means it.

    This used to accept **two** values -- the local date and the UTC date --
    because ``getTodayDateString()`` was ``new Date().toISOString()
    .split('T')[0]``, which is UTC, and in a negative-offset zone an evening
    load defaulted the field to *tomorrow*. That was filed as **#286** rather
    than fixed here, because it is wrong with or without a gate.

    **#286 is fixed**, so the leniency is gone: the local date is the only
    right answer, and accepting the UTC one would let the defect back in
    sixteen hours a day.

    The old wording also claimed "this box runs UTC". It does not; it is
    ``America/New_York``, and #286 was invisible here for sixteen hours a day
    rather than invisible by location. The timezone-driven assertion lives in
    ``test_session_date_defaults_to_local_day.py``, which does not depend on
    what the host's zone happens to be.

    This function now only supplies the *failure message*. The assertion
    itself (``DATE_IS_TODAY``) asks the page for its own local day at the
    moment it reads the field, so there is no import-time snapshot to go
    stale across local midnight.
    """
    return [_dt.date.today().isoformat()]


#: "The field holds the page's own local calendar day." Computed in the page
#: rather than interpolated from Python: one clock, read at assert time.
DATE_IS_TODAY = (
    "(() => { const n = new Date();"
    " const pad = v => String(v).padStart(2, '0');"
    " return " + DATE_VALUE + " === n.getFullYear() + '-'"
    " + pad(n.getMonth() + 1) + '-' + pad(n.getDate()); })()"
)


def _seed(db) -> int:
    exam = db.create_exam_context(exam_name="W120 Exam", exam_description="")
    db.create_question_source(source_name="W120 Bank")
    db.conn.commit()
    return exam.id


@pytest.mark.slow
@pytest.mark.regression
def test_the_form_refuses_input_rather_than_swallowing_and_reverting_it(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Both halves of #120, and the release, each asserted explicitly."""
    # ---- Arrange ----------------------------------------------------------
    exam_id = _seed(wimi_session.user.db)
    install_slow_bridge(wimi_page)
    wimi_page.goto("session-setup", query={"exam_id": exam_id},
                   wait_for_bridge=False)
    assert poll(wimi_page, PAGE_RENDERED), "the session markup never rendered"
    assert_slow_bridge_took(wimi_page)

    # ---- Act: inside the window -------------------------------------------
    assert_still_gated(wimi_page, "before the probe started")

    real_click(wimi_page, centre_of(wimi_page, "#session-date"))
    date_focus_during = wimi_page.eval_js(ACTIVE_ID)
    assert_still_gated(wimi_page, "after clicking the date field")

    real_click(wimi_page, centre_of(wimi_page, "#session-total-questions"))
    real_type(wimi_page, "5")
    real_click(wimi_page, centre_of(wimi_page, "#session-total-incorrect"))
    real_type(wimi_page, "9")
    questions_during = wimi_page.eval_js(QUESTIONS_VALUE)
    incorrect_during = wimi_page.eval_js(INCORRECT_VALUE)
    error_during = wimi_page.eval_js(FORM_ERROR_SHOWN)
    assert_still_gated(wimi_page, "after typing both question counts")

    # ---- Assert: refused, not swallowed -----------------------------------
    assert date_focus_during != "session-date", (
        f"a real click focused the date field during load (activeElement="
        f"{date_focus_during!r}). A date chosen there is overwritten by the "
        f"unconditional `value = getTodayDateString()` later in the chain "
        f"(#120)")
    assert questions_during == "", (
        f"'5' typed during load landed in Total Questions "
        f"(value={questions_during!r}). The `input` handler is not bound "
        f"until initializeFormValidation() at the very end of the chain, so "
        f"the keystroke is swallowed and Start stays disabled on a form that "
        f"looks complete (#120)")
    assert incorrect_during == "", (
        f"'9' typed during load landed in Questions Incorrect "
        f"(value={incorrect_during!r})")
    assert error_during is False, (
        "the validation error appeared during load, which means the handlers "
        "were already bound and this run is measuring the wrong state")

    # ---- Assert: the date default is already in place while gated ---------
    # This is what makes the gate sufficient for the reverted date: the
    # page's own default is written before any input can be accepted, so
    # there is no window in which a student's choice could precede it.
    assert poll(wimi_page, DATE_IS_TODAY, timeout_ms=30000), (
        f"the date default was never written while the page was gated "
        f"(value={wimi_page.eval_js(DATE_VALUE)!r}, expected one of "
        f"{_today_candidates()}). If it lands after the release instead, the "
        f"gate does not cover the reset and #120's second half is still open")
    assert_still_gated(wimi_page, "after the date default was written")

    # ---- Act: after the page is handed over -------------------------------
    wait_for_release(wimi_page)
    date_after_load = wimi_page.eval_js(DATE_VALUE)
    date_still_today = wimi_page.eval_js(DATE_IS_TODAY)

    real_click(wimi_page, centre_of(wimi_page, "#session-date"))
    date_focus_after = wimi_page.eval_js(ACTIVE_ID)

    real_click(wimi_page, centre_of(wimi_page, "#session-total-questions"))
    real_type(wimi_page, "5")
    real_click(wimi_page, centre_of(wimi_page, "#session-total-incorrect"))
    real_type(wimi_page, "9")
    questions_after = wimi_page.eval_js(QUESTIONS_VALUE)
    error_after = poll(wimi_page, FORM_ERROR_SHOWN, timeout_ms=5000)

    # ---- Assert: cleared, as explicitly as it was blocked -----------------
    assert is_gated(wimi_page) is False, (
        "the page stayed gated after init finished. This page does not "
        "redirect when its init fails, so a release reached only from the "
        "happy path leaves a permanently dead form on screen -- far worse "
        "than the bug #120 describes (#114's rule)")
    assert date_still_today is True, (
        f"the date is not today's after handover (value={date_after_load!r}, "
        f"expected one of {_today_candidates()}), so this test is not "
        f"measuring the page the issue is about")
    assert date_focus_after == "session-date", (
        f"a real click did not focus the date field after handover "
        f"(activeElement={date_focus_after!r}) -- the gate never lifted for "
        f"input, and a student still cannot back-date a session")
    assert questions_after == "5", (
        f"typing did not work after handover (value={questions_after!r})")
    assert error_after is True, (
        "9 incorrect of 5 questions did not raise the validation error after "
        "handover, so real keystrokes are still not reaching validateForm() "
        "-- which is #120's 'the form gets stuck' with the gate on top")


@pytest.mark.slow
@pytest.mark.regression
def test_the_gate_is_in_the_accessibility_tree_while_the_form_is_not(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#127 on this page, measured where it is observable at all.

    ``inert`` removes the gated subtree from the accessibility tree, so the
    gate is silence as well as refusal. Measured on settings.html while
    writing this pair: with the status region nested *inside* the gated
    container its DOM state is perfect -- right text, ``role="status"``,
    ``display: block`` -- and the tree holds **1 exposed node of 312**, named
    only by the document title. Outside it: **4 of 315**, the extra three
    being the status node and its text. Every DOM-level assertion passes on
    the broken version, which is why this goes through the tree.

    No screen reader was run - this box has none and CDP cannot observe an
    announcement.
    """
    # ---- Arrange ----------------------------------------------------------
    exam_id = _seed(wimi_session.user.db)
    install_slow_bridge(wimi_page)
    wimi_page.goto("session-setup", query={"exam_id": exam_id},
                   wait_for_bridge=False)
    assert poll(wimi_page, PAGE_RENDERED), "the session markup never rendered"
    assert_slow_bridge_took(wimi_page)
    enable_accessibility(wimi_page)

    # ---- Act / Assert: inside the window ----------------------------------
    assert is_gated(wimi_page) is True, (
        "the page was not gated when the probe ran, so nothing below is "
        "measuring the window this test is about")
    during_gate = gate_state(wimi_page)
    during_ax = ax_snapshot(wimi_page)

    assert_gate_can_be_heard(during_gate, where="while the gate was up")
    assert HOLDING.lower() in during_gate["text"].lower(), (
        f"the gate carries no holding message while it holds "
        f"(text={during_gate['text']!r}); a screen reader lands on a document "
        f"that is empty and silent (#127)")
    assert ax_mentions(during_ax, HOLDING), (
        f"'{HOLDING}' is NOT in the accessibility tree while the gate is up, "
        f"so a screen reader is still handed an empty document. This is the "
        f"failure mode of putting the status element inside the `inert` "
        f"container: present in the DOM, absent from the tree. "
        f"Tree: {ax_summary(during_ax)}")
    assert not ax_mentions(during_ax, PAGE_ONLY), (
        f"the form itself is already exposed to assistive technology during "
        f"the gate ({PAGE_ONLY!r} is in the tree), so the gate is not doing "
        f"what this test assumes. Tree: {ax_summary(during_ax)}")

    # ---- Act / Assert: after handover -------------------------------------
    wait_for_release(wimi_page)
    after_gate = gate_state(wimi_page)
    after_ax = ax_snapshot(wimi_page)

    assert after_gate["state"] == "ready", (
        f"PageGate.release() never ran: the gate still reads "
        f"state={after_gate['state']!r} after the form was handed over. "
        f"markSessionSetupReady() is the one place that calls it (#127)")
    assert READY.lower() in after_gate["text"].lower(), (
        f"the gate's text did not change to the ready message "
        f"(text={after_gate['text']!r}). The text change IS the "
        f"announcement (#127)")
    assert ax_mentions(after_ax, PAGE_ONLY), (
        f"the form is still not exposed to assistive technology after the "
        f"gate lifted. Tree: {ax_summary(after_ax)}")
    assert after_ax["exposed"] > during_ax["exposed"] * 10, (
        f"the accessibility tree barely grew when the gate lifted "
        f"({during_ax['exposed']} -> {after_ax['exposed']} exposed nodes)")


@pytest.mark.slow
@pytest.mark.regression
def test_a_missing_exam_id_still_releases_and_still_stops_holding(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The early return, which is the exit an `if` at the end would miss.

    ``initializeSessionSetup()`` bails before its ``try`` when the URL carries
    no ``exam_id``, toasts, and redirects 1.5 s later. #114's rule is that
    every exit releases, including that one: leaving the page ``inert`` would
    freeze the last frame the student sees, and leaving the gate holding would
    tell assistive technology the form is being prepared while it is being
    abandoned.
    """
    # ---- Arrange / Act ----------------------------------------------------
    wimi_page.goto("session-setup", wait_for_bridge=False)
    assert poll(wimi_page, PAGE_RENDERED), "the session markup never rendered"
    # Poll rather than settle: the release happens at once, the redirect
    # ~1.5 s later.
    released = poll(
        wimi_page,
        "(() => { const p = document.querySelector('[data-page-gated]');"
        " return !!p && !p.hasAttribute('inert'); })()",
        timeout_ms=10000)

    # ---- Assert -----------------------------------------------------------
    assert released, (
        "the form stayed gated after init bailed for want of an exam id. The "
        "pre-`try` return has to release it too, or the student is left "
        "looking at a dead page until the redirect (#120, #114)")
    state = gate_state(wimi_page)
    assert state["state"] == "ready", (
        f"the form was released but the gate was left holding "
        f"(state={state['state']!r}), so assistive technology is still being "
        f"told the form is being prepared while it is being abandoned (#127)")
    assert HOLDING.lower() not in state["text"].lower(), (
        f"the gate still reads {state['text']!r} after the form was released")


# ---------------------------------------------------------------------------
# Why each assertion catches the regression
# ---------------------------------------------------------------------------
#
# * `questions_during == ""` and `incorrect_during == ""` fail against master,
#   where the inputs ship enabled and the keystroke lands only to be ignored
#   by handlers that do not exist yet. `error_during is False` is their
#   companion: on master the keystrokes land AND validateForm() is unbound, so
#   the error stays hidden with a full form -- exactly #120's "stuck".
# * `questions_after == "5"` and `error_after is True` are the positive
#   control for both: the same gestures, landing and reaching validateForm()
#   once the gate lifts. Without them the four assertions above would pass
#   against a page that refused input forever.
# * `date_focus_during != "session-date"` / `date_focus_after ==
#   "session-date"` are the same pair for the one control that cannot be
#   typed into.
# * The gated-while-today's-date-is-already-set poll is what makes the gate a
#   sufficient fix for the reverted date rather than a plausible one. If the
#   default were written after the release, a student could choose a date in
#   between and lose it, and this would be the only assertion to notice.
# * `test_a_missing_exam_id_...` fails against a release reached only from the
#   init `finally`, which is the shape #114's own early-return call exists to
#   prevent.
