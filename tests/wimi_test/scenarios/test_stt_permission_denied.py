"""§7's second failure path: the OS has denied microphone access (#59).

``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` §7,
``PERMISSION_DENIED``:

    **Detect.** ``QCoreApplication.checkPermission(QMicrophonePermission())``
    returns Denied […]

    **macOS.** TCC remembers the denial system-wide, and the OS will **not**
    prompt again. A "try again" button is a lie. The message must name the
    exact path: *System Settings → Privacy & Security → Microphone → WIMI*.

Two assertions carry that. The message must send the student to their system
settings — §7's *"Every message names the remediation"* — and **no retry
button may be offered**, which is not a style preference: on the platform
this path is meaningful on, a second press cannot produce a second prompt.
The test reads ``errors.py``'s ``RETRYABLE`` set for that rather than
restating it, so the page and the taxonomy cannot disagree silently.

The second test is the remediation actually working. Once access is granted
outside WIMI there is no bridge event to learn it from, and the student is
by definition in another application when they do it — so coming back to the
window is the moment that matters, and ``dictation.js`` re-reads the three
states on ``window``'s ``focus``. That is the recovery path this message is
promising, so it is the one worth proving.

``check_permission()`` is not called here: T15's task entry says *"Do not try
to deny a real microphone"*, and on Windows Qt's permission backend does not
exist at all (§7, T2 finding 4) — it returns Granted unconditionally, so
this path cannot be reached from hardware on the platform WIMI ships to
first. ``_helpers/stt_failure.py`` records why the injected payload can be
believed.
"""
from __future__ import annotations

import pytest

from _helpers.stt_failure import (
    FIELDS,
    assert_error_envelope_matches_bridge,
    assert_remediation,
    assert_writing_fields_usable,
    error_payload,
    force_status,
    healthy_mic,
    open_entry_form,
    refresh_controls,
    wait_for_state,
)
from app.stt.errors import SttErrorKind
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

# `_stt_microphone_state` reports a denial with the device still listed —
# there is a microphone, WIMI is simply not allowed to open it. Getting this
# wrong would collapse the path into "no microphone found", which has an
# entirely different fix.
DENIED_MIC = {
    "permission": "denied",
    "devices": [{"id": "t15-default", "label": "Test input",
                 "is_default": True}],
    "ready": False,
    "error": error_payload(SttErrorKind.PERMISSION_DENIED,
                           "microphone permission denied"),
}


def test_a_denial_names_the_system_settings_and_offers_no_retry(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange ----------------------------------------------------------
    open_entry_form(wimi_session, wimi_page, name="T15 denied")
    assert_error_envelope_matches_bridge(wimi_page)
    assert DENIED_MIC["error"]["retryable"] is False, (
        "errors.py now calls PERMISSION_DENIED retryable. §7 says a retry "
        "button is a lie here because macOS will not prompt twice — reopen "
        "that, do not edit this test.")

    # ---- Act --------------------------------------------------------------
    force_status(wimi_page, mic=DENIED_MIC)
    refresh_controls(wimi_page)

    # ---- Assert -----------------------------------------------------------
    for field in FIELDS:
        shown = wait_for_state(wimi_page, field, "mic_problem")

        assert "microphone access" in (shown["status_text"] or "").lower(), (
            f"the {field} control does not say WIMI lacks access — a denial "
            f"reported as anything else sends the student looking for a "
            f"cable: {shown['status_text']!r}")
        # Both platform branches of the copy say this; only macOS spells out
        # the full path, which is asserted in the Python sweep rather than
        # here, where the user agent is whatever the box happens to run.
        assert_remediation(shown, "system settings")

        assert shown["action_hidden"] is True and not shown["action_label"], (
            f"a retry button is offered for a denial. On macOS the OS will "
            f"not ask again, so pressing it cannot change anything: {shown!r}")
        assert shown["button_disabled"] is True, (
            f"the {field} microphone button is pressable while WIMI has no "
            f"access to the microphone: {shown!r}")

    assert_writing_fields_usable(wimi_page, "with permission denied")


def test_granting_access_and_returning_to_the_window_restores_the_button(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The remediation, carried out.

    Nothing tells WIMI that a permission changed — there is no signal, and
    the student was in System Settings, not in WIMI, when they changed it.
    Coming back to the window is the event, and a control that did not
    re-read there would leave a student who did exactly what the message
    asked staring at the same refusal.
    """
    open_entry_form(wimi_session, wimi_page, name="T15 denied then granted")
    force_status(wimi_page, mic=DENIED_MIC)
    refresh_controls(wimi_page)
    wait_for_state(wimi_page, "reflection", "mic_problem")

    # Granted outside WIMI; the page is told nothing.
    granted = force_status(wimi_page, mic=healthy_mic())
    assert granted["mic"]["error"] is None
    wimi_page.eval_js("(() => { window.dispatchEvent(new Event('focus'));"
                      " return true; })()")

    shown = wait_for_state(wimi_page, "reflection", "ready")
    assert shown["button_disabled"] is False, (
        f"access was granted and WIMI was brought back to the front, and the "
        f"button is still refusing: {shown!r}")
    assert shown["button_label"] == "Speak", shown
    assert_writing_fields_usable(wimi_page, "after access was granted")
