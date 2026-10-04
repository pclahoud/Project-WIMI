"""A transcript that arrives too late is dropped, and said so (#59, §3.5).

Transcription runs for seconds on a worker. In that window the form can
be rewritten underneath it — by ``navigateToEntry()``, by
``populateFormWithEntry()``, or by ``applyAutofillData()``, which writes
straight into ``#explanation-editor``. Both dictation targets are
*required* fields, so a late transcript does not merely mislabel
something optional: it lands in a field that gates the save button, on an
entry the student was not speaking about.

``stalenessReason()`` in ``dictation.js`` names four ways a result can be
stale. Two are exercised here, along both axes T16 asks for:

* **the entry axis** — the student moves to the next entry while the
  worker is still running;
* **the field axis** — a result carrying one field key must never be
  delivered to the other field's editor. This is the one that cannot be
  produced by any amount of clicking: the only way to reach it is to hand
  the page a payload echoing the wrong key, which is exactly what a
  backend that mixed up two queued jobs would do.

Discarding quietly would be its own bug, so each test asserts both
halves: the text is nowhere, *and* the student is told. ``dictation.js``
says it in the control's own status line and raises a toast; the status
line is the one a scenario can read without depending on Toast's
lifetime.

``null -> a number`` is deliberately **not** staleness (``dictation.js``,
``stalenessReason``'s third bullet) — that is the first autosave giving a
new entry its id, and treating it as a swap would cost the student the
transcript they just recorded. ``test_stt_transcript_persists.py`` is the
test that would go red if someone "fixed" it into one.
"""
from __future__ import annotations

import pytest

from _helpers.stt_form import (
    control_state,
    editor_text,
    install_stt_stub,
    poll,
    press_mic,
    release_transcript,
    seed_entry_session,
    start_recording,
    status_text,
    stop_and_hold,
    wait_for_state,
)
from _helpers.w114_form_ready import wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

SENTINEL = "ZEBRAFISH LATE TRANSCRIPT"

pytestmark = [pytest.mark.slow, pytest.mark.regression]


def _open_form(wimi_page: WimiPage, session_id: int) -> None:
    wimi_page.goto("entry-form", query={"session_id": session_id})
    wait_for_form_ready(wimi_page)
    install_stt_stub(wimi_page)


def test_moving_to_the_next_entry_discards_the_transcript(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The entry axis: the form is swapped while the worker runs."""
    # ---- Arrange ----------------------------------------------------------
    session_id = seed_entry_session(wimi_session.user.db, name="STT stale",
                                    slots=2)
    _open_form(wimi_page, session_id)

    # ---- Act --------------------------------------------------------------
    start_recording(wimi_page, "reflection")
    stop_and_hold(wimi_page, "reflection")

    # The student moves on. Nothing is dirty, so no unsaved-changes modal:
    # navigateToEntry() goes straight to resetFormForNewEntry().
    wimi_page.locator(css="#btn-next-entry").click()
    assert poll(wimi_page, "(() => EntryState.currentEntryIndex === 1)()",
                timeout_ms=20000), "the form never moved to the second entry"

    release_transcript(wimi_page, SENTINEL)
    wait_for_state(wimi_page, "reflection", "ready")

    # ---- Assert -----------------------------------------------------------
    assert SENTINEL not in editor_text(wimi_page, "reflection"), (
        "a transcript recorded against entry 1 was written into entry 2's "
        "reflection — a required field on an entry the student never spoke "
        "about")
    assert SENTINEL not in editor_text(wimi_page, "explanation"), (
        "the transcript landed in the explanation editor instead")

    told = status_text(wimi_page, "reflection")
    assert "discard" in told.lower(), (
        f"the transcript was dropped without telling the student: {told!r}. "
        f"Silently losing seconds of speech is the failure class this whole "
        f"check exists to avoid")


def test_a_result_for_the_other_field_is_never_delivered(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The field axis: the explanation editor refuses reflection's transcript.

    Nothing a student does produces this; it is what a backend that
    confused two queued jobs would produce, and the field key travels
    with the job for exactly that reason. The check has to be on the
    *receiving* side, because a mis-addressed result has already left
    the worker by the time anyone could notice.
    """
    # ---- Arrange ----------------------------------------------------------
    session_id = seed_entry_session(wimi_session.user.db, name="STT field")
    _open_form(wimi_page, session_id)

    # ---- Act --------------------------------------------------------------
    start_recording(wimi_page, "explanation")
    stop_and_hold(wimi_page, "explanation")
    release_transcript(wimi_page, SENTINEL, field_key="reflection")
    wait_for_state(wimi_page, "explanation", "ready")

    # ---- Assert -----------------------------------------------------------
    assert SENTINEL not in editor_text(wimi_page, "explanation"), (
        "a result stamped field_key='reflection' was inserted into the "
        "explanation editor — the field key is carried through the job "
        "precisely so it cannot be")
    assert SENTINEL not in editor_text(wimi_page, "reflection"), (
        "the transcript was re-routed to the reflection editor. Nothing is "
        "waiting for it there, and a control that delivers to a field the "
        "student did not press is worse than one that drops it")

    told = status_text(wimi_page, "explanation")
    assert "discard" in told.lower(), (
        f"the mis-addressed result vanished with nothing said: {told!r}")
    assert "different field" in told.lower(), (
        f"the student was told the transcript was discarded but not why "
        f"({told!r}); stalenessReason() has a sentence per branch so the "
        f"message is not the same shrug four times over")


def test_a_superseded_recording_does_not_overwrite_the_newer_one(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The token axis, which is the same hazard inside one field.

    Recording twice is ordinary behaviour — the student mumbles, stops,
    and says it again. The first job's result is not wrong about which
    entry or which field it belongs to; only the token tells the page it
    has been superseded.
    """
    # ---- Arrange ----------------------------------------------------------
    session_id = seed_entry_session(wimi_session.user.db, name="STT token")
    _open_form(wimi_page, session_id)

    # ---- Act --------------------------------------------------------------
    start_recording(wimi_page, "reflection")
    stop_and_hold(wimi_page, "reflection")
    # An earlier recording's token can only be lower than the one this field
    # is waiting for; dictation.js increments it at every record-stop.
    release_transcript(wimi_page, SENTINEL, token=0)
    wait_for_state(wimi_page, "reflection", "ready")

    # ---- Assert -----------------------------------------------------------
    assert SENTINEL not in editor_text(wimi_page, "reflection"), (
        "a superseded recording's transcript was inserted, so the student "
        "gets the words they rejected on top of the ones they kept")
    told = status_text(wimi_page, "reflection")
    assert "newer recording" in told.lower(), (
        f"the supersession was not explained: {told!r}")
    assert control_state(wimi_page, "reflection") == "ready", (
        "the control did not come back to ready after discarding; a mic that "
        "stays stuck on 'Transcribing…' has taken the feature away")


# ---------------------------------------------------------------------------
# Why each assertion catches the regression
# ---------------------------------------------------------------------------
#
# * Neutering `stalenessReason()` to `return null` fails all three at the
#   "not in the editor" assertion, with the transcript sitting in the field
#   it should never have reached. Verified by doing exactly that.
# * The three differ in which branch they reach, and each pins its own
#   sentence, so collapsing the four reasons into one shrug would fail the
#   field-key and token tests without touching the entry one.
# * None of them can pass by the transcript simply never arriving:
#   `test_stt_transcript_persists.py` drives the same stub to a successful
#   insertion, so the delivery path is known to work.
# * The transcription is held open by the stub rather than raced, so the
#   window the form is rewritten in is the test's to choose. A real
#   transcription would close it in a few hundred milliseconds on a fast
#   box and never on a slow one.
