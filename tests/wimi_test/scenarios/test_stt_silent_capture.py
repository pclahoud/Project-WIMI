"""§7's fourth failure path: the microphone delivers silence (#59).

``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` §7,
``NO_AUDIO_CAPTURED`` — *"the one that does not announce itself"*:

    With Windows' *Let desktop apps access your microphone* set off, the
    capture stack does not deny anything: it delivers a stream of zeros.
    Every API reports success […] The student speaks for ninety seconds and
    gets an empty transcript with no error anywhere.

    **Detect, two ways, both needed:** 1. A live level meter while recording
    […] 2. A peak-amplitude check on stop.

Both are asserted here, in the order the student meets them, because either
one alone leaves a real hole. The meter is the *honest* half — it says so
while they are still speaking rather than ninety seconds later — and the
stop check is the half that refuses to transcribe. Without the second,
measured by T6 on 2026-09-23, three seconds of digital silence does not
transcribe to nothing: **it transcribes to the word " you"**, which would
land an invented word in the required reflection field, indistinguishable
from something the student said.

The levels are injected rather than produced by a muted device. T15's task
entry rules out denying real hardware, and this particular state is
unreachable on the machine anyway: the toggle it models is a Windows privacy
setting, and every API involved reports success while it is on, which is the
entire difficulty. ``_helpers/stt_failure.py`` records why the injected
payloads can be believed.
"""
from __future__ import annotations

import pytest

from _helpers.stt_failure import (
    assert_error_envelope_matches_bridge,
    assert_remediation,
    assert_writing_fields_usable,
    error_payload,
    force_status,
    open_entry_form,
    refresh_controls,
    set_response,
    wait_for_state,
    wait_for_status_containing,
)
from app.stt.errors import SttErrorKind
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

SILENT = error_payload(
    SttErrorKind.NO_AUDIO_CAPTURED,
    "peak 0.00000 never rose above 0.002 in 4.1 s of audio")

STARTED = {
    "recording": True,
    "error": None,
    "device": {"id": "t15-default", "label": "Test input", "is_default": True},
    "device_choice_honoured": True,
    "format": {"sample_rate": 16000, "channels": 1, "degraded": False},
}

# What a muted microphone sends: bytes arriving, every one of them zero.
FLAT = {"recording": True, "rms": 0.0, "peak": 0.0, "stream_error": None}


def _record_into_silence(session: WimiTestSession, page: WimiPage,
                         name: str) -> None:
    open_entry_form(session, page, name=name)
    force_status(page)
    refresh_controls(page)
    wait_for_state(page, "reflection", "ready")
    set_response(page, "startRecording", STARTED)
    set_response(page, "getRecordingLevel", FLAT)
    page.locator(testid="dictation-reflection-button").click()
    wait_for_state(page, "reflection", "recording")


def test_a_flat_meter_warns_while_the_student_is_still_speaking(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """§7's first detector, and the only one that arrives in time to help."""
    # ---- Arrange / Act ----------------------------------------------------
    _record_into_silence(wimi_session, wimi_page, "T15 flat meter")

    # ---- Assert -----------------------------------------------------------
    # Three seconds of flat level, then the line changes under a recording
    # that is still running — nothing has been stopped or discarded.
    shown = wait_for_status_containing(
        wimi_page, "reflection", "not hearing anything", timeout_ms=30000)
    assert_remediation(shown, "muted", "wrong one is selected")

    assert shown["state"] == "recording", (
        f"the warning arrived by ending the recording; it is supposed to be "
        f"a warning *during* one, so the student can fix the microphone and "
        f"keep going: {shown!r}")
    assert shown["button_label"] == "Stop" and shown["button_disabled"] is False, (
        f"the student cannot stop the recording they are being warned about: "
        f"{shown!r}")
    assert "dictation-status--warn" in (shown["status_class"] or ""), (
        f"a flat meter is rendered in the same tone as 'Listening…': "
        f"{shown['status_class']!r}")
    assert_writing_fields_usable(wimi_page, "while the meter is flat")


def test_silence_is_refused_rather_than_transcribed(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """§7's second detector: the peak check, which refuses to transcribe.

    The value of this one is what does **not** happen — no job is queued, so
    nothing can come back and write a word into a required field that the
    student never said.
    """
    # ---- Arrange ----------------------------------------------------------
    _record_into_silence(wimi_session, wimi_page, "T15 silence refused")
    assert_error_envelope_matches_bridge(wimi_page)
    assert SILENT["retryable"] is True, (
        "errors.py no longer calls NO_AUDIO_CAPTURED retryable, but unmuting "
        "a microphone and speaking again is exactly what fixes this.")

    # ---- Act --------------------------------------------------------------
    # `stopRecording` refuses with a kind and hands back no job at all;
    # `transcribeRecording` is the shipped composite and returns it unchanged.
    set_response(wimi_page, "stopRecording",
                 {"job_id": None, "error": SILENT,
                  "context": {"entry_id": None, "field_key": "reflection",
                              "token": 1, "subject_ids": []}})
    wimi_page.locator(testid="dictation-reflection-button").click()

    # ---- Assert -----------------------------------------------------------
    shown = wait_for_state(wimi_page, "reflection", "error")
    assert "WIMI heard nothing" in (shown["status_text"] or ""), (
        f"silence was reported as something other than silence, which is the "
        f"one thing this path exists to name: {shown['status_text']!r}")
    assert_remediation(shown, "nothing to transcribe", "not muted")

    assert shown["action_label"] == "Try again" and shown["action_hidden"] is False, (
        f"no retry offered after a silent recording: {shown!r}")
    assert shown["button_disabled"] is False and shown["button_label"] == "Speak", (
        f"the control did not return to a state the student can record from: "
        f"{shown!r}")
    assert shown["meter_hidden"] is True, (
        f"the level meter is still showing after recording stopped: {shown!r}")
    assert_writing_fields_usable(wimi_page, "after a silent recording")
