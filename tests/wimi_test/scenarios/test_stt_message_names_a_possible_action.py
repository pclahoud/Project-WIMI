"""Issue #174 - the permission-denied message told the student to press a
button that is disabled.

    "With ``getSttStatus()`` reporting ``mic.error.kind === 'permission_denied'``
    the control renders [...] *then press the button again* -- and at the same
    moment the microphone button is **disabled** [...] and **no action button
    is offered** [...] Both of those are correct on their own. The message is
    what is wrong: it names a gesture the student cannot perform."

``FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` §7's third rule is the one broken:
*"Every message names the remediation. 'Microphone unavailable' is not a
message; it is a shrug."* A remediation the student cannot carry out is the
same shrug with more words.

Why this is a sweep and not one assertion
-----------------------------------------
#174 is one instance of a rule that applies to every state this control can
rest in, so it is asserted as the rule: **a message may not direct a press
when there is nothing pressable.** Written that way it also has its own
positive controls built in -- ``device_in_use`` and ``no_audio_captured`` ARE
in ``errors.py``'s ``RETRYABLE``, so they render a "Try again" button and their
copy may say exactly that. A test that simply banned the word would turn those
two red, which is how it stays honest rather than becoming "never mention a
button".

``NAMED_A_GESTURE`` is checked against #174's original sentence, so a detector
that quietly stops matching cannot report a clean page.

What is NOT changed, and should not be
--------------------------------------
``PERMISSION_DENIED``'s absence from ``RETRYABLE`` and the disabled button are
both deliberate (§7: on macOS the OS will not prompt twice, so "try again" is
a lie). The fix is the sentence. Leaving the button enabled off-macOS was the
alternative and costs a per-platform disabled state -- see #174 before
reaching for it.
"""
from __future__ import annotations

import pytest

from _helpers.stt_failure import (
    FIELDS,
    error_payload,
    force_status,
    open_entry_form,
    refresh_controls,
    wait_for_state,
)
from app.stt.errors import RETRYABLE, SttError, SttErrorKind
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

#: Every mic failure `restIdle` has a resting state for.
MIC_KINDS = [
    SttErrorKind.NO_INPUT_DEVICE,
    SttErrorKind.PERMISSION_DENIED,
    SttErrorKind.DEVICE_IN_USE,
    SttErrorKind.NO_AUDIO_CAPTURED,
]

#: Phrases that direct the student at a control. Imperatives only: the fixed
#: copy says "there is nothing to press here", which is the opposite of a
#: direction, so a bare ban on "press" would flag the fix itself.
GESTURES = (
    "press the button",
    "press it",
    "press again",
    "press the microphone",
    "click the button",
    "tap the button",
    "try again",
)

#: #174's sentence, verbatim. The negative control below needs it.
ORIGINAL_174 = (
    "WIMI does not have microphone access. Grant WIMI access to the "
    "microphone in your system settings, then press the button again."
)


def _named_gestures(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [g for g in GESTURES if g in lowered]


def _mic_payload(kind: SttErrorKind) -> dict:
    """A denial-shaped status for `kind`, with the device still listed.

    The device stays in the list for every kind but NO_INPUT_DEVICE: a denial
    with no device collapses into "no microphone found", which has an entirely
    different fix.
    """
    return {
        "permission": "denied" if kind is SttErrorKind.PERMISSION_DENIED
                      else "granted",
        "devices": ([] if kind is SttErrorKind.NO_INPUT_DEVICE
                    else [{"id": "w174", "label": "Test input",
                           "is_default": True}]),
        "ready": False,
        "error": error_payload(kind, "w174"),
    }


def test_the_detector_fires_on_the_original_sentence() -> None:
    """Without this the sweep below is unfalsifiable."""
    assert _named_gestures(ORIGINAL_174) == ["press the button"], (
        f"the gesture detector no longer matches #174's own message, so the "
        f"sweep would pass on a tree that still carries it: "
        f"{_named_gestures(ORIGINAL_174)!r}")


@pytest.mark.parametrize("kind", MIC_KINDS, ids=lambda k: k.value)
def test_no_mic_message_directs_a_press_when_nothing_is_pressable(
    wimi_session: WimiTestSession, wimi_page: WimiPage, kind: SttErrorKind,
) -> None:
    # ---- Arrange ----------------------------------------------------------
    open_entry_form(wimi_session, wimi_page, name=f"W174 {kind.value}")

    # ---- Act --------------------------------------------------------------
    force_status(wimi_page, mic=_mic_payload(kind))
    refresh_controls(wimi_page)

    # ---- Assert -----------------------------------------------------------
    retryable = kind in RETRYABLE
    assert SttError(kind).retryable is retryable, "taxonomy disagrees with itself"

    for field in FIELDS:
        shown = wait_for_state(wimi_page, field, "mic_problem")
        pressable = (shown["button_disabled"] is False
                     or shown["action_hidden"] is False)

        if pressable:
            # The positive control: a retryable kind really does offer a
            # button, so the sweep is not passing by banning a word outright.
            assert retryable, (
                f"{kind.value} is not in RETRYABLE yet offers a pressable "
                f"control: {shown!r}")
            continue

        named = _named_gestures(shown["status_text"])
        assert not named, (
            f"the {field} control is in {kind.value} with its microphone "
            f"button disabled and no action button, and its message says "
            f"{named} -- a gesture the student cannot perform. §7: every "
            f"message names the remediation, and one that cannot be carried "
            f"out is a shrug with more words (#174). The line reads: "
            f"{shown['status_text']!r}")


def test_a_denial_names_the_recovery_that_does_work(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Not only "no impossible gesture" -- a remediation is still required.

    The recovery needs no press: ``onWindowFocus`` calls ``refreshStatus(true)``
    while the state is ``mic_problem``, so returning to WIMI re-reads the three
    states and enables the button by itself. ``test_stt_permission_denied.py``
    is what proves that path actually works; this asserts the copy names it.

    Platform-branched because the two branches are deliberately different and
    both are right: macOS says the OS will not ask again (§7's ruling), every
    other platform points at the window. Several wordings are accepted so a
    reasonable rewrite does not go red over a synonym.
    """
    open_entry_form(wimi_session, wimi_page, name="W174 denied copy")
    force_status(wimi_page,
                 mic=_mic_payload(SttErrorKind.PERMISSION_DENIED))
    refresh_controls(wimi_page)

    is_mac = wimi_page.eval_js(
        "/Mac OS X|Macintosh/i.test(navigator.userAgent)") is True

    for field in FIELDS:
        shown = wait_for_state(wimi_page, field, "mic_problem")
        text = (shown["status_text"] or "").lower()

        assert "system settings" in text, (
            f"the {field} denial message does not say where to grant access: "
            f"{shown['status_text']!r}")

        if is_mac:
            expected = ("will not ask again", "not ask again")
        else:
            expected = ("switch back to wimi", "come back to wimi",
                        "return to wimi", "back to the front")
        assert any(phrase in text for phrase in expected), (
            f"the {field} denial message names no remediation the student can "
            f"actually carry out (looked for one of {expected}, is_mac="
            f"{is_mac}). The whole line reads: {shown['status_text']!r}")
