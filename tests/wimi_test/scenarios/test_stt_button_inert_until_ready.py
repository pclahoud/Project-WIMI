"""The microphone cannot be pressed before the form is ready (#59, #114).

``dictation.js`` mounts from ``initRichTextEditors()``, early in
``initializeEntryPage()``'s chain and long before the footer handlers are
bound or the editors report ``isInitialized``. Its click listener is
attached the moment the control is built, so nothing in the component
itself stops a press. The only thing standing between an eleven-o'clock
student and a recording whose transcript has nowhere to land is the
``inert`` attribute on ``.entry-page``.

That matters more here than for a text field. ``insertTranscript`` throws
rather than queueing when the editor is not mounted (``rich_editor.js``),
so a recording started too early ends in an error toast eight seconds
after the student stopped speaking — with the audio already gone.

Why this test is built the way it is
------------------------------------
``inert`` blocks hit-tested pointer events and focus. It does **not**
block ``el.click()``, which dispatches straight to the listener — a
scenario written that way passes against a page with no gate at all. So
the press here goes through ``Input.dispatchMouseEvent``.

The harder trap is vacuity from the *other* side. The button also ships
``disabled`` until ``getSttStatus()`` resolves, and a disabled button
swallows a click whatever ``inert`` is doing. A test that pressed during
that state would prove nothing. So the speech bridge is stubbed from a
document-start hook and both controllers are refreshed as soon as they
exist, which parks the button on ``ready`` — **enabled** — while the page
is still inert. ``assert_enabled_during`` below is the guard: if the
button is not live at the moment of the press, the test fails rather than
passing for the wrong reason.
"""
from __future__ import annotations

import pytest

from _helpers.stt_form import (
    assert_hook_took,
    button_disabled,
    control_state,
    install_slow_bridge_with_stt,
    poll,
    refresh_controllers,
    seed_entry_session,
    stub_calls,
)
from _helpers.w114_form_ready import (
    assert_still_in_window,
    centre_of,
    is_inert,
    real_click,
    wait_for_form_ready,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

BUTTON = '[data-testid="dictation-reflection-button"]'

CONTROLS_MOUNTED = (
    "(() => { try { return Array.isArray(EntryState.dictation)"
    " && EntryState.dictation.length === 2; } catch (e) { return false; } })()"
)

ARM_PROBE = """
(() => {
  const b = document.querySelector('[data-testid="dictation-reflection-button"]');
  if (!b) return false;
  window.__micClicked = false;
  if (!b.__armed) {
    b.__armed = true;
    b.addEventListener('click', () => { window.__micClicked = true; });
  }
  return true;
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_the_microphone_refuses_a_real_press_until_the_form_is_ready(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange ----------------------------------------------------------
    session_id = seed_entry_session(wimi_session.user.db, name="STT inert")
    install_slow_bridge_with_stt(wimi_page)
    wimi_page.goto("entry-form", query={"session_id": session_id},
                   wait_for_bridge=False)

    assert poll(wimi_page, CONTROLS_MOUNTED, timeout_ms=40000), (
        "the two dictation controls never mounted; initDictation() runs from "
        "initRichTextEditors(), so this means the init chain never got there")
    assert_hook_took(wimi_page)
    assert_still_in_window(wimi_page, "once the controls had mounted")

    # The button is live: status resolved through the stub, so `ready` and
    # enabled — while the page has not been handed over.
    refresh_controllers(wimi_page)
    assert poll(wimi_page,
                "(() => { const b = document.querySelector(%r);"
                " const p = document.querySelector('.entry-page');"
                " return !!b && b.disabled === false"
                " && !!p && p.hasAttribute('inert'); })()" % BUTTON,
                timeout_ms=20000), (
        f"the microphone never became enabled while the form was still inert "
        f"(state={control_state(wimi_page, 'reflection')!r}, "
        f"disabled={button_disabled(wimi_page, 'reflection')!r}, "
        f"inert={is_inert(wimi_page)!r}). Without that the press below would "
        f"be refused by `disabled` and the test would prove nothing about the "
        f"gate")

    # ---- Act: a real press, inside the window -----------------------------
    assert wimi_page.eval_js(ARM_PROBE) is True, "the mic button is not in the DOM"
    real_click(wimi_page, centre_of(wimi_page, BUTTON))
    reached_during = wimi_page.eval_js("window.__micClicked === true")
    state_during = control_state(wimi_page, "reflection")
    started_during = stub_calls(wimi_page, "startRecording")
    assert_still_in_window(wimi_page, "after pressing the microphone")

    # ---- Assert: refused --------------------------------------------------
    assert reached_during is False, (
        "a hit-tested press reached the microphone button while .entry-page "
        "was still inert — the recording would start against editors that "
        "have not mounted, and insertTranscript() throws rather than queueing")
    assert state_during not in ("recording", "transcribing"), (
        f"the controller began recording during init (state={state_during!r})")
    assert started_during == [], (
        f"startRecording reached the bridge during init: {started_during!r}")

    # ---- Act: after the form is handed over -------------------------------
    wait_for_form_ready(wimi_page)
    refresh_controllers(wimi_page)
    assert poll(wimi_page,
                "(() => { const b = document.querySelector(%r);"
                " return !!b && b.disabled === false; })()" % BUTTON,
                timeout_ms=20000), "the microphone never became usable"
    real_click(wimi_page, centre_of(wimi_page, BUTTON))

    # ---- Assert: cleared, as explicitly as it was blocked -----------------
    assert is_inert(wimi_page) is False, (
        "the form stayed inert after init finished — a permanently dead "
        "microphone is a worse bug than the one being guarded here")
    assert wimi_page.eval_js("window.__micClicked === true") is True, (
        "the press never reached the button after the form was handed over")
    assert poll(wimi_page,
                "(() => (window.__stt.calls || [])"
                ".some(c => c.name === 'startRecording'))()",
                timeout_ms=15000), (
        f"the press was delivered but no recording started "
        f"(state={control_state(wimi_page, 'reflection')!r}) — the button is "
        f"reachable and inert, which is the same silence from the student's "
        f"side")


# ---------------------------------------------------------------------------
# Why each assertion catches the regression
# ---------------------------------------------------------------------------
#
# * Dropping `inert` from `question_entry.html` — the whole of #114's fix —
#   makes `reached_during` true and `started_during` non-empty. Verified by
#   removing the attribute and re-running: the "during" block fails.
# * Removing the `refresh_controllers` call, or stubbing nothing, leaves the
#   button `disabled` during the window; the precondition poll then fails
#   with a message naming exactly that, rather than the test passing on a
#   click that `disabled` ate.
# * Binding dictation's click listener behind the gate instead of at attach
#   time would pass the "during" half and fail the "after" half only if the
#   binding never happened; the `startRecording` poll is what makes the
#   second half mean "a recording actually began", not "a listener fired".
