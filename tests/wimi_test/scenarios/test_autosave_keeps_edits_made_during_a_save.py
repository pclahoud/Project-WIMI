"""An edit typed while a save is in flight is not reported as saved (#267).

`saveEntryAsDraft` snapshots the form with `collectFormData()` and then
`await`s at least one bridge round trip. Before this fix it called
`markClean()` unconditionally when that round trip landed, so an edit typed
inside the window was **not in the write, erased from `isDirty`, announced as
saved, and invisible to `beforeunload`** — four surfaces agreeing on a version
of the entry that no longer existed.

Why this is not driven as a race
--------------------------------
The defect reproduced in 3 of 14 runs of `test_a_dictated_answer_survives_the_autosave`
with the autosave interval shortened to 1200 ms — an automated figure under a
shortened interval, not a rate a student would see, since the shipped interval
is 30000 ms. Either way a test that merely typed fast would go green against
the bug most of the time, and a green test over a lost write is worse than the
red one it replaces. Two hooks make the window deterministic instead, and
**neither touches the code under test**:

* `updateQuestionEntry` is wrapped to hold the call for `SAVE_DELAY_MS` before
  performing it, which widens the await window to a duration the probe can act
  inside with room to spare. The arguments the page passed are recorded at call
  entry, so the test can *prove* the late edit was outside the snapshot rather
  than assuming it.
* `saveEntryAsDraft` is wrapped to count entries and completions. `isDirty` is
  only meaningful once the save has settled, and the settle point is three
  awaits past the bridge call (`syncEntryNotes`, `syncTagContextChoices`).

Why the recovery is left to the real tick
-----------------------------------------
This is the assertion that is easy to get wrong, and the peer review of #267
named it: *"a poll that passes after one tick hides exactly the 3-in-14 case —
it would convert a genuine lost write into a green test, which is worse than
the current red one."*

The second save must therefore be the shipped autosave tick, whose
`if (EntryState.isDirty && ...)` guard is the thing the fix feeds. A test that
called `saveEntryAsDraft()` itself for the recovery would collect the form
afresh and write the late text **whether or not `isDirty` survived** — passing
against the bug. So `AUTOSAVE_MS` is deliberately longer than `SAVE_DELAY_MS`:
tick 2 must fire *after* tick 1's save has settled, or an overlapping save
writes the late text for the wrong reason and the test proves nothing.

`test_a_save_with_no_concurrent_edit_still_marks_the_form_clean` is the
negative control, and it is not decoration: deleting `markClean()` outright
passes the first test.
"""
from __future__ import annotations

import pytest

from _helpers.w114_form_ready import (
    centre_of,
    poll,
    real_click,
    real_type,
    seed_session_with_draft,
    wait_for_form_ready,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

# How long `updateQuestionEntry` is held. Wide enough that a click plus an
# insertText (~220 ms together) fits with an order of magnitude to spare, so a
# loaded machine cannot turn "inside the window" into "just after it" — and the
# test asserts it was inside rather than trusting the arithmetic.
SAVE_DELAY_MS = 2000

# The autosave tick. Longer than SAVE_DELAY_MS plus a real save, so tick 2
# cannot overlap tick 1. See the module docstring: an overlapping tick would
# write the late text regardless of the dirty flag and hide the defect.
AUTOSAVE_MS = 5000

BASE_ANSWER = "BEFORE-THE-SAVE"
LATE_ANSWER = "-TYPED-DURING-THE-SAVE"

# `saveEntryAsDraft` is a top-level function declaration in a classic script,
# so it is a property of the global object and the tick's unqualified call
# resolves through it -- reassigning it is what lets the counter see the tick's
# own save, not just one the test started.
INSTALL_HOOKS = """
(() => {
  window.__s267 = {
    delayMs: %d, callStarted: 0, callDone: 0, sent: [],
    saveStarted: 0, saveDone: 0
  };
  const realCall = window.api.updateQuestionEntry.bind(window.api);
  window.api.updateQuestionEntry = function (entryId, entryData) {
    const s = window.__s267;
    s.callStarted += 1;
    // Recorded at call entry: this is the snapshot collectFormData() took,
    // before anything the probe types next could reach it.
    s.sent.push(entryData ? entryData.correct_answer : null);
    return new Promise((resolve, reject) => setTimeout(() => {
      Promise.resolve(realCall(entryId, entryData)).then(
        (v) => { s.callDone += 1; resolve(v); },
        (e) => { s.callDone += 1; reject(e); });
    }, s.delayMs));
  };
  const realSave = window.saveEntryAsDraft;
  window.saveEntryAsDraft = function () {
    window.__s267.saveStarted += 1;
    return Promise.resolve(realSave.apply(null, arguments)).then(
      (v) => { window.__s267.saveDone += 1; return v; },
      (e) => { window.__s267.saveDone += 1; throw e; });
  };
  return true;
})()
""" % SAVE_DELAY_MS

QUICKEN_AUTOSAVE = (
    "(() => { EntryState.autoSaveInterval = %d; startAutoSave();"
    " return EntryState.autoSaveTimer !== null; })()" % AUTOSAVE_MS
)

INDICATOR_TEXT = (
    "(() => { const el = document.querySelector("
    "'#auto-save-indicator .auto-save-text');"
    " return el ? el.textContent : null; })()"
)


def _install_hooks(page: WimiPage) -> None:
    assert page.eval_js(INSTALL_HOOKS) is True
    assert page.eval_js("typeof window.__s267 === 'object'") is True, (
        "the hooks did not install, so the save window is ~1 s and every "
        "assertion below would be racing rather than measuring")


def _type_answer(page: WimiPage, text: str, *, replace: bool) -> None:
    """Put real text in the Correct Answer field through real input events.

    `Input.insertText` replaces the selection, so `replace` selects the whole
    field and anything else appends at the end. The click is what gives the
    field focus; the insertion is what fires the `input` event the form's
    handler turns into `markDirty()`.
    """
    real_click(page, centre_of(page, "#correct-answer"))
    caret = "el.select()" if replace else (
        "el.setSelectionRange(el.value.length, el.value.length)")
    assert page.eval_js(
        "(() => { const el = document.getElementById('correct-answer');"
        " if (!el) return false; el.focus(); %s; return true; })()" % caret
    ) is True
    real_type(page, text)


def _saved_answer(session: WimiTestSession, session_id: int) -> str:
    entries = session.user.db.get_session_entries(session_id)
    assert entries, "the seeded draft vanished from question_entries"
    return entries[0].correct_answer or ""


def test_an_edit_made_during_a_save_is_not_discarded(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The whole of #267, in the order the student experiences it."""
    # ---- Arrange ----------------------------------------------------------
    session_id, _entry_id = seed_session_with_draft(
        wimi_session.user.db, name="Autosave 267")
    wimi_page.goto("entry-form", query={"session_id": session_id})
    wait_for_form_ready(wimi_page)
    _install_hooks(wimi_page)

    _type_answer(wimi_page, BASE_ANSWER, replace=True)
    assert wimi_page.eval_js("EntryState.isDirty === true") is True, (
        "typing in Correct Answer left the form clean, so the autosave tick "
        "would skip it and this test would measure nothing")
    generation_before = wimi_page.eval_js("EntryState.editGeneration")
    assert isinstance(generation_before, int), (
        "EntryState.editGeneration is missing -- #267's fix is not present, "
        "and without it markClean() cannot know a save was overtaken")
    assert wimi_page.eval_js(QUICKEN_AUTOSAVE) is True

    # ---- Act: get inside tick 1's await window ---------------------------
    assert poll(wimi_page, "window.__s267.callStarted >= 1",
                timeout_ms=AUTOSAVE_MS + 15000), (
        "the autosave tick never reached updateQuestionEntry; with isDirty "
        "true and the interval shortened it should have fired once")

    _type_answer(wimi_page, LATE_ANSWER, replace=False)

    # The assertion that makes this a measurement. If the save has already
    # landed, everything below is about the wrong moment -- so say so here
    # rather than reporting a confident, wrong verdict two assertions later.
    assert wimi_page.eval_js("window.__s267.callDone === 0") is True, (
        "the save completed before the late edit was typed, so the edit was "
        "never inside the await window. Raise SAVE_DELAY_MS rather than "
        "weakening anything below")
    assert wimi_page.eval_js("EntryState.editGeneration") > generation_before, (
        "the late edit did not bump editGeneration, so markClean() has no way "
        "to tell it happened -- check that the Correct Answer input handler "
        "still funnels through markDirty()")

    # ---- Assert: the save landed and did not claim the form was clean ----
    assert poll(wimi_page, "window.__s267.saveDone >= 1", timeout_ms=30000), (
        "the save that was in flight never settled")

    sent_first = wimi_page.eval_js("window.__s267.sent[0]")
    assert sent_first == BASE_ANSWER, (
        f"the first write carried {sent_first!r}. It is supposed to carry the "
        f"snapshot taken before the late edit -- if it already contains the "
        f"late text then collectFormData() is being re-read after the await "
        f"and this test is not exercising #267 at all")

    assert wimi_page.eval_js("EntryState.isDirty === true") is True, (
        "#267: the save reported the form clean although an edit arrived "
        "while it was in flight. That edit is in neither the write nor the "
        "dirty flag, the indicator says it was saved, and beforeunload will "
        "let the student close the page without a warning")
    indicator = wimi_page.eval_js(INDICATOR_TEXT)
    assert indicator == "Unsaved changes", (
        f"the auto-save indicator reads {indicator!r} while an edit is "
        f"unsaved. Saying 'Saved at ...' here is the half of #267 the student "
        f"actually sees")

    # ---- Assert: the shipped tick recovers it ----------------------------
    # Deliberately the real tick, whose isDirty guard is what the fix feeds.
    # Driving the save from the test would write the late text even with the
    # bug present.
    mark = wimi_page.mark_bridge_calls()
    assert wimi_page.wait_for_bridge_call(
        "updateQuestionEntry", since_ts=mark,
        timeout_ms=AUTOSAVE_MS + SAVE_DELAY_MS + 30000), (
        "no second write ever happened. The autosave tick skipped the entry, "
        "which means isDirty was cleared by the save that overtook it")
    assert poll(wimi_page, "window.__s267.saveDone >= 2", timeout_ms=30000)

    expected = BASE_ANSWER + LATE_ANSWER
    stored = _saved_answer(wimi_session, session_id)
    assert stored == expected, (
        f"question_entries.correct_answer holds {stored!r}, not {expected!r}. "
        f"The text the student typed while the save was in flight never "
        f"reached the database")


def test_a_save_with_no_concurrent_edit_still_marks_the_form_clean(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The negative control, and the reason it exists.

    Deleting `markClean()` altogether, or leaving the form permanently dirty,
    passes the test above. It would also mean every save reported unsaved
    changes for ever, `beforeunload` blocked every navigation, and the
    indicator never showed a time -- a worse bug than #267, reached by
    "fixing" it. So the ordinary case is asserted with the same hooks and the
    same settle signal, differing only in that nothing is typed inside the
    window.
    """
    session_id, _entry_id = seed_session_with_draft(
        wimi_session.user.db, name="Autosave 267 control")
    wimi_page.goto("entry-form", query={"session_id": session_id})
    wait_for_form_ready(wimi_page)
    _install_hooks(wimi_page)

    _type_answer(wimi_page, BASE_ANSWER, replace=True)
    assert wimi_page.eval_js(QUICKEN_AUTOSAVE) is True

    assert poll(wimi_page, "window.__s267.callStarted >= 1",
                timeout_ms=AUTOSAVE_MS + 15000)
    # The window is open and deliberately left alone.
    assert poll(wimi_page, "window.__s267.saveDone >= 1", timeout_ms=30000)

    assert wimi_page.eval_js("EntryState.isDirty === false") is True, (
        "a save that nothing overtook left the form dirty. Every later save "
        "would then be unconditional and beforeunload would warn on every "
        "navigation")
    indicator = wimi_page.eval_js(INDICATOR_TEXT)
    assert indicator and indicator.startswith("Saved at"), (
        f"the indicator reads {indicator!r} after a clean save; the student "
        f"has no confirmation their work is stored")
    assert wimi_page.eval_js("EntryState.lastSaveTime !== null") is True

    assert _saved_answer(wimi_session, session_id) == BASE_ANSWER


# ---------------------------------------------------------------------------
# How this fails without the fix -- measured, not predicted
# ---------------------------------------------------------------------------
#
# Run three ways on Linux (offscreen + --disable-gpu) while writing this:
#
# 1. **Fix present**: 2 passed in 24 s.
# 2. **Guard removed, counter kept** -- `markClean()` called unconditionally,
#    `editGeneration` still incrementing, so the *only* difference is #267's
#    one condition. `test_an_edit_made_during_a_save_is_not_discarded` fails at
#    `EntryState.isDirty === true`; the control still passes. That pairing is
#    the point: the first test is not passing because the form is permanently
#    dirty.
# 3. **Guard removed, and this file's `isDirty` and indicator assertions
#    neutralised** so the run could reach the end. It fails with
#    `BridgeCallTimeout: Bridge call 'updateQuestionEntry' was never recorded
#    within 37000 ms. No bridge calls at all were recorded in that window.`
#
# Run 3 is the one worth keeping. The second write does not merely arrive late
# or carry the wrong text -- **it never happens**, because the autosave tick's
# `isDirty` guard skipped the entry. The edit is gone, and nothing anywhere
# says so. That is #267 rather than an inference about it, and it is why the
# recovery is left to the shipped tick.
#
# Leaving `isDirty` set unconditionally instead passes the first test and fails
# all three of the control's assertions.


# Answering the modal deterministically. Its buttons are not what is under
# test here -- the code after "save" is -- and driving them would add a
# second source of timing to a test that is about one.
STUB_MODAL = (
    "(() => { window.showUnsavedChangesModal = async () => 'save';"
    " return true; })()"
)

LEAVE_TO_SLOT_TWO = """
(() => {
  window.__s267.navDone = false;
  navigateToEntry(1).then(
    () => { window.__s267.navDone = true; },
    (e) => { window.__s267.navDone = 'error: ' + e; });
  return true;
})()
"""


def test_an_edit_arriving_while_leaving_the_entry_is_not_lost(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The same defect on the way out, where no tick can rescue it (#267).

    `navigateToEntry` saves, then replaces the form with another entry and
    calls `markClean()`. Leaving `isDirty` honest is not enough on this path:
    `isNavigating` is true throughout, so the autosave tick is suppressed, and
    the form the edit lives in is about to be overwritten. Nothing is holding
    it. So the leave paths ask `saveBeforeLeaving()` whether the save was
    overtaken and retry once rather than pressing on.

    Found by `wimi-windows-2` reading the path after the first fix landed, and
    its example is the reason this is not a corner: **dictation inserts
    asynchronously and calls `markDirty()` itself**, so a transcript can arrive
    after Next was clicked and "save" chosen, with the student not typing at
    all.

    The last assertion is the control. Refusing to navigate whenever the form
    is dirty would pass everything above and strand the student on one entry,
    so this checks the navigation actually completed.
    """
    session_id, _entry_id = seed_session_with_draft(
        wimi_session.user.db, name="Autosave 267 leaving")
    wimi_page.goto("entry-form", query={"session_id": session_id})
    wait_for_form_ready(wimi_page)
    _install_hooks(wimi_page)
    assert wimi_page.eval_js(STUB_MODAL) is True

    _type_answer(wimi_page, BASE_ANSWER, replace=True)
    assert wimi_page.eval_js("EntryState.isDirty === true") is True

    # ---- Act: leave, and let something land inside the save's window ------
    assert wimi_page.eval_js(LEAVE_TO_SLOT_TWO) is True
    assert poll(wimi_page, "window.__s267.callStarted >= 1", timeout_ms=20000), (
        "leaving the entry never reached updateQuestionEntry, so the modal "
        "stub or navigateToEntry did not take the 'save' branch")

    _type_answer(wimi_page, LATE_ANSWER, replace=False)
    assert wimi_page.eval_js("window.__s267.callDone === 0") is True, (
        "the save completed before the late edit was typed, so the edit was "
        "never inside the window. Raise SAVE_DELAY_MS")

    assert poll(wimi_page, "window.__s267.navDone === true", timeout_ms=60000), (
        "navigateToEntry never settled: %r"
        % wimi_page.eval_js("window.__s267.navDone"))

    # ---- Assert -----------------------------------------------------------
    expected = BASE_ANSWER + LATE_ANSWER
    stored = _saved_answer(wimi_session, session_id)
    assert stored == expected, (
        f"question_entries.correct_answer holds {stored!r}, not {expected!r}. "
        f"The edit arrived while the entry was being saved on the way out, "
        f"and the form was then replaced -- so it is in no field, no flag and "
        f"no row. This is the path with no autosave tick to recover it")

    assert wimi_page.eval_js("EntryState.currentEntryIndex === 1") is True, (
        "the navigation never completed. Refusing to move whenever the form "
        "is dirty would satisfy every assertion above and strand the student "
        "on one entry -- a worse bug than the one being fixed")


def _poll_stored_answer(page: WimiPage, session: WimiTestSession,
                        session_id: int, expected: str,
                        *, timeout_ms: int = 40000) -> str:
    """Wait for the row to reach ``expected``, and return whatever it holds.

    Asserting on the **row** is what makes the Back button testable at all:
    `handleBackButton` ends in a `window.location.href` assignment, so the
    document the probe was talking to is gone by the time the save settles.
    The database outlives it.

    Bounded, so "arrived late" and "never arrived" stay distinguishable --
    with the bug the late text never appears at all, so the timeout is a
    verdict rather than a flake.
    """
    waited = 0
    stored = ""
    while waited < timeout_ms:
        stored = _saved_answer(session, session_id)
        if stored == expected:
            return stored
        page.wait_for_timeout(200)
        waited += 200
    return stored


# Let the unload happen, but silence the `beforeunload` guard first.
#
# **The unload is not optional here, and that was measured the hard way.** An
# earlier version of this test parked the flow just before
# `window.location.href = ...`, on the reasoning that the navigation is not
# what the fix changes. The mutant then *passed*: with the document still
# alive, `handleBackButton` never sets `isNavigating`, so the shipped autosave
# tick was still running and rescued the late edit inside this test's own
# poll window. Removing the unload removes the bug -- on this path the loss
# exists precisely because the document goes away.
#
# So the unload stays, and the thing that has to go is the dialog. With the
# fix reverted the form is dirty at unload, the page's own `beforeunload`
# guard fires `preventDefault()`, and QtWebEngine raises a **real modal
# dialog** for a scripted `location.href` -- confirmed by catching
# `Page.javascriptDialogOpening`, an event handled nowhere in `wimi_test/`.
# Accepting it let the assertion report but left the tab wedged: the run
# printed FAILED, then sat until interrupted at 199.9 s, and a later `goto`
# on that tab hung too. `pytest.ini` sets no global timeout, so in CI that is
# an unbounded hang instead of a failure.
#
# `EntryState.isDirty` is therefore cleared in the last statement before the
# assignment. Everything under test -- the modal branch, `saveBeforeLeaving()`
# and its retry -- has already run by then, and the assertion is on the row
# rather than on the flag, so nothing being measured is suppressed. What is
# suppressed is the *backstop*, which this incidentally establishes does work:
# QtWebEngine honours `beforeunload` on a scripted navigation, and this fix is
# what keeps the flag it reads honest.
SILENCE_UNLOAD_PROMPT = """
(() => {
  const real = window.autoSuspendTimerForNavigation;
  window.autoSuspendTimerForNavigation = async () => {
    await real();
    EntryState.isDirty = false;
  };
  return true;
})()
"""


def test_an_edit_arriving_while_the_back_button_saves_is_not_lost(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The Back button is the same path with no form left at all (#267).

    `handleBackButton` is wired to `#btn-back` at `question_entry.js:4564`,
    so every student who leaves the entry form by the Back button goes
    through it -- and nothing in `tests/` or `wimi_test/` referenced it
    before this test, which `wimi-windows-2` established by grep after
    asking the question. Its guard was reasoning-only; this is the
    measurement.

    It is worse than `navigateToEntry`'s: that one replaces the form, this
    one unloads the document. An edit landing inside the save's window has
    no field, no flag, no tick and no page.
    """
    session_id, _entry_id = seed_session_with_draft(
        wimi_session.user.db, name="Autosave 267 back")
    wimi_page.goto("entry-form", query={"session_id": session_id})
    wait_for_form_ready(wimi_page)
    _install_hooks(wimi_page)
    assert wimi_page.eval_js(STUB_MODAL) is True
    assert wimi_page.eval_js(SILENCE_UNLOAD_PROMPT) is True

    _type_answer(wimi_page, BASE_ANSWER, replace=True)
    assert wimi_page.eval_js("EntryState.isDirty === true") is True

    # ---- Act: a real click on the real Back button -----------------------
    real_click(wimi_page, centre_of(wimi_page, "#btn-back"))
    assert poll(wimi_page, "window.__s267.callStarted >= 1", timeout_ms=20000), (
        "clicking Back never reached updateQuestionEntry -- the handler is "
        "not bound, or the modal stub did not take the 'save' branch")

    _type_answer(wimi_page, LATE_ANSWER, replace=False)
    assert wimi_page.eval_js("window.__s267.callDone === 0") is True, (
        "the save completed before the late edit was typed, so the edit was "
        "never inside the window. Raise SAVE_DELAY_MS")

    # ---- Assert on the row; the page is on its way out -------------------
    expected = BASE_ANSWER + LATE_ANSWER
    stored = _poll_stored_answer(wimi_page, wimi_session, session_id, expected)

    assert stored == expected, (
        f"question_entries.correct_answer holds {stored!r}, not {expected!r}. "
        f"The edit arrived while Back was saving, and then the document "
        f"unloaded. There is no field, no flag, no autosave tick and no page "
        f"left holding it")

    # The control in the other direction, and it has to be asked of the
    # *document* rather than of `EntryState`: by now the entry form's
    # JavaScript context is gone, so probing `window.__s267` here raises
    # `eval error: Uncaught` -- which is how this assertion was first written
    # and how that was found. `poll` swallows the mid-navigation errors.
    assert poll(wimi_page,
                "location.pathname.endsWith('session_setup.html')",
                timeout_ms=20000), (
        "the student never left the entry form, i.e. saveBeforeLeaving() "
        "refused. Refusing to leave whenever the form is dirty satisfies the "
        "row assertion above and would trap the student on one entry -- a "
        "worse bug than the one being fixed")
