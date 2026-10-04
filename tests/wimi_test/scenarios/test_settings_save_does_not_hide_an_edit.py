"""Issue #119's other half - `clearDirty()` must not report a discarded edit.

    "[bug] Settings changed while the page is still loading are silently
    reverted, **and clearDirty() hides that they were**"

The gate (``test_settings_gate_until_ready.py``) closes the **load** window:
nothing can be typed before ``populateForm()`` runs, so the ``clearDirty()`` on
the next line has nothing left to hide. It does not close the **save** window,
which is a different one and still reachable:

``saveSettings()`` computes its diff from ``currentPreferences``, awaits
``api.updateUserPreferences(changes)``, and then - on master - assigns
``currentPreferences = updated`` and calls ``clearDirty()``. A control changed
during that await has already written the new value into
``currentPreferences`` and set ``isDirty``; the assignment overwrites it with
the server's answer and ``clearDirty()`` says the page is clean. Three things
then disagree: the control on screen shows the student's value, the model holds
the old one, and the guard says there is nothing unsaved. Pressing Save again
reports **"No changes to save"**, because the diff was erased along with the
edit.

This is the shape #267 fixed on the entry form, where ``saveEntryAsDraft``
snapshots ``editGeneration`` beside its form snapshot and only calls
``markClean()`` if it has not moved. ``saveSettings()`` now does the same with
``this.editGeneration``, bumped by ``markDirty()`` - the single funnel every
edit already goes through.

How the window is widened
-------------------------
``_helpers.w114_form_ready.install_slow_bridge`` holds *every* bridge call,
which is right for a load-window test and wrong here: the page makes a dozen
calls during init and the probe only needs one of them held. So the save call
alone is wrapped, from ``eval_js`` after the page is ready. The code under test
is untouched either way - what is slowed is a bridge round trip, exactly as the
shared helper does, just one of them and later.
"""
from __future__ import annotations

import json

import pytest

from _helpers.page_gate import wait_for_release
from _helpers.w114_form_ready import centre_of, poll, real_click, real_type
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

STORED_SECONDS = 300
FIRST_EDIT_SECONDS = "45"
PAGE_RENDERED = "(() => !!document.getElementById('dashboard_auto_refresh_seconds'))()"

# `settingsPage` is a top-level `const` in a classic script: a global binding,
# not a property of `window`.
STATE = """
(() => {
  const p = settingsPage;
  return JSON.stringify({
    isDirty: p.isDirty,
    current: p.currentPreferences.dashboard_auto_refresh_seconds,
    original: p.originalPreferences.dashboard_auto_refresh_seconds,
    shown: document.getElementById('dashboard_auto_refresh_seconds').value,
    animationsCurrent: p.currentPreferences.show_animations,
    animationsShown: document.getElementById('show_animations').checked
  });
})()
"""

# Hold the one call that matters, and record that it was held so a hook that
# silently failed to attach cannot read as "no edit was lost".
HOLD_SAVE = """
(() => {
  const real = api.updateUserPreferences.bind(api);
  window.__saveHeld = 0;
  window.__saveResolved = 0;
  api.updateUserPreferences = function (...args) {
    window.__saveHeld += 1;
    return new Promise((resolve, reject) => setTimeout(() => {
      Promise.resolve(real(...args)).then(
        (v) => { window.__saveResolved += 1; resolve(v); },
        (e) => { window.__saveResolved += 1; reject(e); });
    }, 2500));
  };
  return true;
})()
"""


def _state(wimi_page: WimiPage) -> dict:
    return json.loads(wimi_page.eval_js(STATE))


def _open_settings(wimi_session: WimiTestSession, wimi_page: WimiPage) -> None:
    db = wimi_session.user.db
    db.update_preferences(dashboard_auto_refresh_seconds=STORED_SECONDS,
                          show_animations=True)
    db.conn.commit()
    wimi_page.goto("settings")
    assert poll(wimi_page, PAGE_RENDERED), "the settings markup never rendered"
    wait_for_release(wimi_page)


@pytest.mark.slow
@pytest.mark.regression
def test_a_change_made_while_saving_is_not_reported_as_saved(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The reachable half of "clearDirty() hides that they were"."""
    # ---- Arrange ----------------------------------------------------------
    _open_settings(wimi_session, wimi_page)
    # Dashboard & Analytics is the fourth sidebar panel; the auto-refresh
    # field lives there and has no `maxlength`, so real typing can replace it.
    wimi_page.eval_js(
        "document.querySelector('[data-panel=\"dashboard_analytics\"]').click()")
    assert poll(
        wimi_page,
        "(() => { const el ="
        " document.getElementById('dashboard_auto_refresh_seconds');"
        " return !!el && el.getBoundingClientRect().height > 0; })()"), (
        "the Dashboard & Analytics panel never became visible")

    # A real, hit-tested edit: select the field's contents and retype them.
    real_click(wimi_page, centre_of(wimi_page, "#dashboard_auto_refresh_seconds"))
    wimi_page.eval_js(
        "document.getElementById('dashboard_auto_refresh_seconds').select()")
    real_type(wimi_page, FIRST_EDIT_SECONDS)
    wimi_page.eval_js(
        "document.getElementById('dashboard_auto_refresh_seconds')"
        ".dispatchEvent(new Event('change', {bubbles: true}))")
    before_save = _state(wimi_page)
    assert before_save["isDirty"] is True, (
        f"the first edit did not reach the page's model, so this test never "
        f"gets to the window it is about: {before_save!r}")

    # ---- Act: save, and change something else while it is in flight -------
    assert wimi_page.eval_js(HOLD_SAVE) is True
    wimi_page.eval_js("document.getElementById('saveBtn').click()")
    assert poll(wimi_page, "window.__saveHeld === 1", timeout_ms=10000), (
        "the save call was never made, so nothing was held and the window "
        "below does not exist")

    # Back to Appearance and toggle the animations checkbox with a real click.
    # This is the edit the student makes while the spinner is up.
    wimi_page.eval_js(
        "document.querySelector('[data-panel=\"appearance\"]').click()")
    assert poll(wimi_page, "(() => { const el ="
                " document.getElementById('show_animations');"
                " return !!el && el.getBoundingClientRect().height > 0; })()")
    real_click(wimi_page, centre_of(wimi_page, "#show_animations"))
    mid_save = _state(wimi_page)
    assert wimi_page.eval_js("window.__saveResolved") == 0, (
        f"the save resolved before the mid-flight edit landed, so this run "
        f"measured nothing: {mid_save!r}")
    assert mid_save["animationsShown"] is False, (
        f"the mid-flight click did not reach the checkbox: {mid_save!r}")

    # ---- Act: let the save finish -----------------------------------------
    assert poll(wimi_page, "window.__saveResolved === 1", timeout_ms=20000), (
        "the held save never resolved")
    wimi_page.wait_for_timeout(250)
    after = _state(wimi_page)

    # ---- Assert: the edit survived, and is not reported as saved ----------
    assert after["animationsCurrent"] is False, (
        f"the change made while the save was in flight was discarded from "
        f"the page's model (show_animations={after['animationsCurrent']!r}) "
        f"while the checkbox on screen still shows "
        f"{after['animationsShown']!r}. `currentPreferences = updated` is the "
        f"assignment that does it (#119, #267). State: {after!r}")
    assert after["animationsShown"] is False, (
        f"the checkbox reverted itself: {after!r}")
    assert after["isDirty"] is True, (
        f"the page reports itself clean after discarding an edit "
        f"(isDirty={after['isDirty']!r}). That is the half of #119's title "
        f"the gate does not cover: the unsaved-changes guard will not fire "
        f"and Save is not offered for a change the student can still see on "
        f"screen. State: {after!r}")
    assert after["original"] == int(FIRST_EDIT_SECONDS), (
        f"originalPreferences does not hold what was actually written "
        f"(original={after['original']!r}, sent={FIRST_EDIT_SECONDS}); the "
        f"next diff would be computed against the wrong baseline. "
        f"State: {after!r}")

    # ---- Assert: and a second Save really sends it ------------------------
    # The clearest proof that the diff survived: pressing Save again writes
    # the mid-flight edit to the database, rather than reporting "No changes
    # to save" because the model was overwritten.
    wimi_page.eval_js("document.getElementById('saveBtn').click()")
    db = wimi_session.user.db
    assert poll(
        wimi_page,
        "window.__saveResolved === 2", timeout_ms=20000), (
        "the second Save made no bridge call at all, which is what "
        "'No changes to save' looks like from here: saveSettings() found an "
        "empty diff because the edit had been erased from "
        "currentPreferences (#119)")
    settled = None
    for _ in range(80):
        settled = db.get_all_settings()
        if settled.get("show_animations") in (False, 0):
            break
        wimi_page.wait_for_timeout(50)
    assert settled.get("show_animations") in (False, 0), (
        f"the mid-flight edit never reached the database even after a second "
        f"Save (show_animations={settled.get('show_animations')!r}); the "
        f"student's change is gone for good")


@pytest.mark.slow
@pytest.mark.regression
def test_an_ordinary_save_still_clears_the_dirty_flag(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The other side of the guard, which the test above cannot see.

    ``saveSettings()`` only calls ``clearDirty()`` when ``editGeneration`` has
    not moved across the await. That is one branch of a condition, and the
    test above exercises exactly one of them. A guard that *never* cleared --
    ``editGeneration`` bumped by something other than a student edit, the
    comparison inverted, the snapshot taken on the wrong side of the await --
    satisfies every assertion in this file and leaves the page **permanently
    dirty after every successful save**: the unsaved-changes banner never goes
    away, the Back link raises ``'You have unsaved changes. Save before
    leaving?'`` each time, and the toast tells the student something is still
    unsaved when nothing is.

    Measured: with ``if (!editedMidSave)`` replaced by ``if (false)``, all 32
    settings-touching regression scenarios on this branch passed. The write
    still reaches the database, so a test that only checks persistence cannot
    tell the two apart -- which is why this asserts the *page's own report*.
    """
    # ---- Arrange ----------------------------------------------------------
    _open_settings(wimi_session, wimi_page)
    assert poll(wimi_page, "(() => { const el ="
                " document.getElementById('show_animations');"
                " return !!el && el.getBoundingClientRect().height > 0; })()"), (
        "the Appearance panel's animations checkbox never became visible")

    # One real edit, and nothing else. No bridge call is held: this is the
    # ordinary path, where the save resolves before the student does anything.
    real_click(wimi_page, centre_of(wimi_page, "#show_animations"))
    assert _state(wimi_page)["isDirty"] is True, (
        "the edit did not reach the page's model, so there is no dirty state "
        "for the save to clear and this test measures nothing")

    # ---- Act --------------------------------------------------------------
    wimi_page.eval_js("document.getElementById('saveBtn').click()")
    db = wimi_session.user.db
    saved = None
    for _ in range(100):
        saved = db.get_all_settings()
        if saved.get("show_animations") in (False, 0):
            break
        wimi_page.wait_for_timeout(50)
    assert saved.get("show_animations") in (False, 0), (
        f"the save never reached the database "
        f"(show_animations={saved.get('show_animations')!r}), so what follows "
        f"would be measuring a failed save rather than a clean one")
    wimi_page.wait_for_timeout(250)

    # ---- Assert: the page reports itself clean ----------------------------
    after = _state(wimi_page)
    assert after["isDirty"] is False, (
        f"the page still reports unsaved changes after an ordinary save with "
        f"no concurrent edit (isDirty={after['isDirty']!r}). clearDirty() is "
        f"behind `if (!editedMidSave)`; a guard that never fires leaves the "
        f"unsaved-changes banner up for good and makes the Back link prompt "
        f"'You have unsaved changes' after every save (#119). State: {after!r}")
    assert after["animationsCurrent"] == after["animationsShown"], (
        f"currentPreferences was not refreshed from the server's answer "
        f"(model={after['animationsCurrent']!r}, "
        f"screen={after['animationsShown']!r}): {after!r}")

    warning_hidden = wimi_page.eval_js(
        "(() => { const w = document.getElementById('previewWarning');"
        " return !!w && !w.classList.contains('visible'); })()")
    assert warning_hidden is True, (
        "the 'unsaved changes' warning is still showing after a clean save; "
        "clearDirty() is what hides it and it did not run")

    toast = wimi_page.eval_js(
        "(() => { const t = document.querySelector('.settings-toast');"
        " return t ? (t.textContent || '').trim() : null; })()")
    assert toast == "Settings saved successfully", (
        f"an ordinary save reported {toast!r}. The mid-save wording is "
        f"reserved for a save that really did leave an edit behind -- saying "
        f"it unconditionally is #240's rule broken in the other direction, "
        f"and it is what a never-firing guard looks like from the student's "
        f"side (#119)")


# ---------------------------------------------------------------------------
# Why each assertion catches the regression
# ---------------------------------------------------------------------------
#
# Against master (`currentPreferences = updated; this.clearDirty();`
# unconditionally):
#
# * `after["animationsCurrent"] is False` fails - the model is overwritten with
#   the server's answer, which still has show_animations true.
# * `after["isDirty"] is True` fails - this is literally the "clearDirty()
#   hides that they were" clause in the issue's title.
# * the second-Save assertion fails with no bridge call, because the diff is
#   empty; that is the user-visible end of it, "No changes to save" for a
#   change that is still on screen.
#
# `after["original"] == FIRST_EDIT_SECONDS` is the control in the other
# direction: a fix that simply declined to touch anything after the await
# would leave `originalPreferences` stale, so every later diff would re-send
# the first edit forever. The fix updates the baseline and keeps the edit,
# which is the only combination that satisfies both.
#
# `window.__saveResolved == 0` at the mid-save read, and `__saveHeld == 1`
# before it, are what make this a measurement rather than a race: without
# them a run where the save finished first would pass while testing nothing.
