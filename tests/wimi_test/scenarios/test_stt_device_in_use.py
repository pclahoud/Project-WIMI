"""§7's third failure path: another application holds the microphone (#59).

``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` §7, ``DEVICE_IN_USE``:

    **Detect.** ``QAudioSource`` reports ``QAudio.Error.OpenError`` on start
    — most often another application holds the device in exclusive mode (a
    video call is the common case).

    **Behave.** "Your microphone is in use by another app." Offer retry,
    because unlike the permission case, retry genuinely works once the call
    ends.

This is the first of the four that only exists *after* a press: step 4 of
the check order constructs the ``QAudioSource``, and everything before it
said the microphone was fine. So this scenario starts from a control that is
ready and willing, and dispatches a real hit-tested click — the harness
locator uses ``Input.dispatchMouseEvent``, not ``el.click()``, so a button
the student could not actually reach fails here rather than passing.

Two things §7 asks for that are easy to get half right:

- **The retry must be offered *and* work.** An error state that leaves the
  button disabled with a "Try again" beside it is the same dead end as the
  permission path, which §7 distinguishes this one from explicitly. The
  second half of the test presses it and expects a recording.
- **The other field must not be stranded.** ``dictation.js`` takes a
  module-level lock before opening the microphone, and the other writing
  field's button greys out while it is held. A refused start that forgot to
  release it would leave the explanation field's microphone dead for the
  rest of the session, with the reason pointing at a recording that never
  started.
"""
from __future__ import annotations

import pytest

from _helpers.stt_failure import (
    assert_error_envelope_matches_bridge,
    assert_remediation,
    assert_writing_fields_usable,
    control,
    error_payload,
    force_status,
    open_entry_form,
    refresh_controls,
    set_response,
    wait_for_state,
)
from app.stt.errors import SttErrorKind
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

IN_USE = error_payload(SttErrorKind.DEVICE_IN_USE,
                       "QAudio.Error.OpenError on start")

# `startRecording`'s own success shape, for the retry half.
STARTED = {
    "recording": True,
    "error": None,
    "device": {"id": "t15-default", "label": "Test input", "is_default": True},
    "device_choice_honoured": True,
    "format": {"sample_rate": 16000, "channels": 1, "degraded": False},
}


def _arrange_ready(session: WimiTestSession, page: WimiPage, name: str) -> None:
    open_entry_form(session, page, name=name)
    force_status(page)
    refresh_controls(page)
    ready = wait_for_state(page, "reflection", "ready")
    assert ready["button_disabled"] is False, (
        f"the control never became usable, so the refusal below would not be "
        f"the thing under test: {ready!r}")


def test_a_busy_microphone_says_so_and_frees_the_other_field(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange ----------------------------------------------------------
    _arrange_ready(wimi_session, wimi_page, "T15 in use")
    assert_error_envelope_matches_bridge(wimi_page)
    assert IN_USE["retryable"] is True, (
        "errors.py no longer calls DEVICE_IN_USE retryable, which is the one "
        "thing §7 says separates it from the permission path.")

    # ---- Act --------------------------------------------------------------
    set_response(wimi_page, "startRecording",
                 {"recording": False, "error": IN_USE})
    wimi_page.locator(testid="dictation-reflection-button").click()

    # ---- Assert -----------------------------------------------------------
    shown = wait_for_state(wimi_page, "reflection", "error")
    assert "in use by another app" in (shown["status_text"] or ""), (
        f"the student is not told another application has the microphone. "
        f"The line reads: {shown['status_text']!r}")
    assert_remediation(shown, "close it", "try again")

    assert shown["action_hidden"] is False and shown["action_label"] == "Try again", (
        f"no retry is offered for a failure the taxonomy calls retryable — "
        f"and here a retry genuinely works, once the call ends: {shown!r}")
    assert shown["button_disabled"] is False, (
        f"the microphone button is left disabled after a refused start, so "
        f"the 'try again' the message asks for is impossible: {shown!r}")

    other = control(wimi_page, "explanation")
    assert other["state"] != "blocked", (
        f"the explanation field is still waiting on a recording that never "
        f"started — the lock was taken and not released: {other!r}")
    assert other["button_disabled"] is False, other

    assert_writing_fields_usable(wimi_page, "with the microphone busy")


def test_pressing_try_again_after_the_call_ends_records(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """§7: *"retry genuinely works once the call ends."* So prove it does."""
    _arrange_ready(wimi_session, wimi_page, "T15 in use then free")
    set_response(wimi_page, "startRecording",
                 {"recording": False, "error": IN_USE})
    wimi_page.locator(testid="dictation-reflection-button").click()
    wait_for_state(wimi_page, "reflection", "error")

    # The video call ends. Nothing tells WIMI; the next attempt simply works.
    set_response(wimi_page, "startRecording", STARTED)
    set_response(wimi_page, "getRecordingLevel",
                 {"recording": True, "rms": 0.2, "peak": 0.4,
                  "stream_error": None})
    wimi_page.locator(testid="dictation-reflection-action").click()

    shown = wait_for_state(wimi_page, "reflection", "recording")
    assert shown["button_label"] == "Stop", shown
    assert shown["button_disabled"] is False, shown
    assert shown["meter_hidden"] is False, (
        f"recording with no level meter — §7 calls the meter the only signal "
        f"that tells a student their microphone is muted while they are "
        f"still speaking: {shown!r}")
    assert_writing_fields_usable(wimi_page, "while recording")
