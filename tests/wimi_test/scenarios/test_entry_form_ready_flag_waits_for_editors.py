"""Issue #114 — ``EntryState.isLoading`` must stop going false early.

``isLoading`` is the flag every entry-form scenario waits on for "the
form is ready", and #99/#105 hardened the harness around exactly that.
It was lying: measured on the spike branch, it went false **127–147 ms
before the rich text editors were actually mounted**, in every condition
tested. In that tail ``resetFormForNewEntry()`` has already queued ``''``
into both editors and TinyMCE's ``init`` has not yet flushed it, so the
page looks completely finished while the reflection box is still going
to be wiped.

The fix folds the flag into ``markEntryFormReady()``, the same gate that
removes ``inert``, so one function owns both and the flag cannot claim
ready while the page is still refusing input.

How this is asserted
--------------------
Not with timings — with an **atomic snapshot**. A document-start script
(installed through ``Page.addScriptToEvaluateOnNewDocument``, so it is
running before any of the page's own scripts) records, at the exact
instant the ``inert`` attribute is removed, what both editors reported at
that moment; and separately the first sample in which ``isLoading`` is
false, with the editors' state read in the same tick. No clock
comparison, nothing to tune, nothing to flake.

The page under test carries no test-only hooks: everything here is
installed from the harness side.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import (
    poll,
    seed_empty_session,
    wait_for_form_ready,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# Installed before the page's first script. The MutationObserver is the
# exact handover instant: markEntryFormReady() sets isLoading and then
# removes the attribute as its last statement, so a snapshot taken in the
# observer callback sees the state the form was handed over in.
RECORDER = """
(() => {
  const snap = () => {
    const page = document.querySelector('.entry-page');
    const S = (typeof EntryState !== 'undefined') ? EntryState : null;
    const r = S ? S.reflectionEditor : null;
    const e = S ? S.explanationEditor : null;
    return {
      t: Math.round(performance.now()),
      inert: page ? page.hasAttribute('inert') : null,
      isLoading: S ? S.isLoading : null,
      isFormReady: S ? S.isFormReady : null,
      reflectionExists: !!r,
      reflectionInit: r ? r.isInitialized === true : null,
      explanationExists: !!e,
      explanationInit: e ? e.isInitialized === true : null
    };
  };
  const state = {handover: null, firstReady: null};
  new MutationObserver((records) => {
    for (const rec of records) {
      const el = rec.target;
      if (rec.attributeName !== 'inert') continue;
      if (!el.classList || !el.classList.contains('entry-page')) continue;
      if (!el.hasAttribute('inert') && state.handover === null) {
        state.handover = snap();
      }
    }
  // `document`, not `document.documentElement`: this script runs before the
  // document has been parsed, so documentElement is still null here.
  }).observe(document,
             {subtree: true, attributes: true, attributeFilter: ['inert']});
  const iv = setInterval(() => {
    if (state.firstReady === null && typeof EntryState !== 'undefined'
        && EntryState.isLoading === false) {
      state.firstReady = snap();
    }
    if (state.firstReady !== null && state.handover !== null) clearInterval(iv);
  }, 5);
  window.__w114rec = state;
})();
"""

RECORDED = ("(() => { const s = window.__w114rec;"
            " if (!s || !s.handover || !s.firstReady) return null;"
            " return JSON.stringify(s); })()")


@pytest.mark.slow
@pytest.mark.regression
def test_isloading_does_not_go_false_before_the_editors_mount(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange ----------------------------------------------------------
    session_id = seed_empty_session(wimi_session.user.db, name="W114 flag")
    wimi_page.tab.Page.enable()
    wimi_page.tab.Page.addScriptToEvaluateOnNewDocument(source=RECORDER)

    # ---- Act --------------------------------------------------------------
    wimi_page.goto("entry-form", query={"session_id": session_id},
                   wait_for_bridge=False)
    wait_for_form_ready(wimi_page)
    assert poll(wimi_page, f"({RECORDED} !== null)", timeout_ms=30000), (
        "the recorder never saw both the handover and isLoading going false")
    recorded = json.loads(wimi_page.eval_js(RECORDED))
    handover, first_ready = recorded["handover"], recorded["firstReady"]

    # ---- Assert -----------------------------------------------------------
    # The whole point: at the instant the form was handed over, TinyMCE had
    # actually mounted. Before the fix these two are false — the attribute
    # did not exist and isLoading went false 127-147 ms too early.
    assert handover["reflectionExists"] and handover["explanationExists"], (
        f"the editors had not even been constructed at handover: {handover!r}")
    assert handover["reflectionInit"] is True, (
        f"the form was handed over while the reflection editor was still "
        f"mounting — the 127-147 ms window in which typed text is erased by "
        f"TinyMCE's queue flush: {handover!r}")
    assert handover["explanationInit"] is True, (
        f"the form was handed over while the explanation editor was still "
        f"mounting: {handover!r}")
    assert handover["isLoading"] is False, (
        f"inert was removed while isLoading still said the form was loading; "
        f"the two must move together: {handover!r}")

    # And the flag itself, read the moment it first goes false — this is
    # what every other entry-form scenario waits on (#99, #105).
    assert first_ready["reflectionInit"] is True, (
        f"EntryState.isLoading went false before the reflection editor was "
        f"ready, so waiting on it is still not a readiness signal: "
        f"{first_ready!r}")
    assert first_ready["explanationInit"] is True, (
        f"EntryState.isLoading went false before the explanation editor was "
        f"ready: {first_ready!r}")
    assert first_ready["inert"] is False, (
        f"isLoading said ready while the page was still refusing input: "
        f"{first_ready!r}")

    # ---- Assert: and it does clear ----------------------------------------
    final = json.loads(wimi_page.eval_js(
        "(() => JSON.stringify({"
        " inert: document.querySelector('.entry-page').hasAttribute('inert'),"
        " isLoading: EntryState.isLoading,"
        " isFormReady: EntryState.isFormReady}))()"))
    assert final == {"inert": False, "isLoading": False, "isFormReady": True}, (
        f"the form never reached a clean ready state: {final!r}")


# ---------------------------------------------------------------------------
# Why these assertions catch the regression
# ---------------------------------------------------------------------------
#
# * Against master the MutationObserver never fires at all (nothing sets or
#   removes `inert`), so `handover` stays null and the poll fails with
#   "never saw both the handover and isLoading going false".
# * Against a fix that clears `inert` at the end of the init chain instead
#   of waiting for the editors, `handover["reflectionInit"]` comes back
#   `false` — verified by temporarily removing the editor gate from
#   `markEntryFormReady()`.
# * Against a fix that removes `inert` but leaves `EntryState.isLoading`
#   where it was, `first_ready["inert"]` comes back `true`: the flag would
#   again be claiming ready while the page refuses input.
