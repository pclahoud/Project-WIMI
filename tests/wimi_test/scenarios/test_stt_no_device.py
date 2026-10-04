"""§7's first failure path: there is no microphone at all (#59).

``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` §7, ``NO_INPUT_DEVICE``:

    **Detect.** ``QMediaDevices.audioInputs()`` is empty. Checkable *before*
    the student presses anything.

    **Behave.** The mic button renders disabled from the start, with "No
    microphone found" beside it. Neither writing field is disabled — the
    student types into both as normal.

This is the only one of the four that is knowable before any interaction, so
it is asserted where the student meets it: on a freshly opened entry form,
with no press involved. The remediation matters as much as the message —
§7's *"Every message names the remediation. 'Microphone unavailable' is not
a message; it is a shrug."*

The absent **Try again** button is the other half. ``NO_INPUT_DEVICE`` is not
in ``errors.py``'s ``RETRYABLE`` set, because pressing a button cannot
conjure a microphone; §7's sibling ruling for the permission path puts it
plainly — *"A 'try again' button is a lie."* The assertion below reads that
set rather than restating it, so the taxonomy and the page cannot drift
apart without this failing.

Why the device list is injected rather than emptied: T15's task entry says
*"Do not try to deny a real microphone"*, and CI has no audio device at all,
so a hardware-driven version of this test would be unrunnable in one place
and unreproducible in the other. See ``_helpers/stt_failure.py`` for the
three things that tie the injected payload back to the shipped code.
"""
from __future__ import annotations

import pytest

from _helpers.stt_failure import (
    FIELDS,
    assert_error_envelope_matches_bridge,
    assert_remediation,
    assert_writing_fields_usable,
    control,
    error_payload,
    force_status,
    open_entry_form,
    refresh_controls,
    wait_for_state,
)
from app.stt.errors import SttErrorKind
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]


def test_no_microphone_disables_the_button_and_says_why(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange ----------------------------------------------------------
    open_entry_form(wimi_session, wimi_page, name="T15 no device")
    assert_error_envelope_matches_bridge(wimi_page)

    no_device = error_payload(SttErrorKind.NO_INPUT_DEVICE,
                              "no audio input devices")
    assert no_device["retryable"] is False, (
        "errors.py now calls NO_INPUT_DEVICE retryable. The assertion below "
        "that no retry button is offered follows from RETRYABLE, so decide "
        "which one is right rather than editing this test.")

    # ---- Act --------------------------------------------------------------
    # Exactly the mic section `_stt_microphone_state` builds when
    # `list_input_devices()` comes back empty: no devices, not ready, and the
    # kind the check order reaches first.
    force_status(wimi_page, mic={"permission": "undetermined", "devices": [],
                                 "ready": False, "error": no_device})
    refresh_controls(wimi_page)

    # ---- Assert -----------------------------------------------------------
    for field in FIELDS:
        shown = wait_for_state(wimi_page, field, "mic_problem")

        assert "No microphone found" in (shown["status_text"] or ""), (
            f"the {field} control does not say a microphone is missing. It "
            f"reads: {shown['status_text']!r}")
        assert_remediation(shown, "plug one in", "type into this field")

        assert shown["button_disabled"] is True, (
            f"the {field} microphone button is pressable with no microphone "
            f"on the machine; §7 asks for it to render disabled from the "
            f"start: {shown!r}")
        assert shown["action_hidden"] is True and not shown["action_label"], (
            f"a remediation button is offered for a failure the taxonomy "
            f"says is not retryable — it cannot work, and a button that "
            f"cannot work is worse than no button: {shown!r}")
        assert shown["meter_hidden"] is True, (
            f"the level meter is showing while nothing can be recorded: "
            f"{shown!r}")

    # §7's first rule for all four paths, and the one with teeth: both of
    # these are *required* fields and a broken microphone must leave the
    # student typing exactly as they did before this feature existed.
    assert_writing_fields_usable(wimi_page, "with no microphone")


def test_the_message_survives_the_control_re_reading_its_status(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Parked on this state, the control re-asks. It must not flicker to
    'ready' while doing so.

    ``restIdle`` arms a five-second re-check whenever it parks on
    ``no_input_device`` (and ``onWindowFocus`` forces another), so this
    resting state is re-entered repeatedly for as long as the form is open.
    Each of those passes is a chance to land somewhere else — and the
    student would be looking at an enabled button with no microphone behind
    it. Two forced refreshes with the same answer must produce the same
    screen.

    **That re-check is live code, not a leftover.** Measured in one process
    on 2026-09-23: *adding* an input device fires ``audioInputsChanged`` and
    refreshes the list, so asking again is how a headset plugged in after
    launch enables this button. It is *removal* that is never noticed
    (#168), which is the opposite direction and not what this state is
    waiting for. So the loop below is guarding a path a student really
    takes, and the button must not flicker while it runs.
    """
    open_entry_form(wimi_session, wimi_page, name="T15 no device twice")
    force_status(wimi_page, mic={
        "permission": "undetermined", "devices": [], "ready": False,
        "error": error_payload(SttErrorKind.NO_INPUT_DEVICE,
                               "no audio input devices")})

    refresh_controls(wimi_page)
    first = wait_for_state(wimi_page, "reflection", "mic_problem")
    refresh_controls(wimi_page)
    again = wait_for_state(wimi_page, "reflection", "mic_problem")

    assert again == first, (
        f"the control rendered differently the second time it read the same "
        f"status: {first!r} then {again!r}")
    assert_writing_fields_usable(wimi_page, "after a second status read")
