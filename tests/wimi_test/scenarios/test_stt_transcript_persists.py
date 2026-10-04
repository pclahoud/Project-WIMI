"""A dictated transcript reaches ``question_entries``, not just the screen.

This is the test for §3.5's dirty-flag hazard, and it is the reason it
asserts against the database rather than the DOM.

``initRichTextEditors()`` wires each editor with ``onChange: () =>
{ markDirty(); validateForm(); }``, but whether TinyMCE's change event
reaches that handler for a *scripted* ``insertContent()`` depends on
undo-level batching. If it does not:

* ``EntryState.isDirty`` stays false,
* the autosave tick's ``if (EntryState.isDirty && ...)`` guard skips the
  entry entirely,
* and the student navigates away having lost a **required** field with no
  toast, no console error and nothing on screen looking wrong.

So ``dictation.js`` calls ``onInserted()`` — ``markDirty()`` +
``validateForm()`` — itself, unconditionally, after every insertion.
Everything about that failure is invisible from the page: the editor
shows the words either way. Only the row knows.

Two things this test does on purpose
------------------------------------
**It saves through the autosave, not through the Save as Draft button.**
An explicit save does not consult ``isDirty``, so it would write the
transcript whether ``markDirty()`` was called or not — which is to say it
would pass against the bug. The tick's guard is the code under test, so
the interval is shortened (``EntryState.autoSaveInterval``) and
``startAutoSave()`` restarted. The guard itself is untouched.

**It reads back through ``wimi_session.user.db``**, the same database the
application process is writing to, rather than asking the page what it
thinks it saved.

The tick is quickened AFTER the dictating, not before (#117, #186)
-----------------------------------------------------------------

The first test used to shorten the interval to 1200 ms during Arrange
and then dictate two fields, which left a tick boundary sitting in the
middle of the Act. If it fell between the two dictations, the resulting
``createQuestionEntry`` carried the reflection and not the explanation —
and since the test waits for the *first* ``createQuestionEntry`` after a
cursor taken before the *first* dictation, it matched that save and read
the row before the next tick wrote the explanation. The row then held
``explanation = NULL`` and the test said so, which reads exactly like
the data loss it exists to detect.

Measured: 8 failures in 8 runs once each microphone press got ~150 ms
slower, 0 in 8 before, and 0 in 4 with the interval raised to 6000 ms
and nothing else changed. #186 is the same symptom on Windows, where it
was already suspected to be "the test's synchronisation" rather than the
product.

So the shipped 30 s interval stays in force while the dictating happens
— it cannot fire inside the few seconds two dictations take — and the
tick is quickened immediately before the save is awaited. That removes
the boundary rather than making it less likely to be hit: widening a
window is how this comes back on a slower machine.
"""
from __future__ import annotations

import pytest

from _helpers.stt_form import (
    editor_text,
    install_stt_stub,
    poll,
    release_transcript,
    seed_entry_session,
    start_recording,
    stop_and_hold,
    wait_for_state,
)
from _helpers.w114_form_ready import (
    centre_of,
    real_click,
    real_type,
    wait_for_form_ready,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

REFLECTION_SAID = "I confused preload with afterload again"
EXPLANATION_SAID = "Afterload is the pressure the ventricle works against"

pytestmark = [pytest.mark.slow, pytest.mark.regression]

# Short enough for a scenario, long enough that the tick is a tick. The
# guard inside it is the shipped one.
AUTOSAVE_MS = 1200

QUICKEN_AUTOSAVE = (
    "(() => { EntryState.autoSaveInterval = %d; startAutoSave();"
    " return EntryState.autoSaveTimer !== null; })()" % AUTOSAVE_MS
)


def _dictate(page: WimiPage, field: str, said: str) -> None:
    start_recording(page, field)
    stop_and_hold(page, field)
    release_transcript(page, said)
    wait_for_state(page, field, "ready")
    assert said in editor_text(page, field), (
        f"the transcript never reached the {field} editor at all, so the "
        f"persistence assertion below would be meaningless")
    # Reset for the next recording in this test.
    page.eval_js("(() => { window.__stt.release = false; return true; })()")


def _saved_entry(session, session_id: int):
    entries = session.user.db.get_session_entries(session_id)
    assert entries, (
        "no row in question_entries for this session. The transcript is on "
        "screen and the database is empty — which is exactly what a missing "
        "markDirty() looks like: the autosave tick's isDirty guard skipped "
        "the entry and said nothing")
    return entries[0]


def test_a_dictated_answer_survives_the_autosave(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Both fields, through the tick, read back from the row."""
    # ---- Arrange ----------------------------------------------------------
    session_id = seed_entry_session(wimi_session.user.db, name="STT persist")
    wimi_page.goto("entry-form", query={"session_id": session_id})
    wait_for_form_ready(wimi_page)
    install_stt_stub(wimi_page)

    # ---- Act --------------------------------------------------------------
    # The shipped 30 s interval is still in force here, so no tick can land
    # between the two dictations and split them across two saves. See this
    # module's docstring: that boundary is what #117's harness fix exposed
    # and what #186 looks like on Windows.
    _dictate(wimi_page, "reflection", REFLECTION_SAID)

    # The flag the tick reads. Asserted here as well as through the row,
    # because "the row is empty" and "the row is empty for this reason" are
    # different amounts of help to whoever sees this go red.
    assert wimi_page.eval_js("EntryState.isDirty === true") is True, (
        "inserting a transcript left EntryState.isDirty false. dictation.js "
        "calls onInserted() -> markDirty() precisely so this cannot depend "
        "on whether TinyMCE's change event fired for a scripted insert")

    _dictate(wimi_page, "explanation", EXPLANATION_SAID)

    # Both fields are in the editors and isDirty is set; NOW make the tick
    # quick. The cursor is taken first so the save it triggers cannot land
    # in the gap before the wait is armed.
    mark = wimi_page.mark_bridge_calls()
    assert wimi_page.eval_js(QUICKEN_AUTOSAVE) is True, (
        "startAutoSave() did not arm a timer")

    assert wimi_page.wait_for_bridge_call(
        "createQuestionEntry", since_ts=mark, timeout_ms=30000), (
        "the autosave tick never created the entry; with isDirty true and "
        "the interval shortened it should have fired within a second")

    # ---- Assert: the row, not the screen ----------------------------------
    entry = _saved_entry(wimi_session, session_id)
    assert REFLECTION_SAID in (entry.reflection or ""), (
        f"the dictated reflection is not in question_entries.reflection "
        f"(stored {entry.reflection!r}). Everything on screen looked right")
    assert EXPLANATION_SAID in (entry.explanation or ""), (
        f"the dictated explanation is not in question_entries.explanation "
        f"(stored {entry.explanation!r})")


def test_the_first_save_arriving_mid_transcription_does_not_discard_it(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """``null -> a number`` is not a swap (``dictation.js``, third bullet).

    A new entry has no id until something saves it, and on a form the
    student is typing into that first save lands *while* the worker is
    running. Reading the id change as "you moved to a different entry"
    would throw away the transcript on the single most common path there
    is — so this is the one comparison ``stalenessReason()`` deliberately
    does not make, and an absence is easy to "fix" back into presence.
    """
    # ---- Arrange ----------------------------------------------------------
    session_id = seed_entry_session(wimi_session.user.db, name="STT firstsave")
    wimi_page.goto("entry-form", query={"session_id": session_id})
    wait_for_form_ready(wimi_page)
    install_stt_stub(wimi_page)

    # Typing is what arms the autosave; the entry has no id yet.
    real_click(wimi_page, centre_of(wimi_page, "#user-answer"))
    real_type(wimi_page, "B")
    assert wimi_page.eval_js("EntryState.currentEntry === null") is True, (
        "the entry already had an id before the first save, so this test "
        "would not exercise the null -> id transition at all")
    assert wimi_page.eval_js(QUICKEN_AUTOSAVE) is True

    # ---- Act: the save lands while the transcription is still running -----
    start_recording(wimi_page, "reflection")
    stop_and_hold(wimi_page, "reflection")
    assert poll(wimi_page,
                "(() => !!(EntryState.currentEntry && EntryState.currentEntry.id))()",
                timeout_ms=30000), (
        "the autosave never gave the entry an id while the transcription was "
        "held open")
    mark = wimi_page.mark_bridge_calls()
    release_transcript(wimi_page, REFLECTION_SAID)
    wait_for_state(wimi_page, "reflection", "ready")

    # ---- Assert -----------------------------------------------------------
    assert REFLECTION_SAID in editor_text(wimi_page, "reflection"), (
        "the transcript was discarded because the entry acquired an id while "
        "it was being transcribed. That is the same entry being saved for the "
        "first time, not a different one")

    assert wimi_page.wait_for_bridge_call(
        "updateQuestionEntry", since_ts=mark, timeout_ms=30000), (
        "the autosave never wrote the transcript back to the existing row")
    entry = _saved_entry(wimi_session, session_id)
    assert REFLECTION_SAID in (entry.reflection or ""), (
        f"the transcript stayed on screen and never reached the row "
        f"(stored {entry.reflection!r})")


# ---------------------------------------------------------------------------
# Why each assertion catches the regression
# ---------------------------------------------------------------------------
#
# * Making `markDirty()` a no-op fails both tests: the first on the isDirty
#   assertion, the second because the autosave never gives the entry an id.
#   Verified by doing exactly that.
# * **Measured while checking it**: on this build TinyMCE's change event
#   *does* reach the editor's own `onChange` for a scripted
#   `insertContent()`, so deleting only dictation's explicit
#   `onInserted()` call leaves both tests green. §3.5 says the behaviour
#   "depends on undo-level batching" and prescribes calling it regardless;
#   that is the right call — undo batching is not a contract — but it does
#   mean no end-to-end test can distinguish the two paths here. The
#   guarantee these tests give is the outcome: the words are in the row.
#   Whether `onInserted()` is still called is a unit-level question (T17).
# * The save deliberately goes through the autosave tick, not the Save as
#   Draft button, because the button does not consult `isDirty` and would
#   write the transcript even with the bug present.
