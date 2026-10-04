"""Dictation inserts at the caret. It never replaces and never appends (#59).

§3.5's decision, in the owner's own framing: the student may speak, then
type, then speak again, and *"the explanation (as I say it)"* is
dictation, not a recording booth. A control that overwrites what is
already written is hostile — and the damage is silent, because the field
still looks full afterwards.

Three failure modes this rules out, all of which look plausible in code:

* **replace** — ``setContent()`` instead of ``insertContent()``. Loses
  everything typed, with only TinyMCE's undo stack between the student
  and a lost paragraph.
* **append to the end** — right whenever the caret happens to be at the
  end, which is most of the time, and wrong the moment the student puts
  it mid-paragraph to add a clause. It passes any test that types and
  then dictates without moving the caret, which is why this one moves it.
* **prepend** — what TinyMCE's *default* selection produces in an editor
  that has never been focused (``captureInsertionPoint({atEnd: ...})``
  exists for exactly that). A second test below covers it, because the
  never-focused case is the first-ever use of the feature.

The caret is captured when recording **starts**, not when the transcript
lands: the student's model is "I put the cursor here and started
talking", and eight seconds later they may have clicked elsewhere. The
press on the microphone button is itself a click elsewhere, so this test
is also the check that ``getBookmark(2, true)`` survives losing focus.
"""
from __future__ import annotations

import json

import pytest

from _helpers.stt_form import (
    editor_text,
    install_stt_stub,
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

HEAD = "The clot forms first"
TAIL = "and the vessel occludes later"
TYPED = f"{HEAD} {TAIL}"
SAID = "in the deep veins of the calf"

pytestmark = [pytest.mark.slow, pytest.mark.regression]

# Put the caret between the two halves of the typed sentence, inside the
# editor's own document. Returns what the caret can see behind it, so the
# test fails loudly if the placement did not take rather than silently
# measuring an append.
PLACE_CARET = """
(() => {
  const ed = EntryState.reflectionEditor.getEditor();
  const walker = ed.getDoc().createTreeWalker(
      ed.getBody(), NodeFilter.SHOW_TEXT, null, false);
  let node;
  while ((node = walker.nextNode())) {
    const at = node.nodeValue.indexOf(%s);
    if (at === -1) continue;
    ed.selection.setCursorLocation(node, at + %d);
    ed.focus();
    const rng = ed.selection.getRng();
    return JSON.stringify({placed: true, offset: rng.startOffset,
                           text: node.nodeValue});
  }
  return JSON.stringify({placed: false, body: ed.getBody().textContent});
})()
"""


def _open(wimi_session: WimiTestSession, wimi_page: WimiPage,
          name: str) -> None:
    session_id = seed_entry_session(wimi_session.user.db, name=name)
    wimi_page.goto("entry-form", query={"session_id": session_id})
    wait_for_form_ready(wimi_page)
    install_stt_stub(wimi_page)


def _dictate_into_reflection(wimi_page: WimiPage) -> None:
    start_recording(wimi_page, "reflection")
    stop_and_hold(wimi_page, "reflection")
    release_transcript(wimi_page, SAID)
    wait_for_state(wimi_page, "reflection", "ready")


def test_a_transcript_lands_at_the_caret_and_keeps_what_was_typed(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange ----------------------------------------------------------
    _open(wimi_session, wimi_page, "STT caret")
    real_click(wimi_page, centre_of(wimi_page, "#reflection-editor iframe"))
    real_type(wimi_page, TYPED)
    assert TYPED in editor_text(wimi_page, "reflection"), (
        "the typed sentence never reached the reflection editor, so nothing "
        "below would be testing whether dictation preserves it")

    placed = json.loads(wimi_page.eval_js(
        PLACE_CARET % (json.dumps(HEAD), len(HEAD))))
    assert placed["placed"] is True, (
        f"could not put the caret between the two halves: {placed!r}")

    # ---- Act --------------------------------------------------------------
    _dictate_into_reflection(wimi_page)

    # ---- Assert -----------------------------------------------------------
    text = editor_text(wimi_page, "reflection")
    assert HEAD in text and TAIL in text, (
        f"dictation destroyed what the student had already written "
        f"({text!r}). insertContent() at the caret, never setContent()")
    assert SAID in text, f"the transcript is not in the field at all: {text!r}"

    head_at, said_at, tail_at = (text.index(HEAD), text.index(SAID),
                                 text.index(TAIL))
    assert head_at < said_at < tail_at, (
        f"the transcript did not land where the caret was ({text!r}). "
        f"Appending to the end is right only while the caret happens to be "
        f"there, and the caret is captured at record-start precisely because "
        f"pressing the microphone moves focus off the editor")
    assert f"{HEAD} {SAID} {TAIL}" in " ".join(text.split()), (
        f"the transcript welded onto a neighbouring word instead of being "
        f"spaced into the sentence: {text!r}")


def test_an_untouched_field_gets_the_transcript_at_the_end_not_the_front(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The never-focused editor, which is the very first use of the feature.

    TinyMCE's default selection in an editor nobody has clicked is the
    start of the document, so the obvious implementation *prepends*.
    ``captureInsertionPoint({atEnd: true})`` is what stops that, keyed on
    whether a ``focus`` event has ever been seen.
    """
    # ---- Arrange ----------------------------------------------------------
    _open(wimi_session, wimi_page, "STT unfocused")
    # Content that arrived without the student ever putting a caret in the
    # field: this is the applyAutofillData()/populate shape.
    wimi_page.eval_js(
        "(() => { EntryState.reflectionEditor.setContent(%s); return true; })()"
        % json.dumps(f"<p>{TYPED}</p>"))
    assert TYPED in editor_text(wimi_page, "reflection")

    # ---- Act --------------------------------------------------------------
    _dictate_into_reflection(wimi_page)

    # ---- Assert -----------------------------------------------------------
    text = editor_text(wimi_page, "reflection")
    assert HEAD in text and TAIL in text, (
        f"the existing content was replaced rather than added to: {text!r}")
    assert text.index(TAIL) < text.index(SAID), (
        f"the transcript was prepended to a field the student had never "
        f"focused ({text!r}) — that is TinyMCE's default selection, and it "
        f"puts spoken words in front of written ones")


# ---------------------------------------------------------------------------
# Why each assertion catches the regression
# ---------------------------------------------------------------------------
#
# * Making `insertTranscript` collapse to the end of the body before
#   inserting — the append implementation — fails the first test on the
#   ordering assertion and leaves the second green, which is the point:
#   append is *correct* for a field nobody has focused and wrong for one
#   the student has put a caret in.
# * Dropping `captureInsertionPoint`'s `atEnd` branch fails the second and
#   leaves the first green. The two are orthogonal and neither covers the
#   other. Both verified by doing exactly that.
# * `setContent()` in place of `insertContent()` fails both on the "the
#   student's own words are still there" assertion.
# * The caret is placed *before* the microphone is pressed, so the bookmark
#   has to survive the button taking focus — which is the whole reason
#   `getBookmark(2, true)` is the non-intrusive form.
