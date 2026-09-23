"""Issue #114 — the entry form must refuse input until it is genuinely ready.

    "`question_entry.html` renders the complete form — every field
    editable, every footer button present and enabled — before
    `initializeEntryPage()` has run. [...] Typing is erased. [...]
    Clicking Save as Draft does nothing at all."

Three distinct windows were measured on the spike branch, all from
``domContentLoadedEventEnd``:

===========================  ==========================  ==========  ===========
what is lost                 ends at                     small/cold  large/warm
===========================  ==========================  ==========  ===========
typing erased                ``resetFormForNewEntry()``  110 ms      ~31 ms
click swallowed              the five handler binds      451 ms      211–252 ms
rich text erased             TinyMCE ``init``            578 ms      354–382 ms
===========================  ==========================  ==========  ===========

The third is the serious one and the least obvious. ``#47`` does not
cover it: #47 guards the *app* setting queued content that a premature
save reads back empty. This is the opposite direction — the reflection
iframe becomes editable 118–436 ms *after* ``resetFormForNewEntry()``
has queued ``''`` into the editor, and TinyMCE's ``init`` then flushes
that empty string over whatever the student typed. Measured three times
on unfixed code: the text landed visibly in the iframe, read back as
``""``, ``isDirty: false``, no toast.

The fix ships ``.entry-page`` with ``inert`` and removes it in
``markEntryFormReady()``, gated on the end of the init chain *and* both
rich text editors reporting ``isInitialized``.

Why these tests are built the way they are
------------------------------------------
``inert`` blocks hit-tested input and focus but not programmatic DOM
writes — ``el.value = 'x'``, ``el.click()`` and ``body.innerHTML = ...``
all still work on an inert subtree. A test written with those would pass
against a completely unfixed build. Every gesture below therefore goes
through ``Input.dispatchMouseEvent`` / ``Input.insertText``, and the
window is widened by holding the page's bridge calls from a document-start
hook rather than raced. See ``_helpers/w114_form_ready.py``.

Each test asserts the *cleared* state as explicitly as the blocked one:
a permanently inert form would be a much worse bug than the one being
fixed, and a test that only checks "input was refused" cannot tell the
two apart.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import (
    REFLECTION_BODY,
    REFLECTION_EDITABLE_AND_INERT,
    arm_save_draft_probe,
    assert_slow_bridge_took,
    assert_still_in_window,
    centre_of,
    click_reached_save_draft,
    install_slow_bridge,
    is_inert,
    poll,
    real_click,
    real_type,
    rich_state,
    seed_empty_session,
    seed_session_with_draft,
    wait_for_form_ready,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

DURING = "TYPED-DURING-INIT"
AFTER = "TYPED-AFTER-READY"

FORM_RENDERED = "(() => !!document.getElementById('user-answer'))()"
ANSWER_VALUE = "document.getElementById('user-answer').value"


@pytest.mark.slow
@pytest.mark.regression
def test_typing_and_clicks_are_refused_until_the_form_is_ready(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Windows 1 and 2: the erased keystroke and the swallowed click."""
    # ---- Arrange ----------------------------------------------------------
    session_id = seed_empty_session(wimi_session.user.db)
    install_slow_bridge(wimi_page)
    wimi_page.goto("entry-form", query={"session_id": session_id},
                   wait_for_bridge=False)
    assert poll(wimi_page, FORM_RENDERED), "the entry form markup never rendered"
    assert_slow_bridge_took(wimi_page)

    # ---- Act: inside the window -------------------------------------------
    assert_still_in_window(wimi_page, "before the probe started")
    arm_save_draft_probe(wimi_page)

    real_click(wimi_page, centre_of(wimi_page, "#user-answer"))
    active_during = wimi_page.eval_js(
        "(() => document.activeElement ? document.activeElement.id"
        " || document.activeElement.tagName : null)()")
    real_type(wimi_page, DURING)
    value_during = wimi_page.eval_js(ANSWER_VALUE)
    assert_still_in_window(wimi_page, "after typing into 'Your Answer'")

    real_click(wimi_page, centre_of(wimi_page, "#btn-save-draft"))
    arrived_during = click_reached_save_draft(wimi_page)
    assert_still_in_window(wimi_page, "after clicking Save as Draft")

    # ---- Assert: refused --------------------------------------------------
    assert active_during != "user-answer", (
        f"focus reached 'Your Answer' during init (activeElement="
        f"{active_during!r}); a keystroke would have been erased by "
        f"resetFormForNewEntry()")
    assert value_during == "", (
        f"text typed during init landed in 'Your Answer' ({value_during!r}) "
        f"— the reset would have wiped it without a word")
    assert arrived_during is False, (
        "a real click reached Save as Draft during init, where it has no "
        "listener yet and is swallowed in silence")

    # ---- Act: after the form is handed over -------------------------------
    wait_for_form_ready(wimi_page)
    real_click(wimi_page, centre_of(wimi_page, "#user-answer"))
    real_type(wimi_page, AFTER)
    value_after = wimi_page.eval_js(ANSWER_VALUE)
    mark = wimi_page.mark_bridge_calls()
    real_click(wimi_page, centre_of(wimi_page, "#btn-save-draft"))
    arrived_after = click_reached_save_draft(wimi_page)

    # ---- Assert: cleared, as explicitly as it was blocked -----------------
    assert is_inert(wimi_page) is False, (
        "the form stayed inert after init finished — a permanently dead form "
        "is a worse bug than the one #114 describes")
    assert value_after == AFTER, (
        f"typing did not work after the form was handed over "
        f"(value={value_after!r})")
    assert arrived_after is True, (
        "Save as Draft never became clickable after init finished")
    assert wimi_page.wait_for_bridge_call(
        "createQuestionEntry", since_ts=mark, timeout_ms=20000), (
        "Save as Draft was reachable but produced no createQuestionEntry call, "
        "so the click still did nothing")


@pytest.mark.slow
@pytest.mark.regression
def test_rich_text_typed_during_init_is_refused_not_erased(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Window 3 — the reflection box, and the reason this issue matters.

    The interesting instant is not "before init"; it is the moment the
    TinyMCE iframe reports ``isContentEditable`` while the form has not
    been handed over. Unfixed, everything typed there is lost — either to
    the queued ``''`` that ``init`` flushes, or to the reset that follows.
    The test waits for exactly that instant and asserts the page is still
    refusing input when it arrives.
    """
    # ---- Arrange ----------------------------------------------------------
    session_id = seed_empty_session(wimi_session.user.db, name="W114 rich")
    install_slow_bridge(wimi_page)
    wimi_page.goto("entry-form", query={"session_id": session_id},
                   wait_for_bridge=False)
    assert poll(wimi_page, REFLECTION_EDITABLE_AND_INERT, timeout_ms=60000), (
        "never observed the reflection iframe editable while the form was "
        "still inert — either the editor never mounted or the form is being "
        "handed over before it does")
    assert_slow_bridge_took(wimi_page)

    # ---- Act --------------------------------------------------------------
    during = rich_state(wimi_page)
    real_click(wimi_page, centre_of(wimi_page, "#reflection-editor iframe"))
    real_type(wimi_page, DURING)
    body_during = wimi_page.eval_js(REFLECTION_BODY) or ""
    assert_still_in_window(wimi_page, "after typing into the reflection editor")

    # ---- Assert: nothing could be typed, so nothing can be lost -----------
    assert during["editable"] is True, (
        f"precondition: the iframe was expected to be editable here: {during!r}")
    assert DURING not in body_during, (
        f"text was typed into the reflection iframe before the form was handed "
        f"over (state={during!r}, body={body_during!r}). Everything typed there "
        f"is at the mercy of the init chain — the queued '' that TinyMCE's "
        f"`init` flushes, or the reset/populate that has still to run — and it "
        f"goes with isDirty false and no toast")

    # ---- Act: after the form is handed over -------------------------------
    wait_for_form_ready(wimi_page)
    real_click(wimi_page, centre_of(wimi_page, "#reflection-editor iframe"))
    real_type(wimi_page, AFTER)
    after = rich_state(wimi_page)
    content_after = wimi_page.eval_js(
        "(() => { const e = EntryState.reflectionEditor;"
        " return e ? (e.getContent() || {}).html || '' : null; })()") or ""

    # ---- Assert: the editor really works once it is handed over -----------
    assert after["inert"] is False, f"the form stayed inert: {after!r}"
    assert AFTER in (after["html"] or ""), (
        f"the reflection editor never accepted typing after init: {after!r}")
    assert AFTER in content_after, (
        f"typing reached the iframe but RichEditor.getContent() does not see "
        f"it ({content_after!r}) — the queue flush is still winning")
    assert DURING not in content_after, (
        "text from the init window somehow survived into the editor")


@pytest.mark.slow
@pytest.mark.regression
def test_the_draft_loading_path_is_gated_too(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """``populateFormWithEntry()`` — the path the issue body never mentions.

    When the session holds an unfinished draft, init loads it and
    ``populateFormWithEntry()`` overwrites the same fields the reset
    does, unconditionally. A gate aimed only at ``resetFormForNewEntry()``
    would miss the *common* path entirely.
    """
    # ---- Arrange ----------------------------------------------------------
    session_id, _entry_id = seed_session_with_draft(wimi_session.user.db)
    install_slow_bridge(wimi_page)
    wimi_page.goto("entry-form", query={"session_id": session_id},
                   wait_for_bridge=False)
    assert poll(wimi_page, FORM_RENDERED), "the entry form markup never rendered"
    assert_slow_bridge_took(wimi_page)

    # ---- Act: inside the window -------------------------------------------
    assert_still_in_window(wimi_page, "before the probe started")
    real_click(wimi_page, centre_of(wimi_page, "#user-answer"))
    real_type(wimi_page, DURING)
    value_during = wimi_page.eval_js(ANSWER_VALUE)
    assert_still_in_window(wimi_page, "after typing into 'Your Answer'")

    # ---- Assert -----------------------------------------------------------
    assert DURING not in (value_during or ""), (
        f"text typed while the draft was still loading landed in the field "
        f"({value_during!r}); populateFormWithEntry() overwrites it")

    # ---- Act: after the form is handed over -------------------------------
    wait_for_form_ready(wimi_page)
    loaded = json.loads(wimi_page.eval_js(
        "(() => JSON.stringify({"
        " answer: document.getElementById('user-answer').value,"
        " qid: document.getElementById('question-id').value,"
        " reflection: (EntryState.reflectionEditor"
        "   ? (EntryState.reflectionEditor.getContent() || {}).html || '' : null)"
        "}))()"))

    # ---- Assert: the draft loaded intact, and the form is live ------------
    assert loaded["answer"] == "STORED-ANSWER", (
        f"the draft did not load into the form: {loaded!r}")
    assert loaded["qid"] == "Q-STORED", f"draft question id missing: {loaded!r}"
    assert "STORED-REFLECTION" in (loaded["reflection"] or ""), (
        f"the draft's reflection did not reach the editor: {loaded!r}")
    assert is_inert(wimi_page) is False, "the form stayed inert after loading a draft"

    real_click(wimi_page, centre_of(wimi_page, "#user-answer"))
    real_type(wimi_page, AFTER)
    assert AFTER in wimi_page.eval_js(ANSWER_VALUE), (
        "the draft form never became typeable")


@pytest.mark.slow
@pytest.mark.regression
def test_a_failed_init_still_releases_the_form(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The unhappy path, which is where "permanently inert" would hide.

    A form that never comes back is a far worse bug than the one #114
    describes, and the only thing standing between the two is the
    ``finally`` in ``initializeEntryPage()``. A session id that does not
    resolve takes the "Session Not Found" early return from inside the
    ``try``, which is the exit an ``if`` at the end of the happy path
    would miss entirely.
    """
    # ---- Arrange / Act ----------------------------------------------------
    wimi_page.goto("entry-form", query={"session_id": 999999},
                   wait_for_bridge=False)
    assert poll(wimi_page, FORM_RENDERED), "the entry form markup never rendered"

    # ---- Assert -----------------------------------------------------------
    # The page redirects to the dashboard 1.5 s later, so poll rather than
    # settle: the release happens immediately, well before the redirect.
    assert poll(wimi_page,
                "(() => { const p = document.querySelector('.entry-page');"
                " return !!p && !p.hasAttribute('inert'); })()",
                timeout_ms=10000), (
        "the form stayed inert after init failed to find its session — the "
        "`finally` in initializeEntryPage() is not releasing it, which leaves "
        "a permanently dead page")


# ---------------------------------------------------------------------------
# Why each assertion catches the regression
# ---------------------------------------------------------------------------
#
# * The "during" assertions fail against master, where the form ships with
#   no `inert` attribute: the click lands in the textarea, `insertText`
#   fills it, the marker listener fires, and the reflection iframe takes
#   the text. Confirmed by running these against master's
#   `question_entry.html` / `question_entry.js`.
# * The "after" assertions fail against a fix that forgets to remove the
#   attribute, or removes it from only one code path — dropping the
#   `finally` in `initializeEntryPage()` leaves the form permanently inert
#   whenever init throws.
# * `test_rich_text_...` would be vacuous if it typed before the iframe
#   existed; it polls for "editable AND still inert" first, so it is
#   asserting about the exact window that was measured to lose text.
# * `test_the_draft_loading_path_...` is the only one that exercises
#   `populateFormWithEntry()`. Without it a fix could gate the reset path
#   alone and still pass everything else here.
