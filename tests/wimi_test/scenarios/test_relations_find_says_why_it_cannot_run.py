"""Regression: the greyed Find button explains itself in text a student can read (#398).

`renderBar` disables **Find related topics** until the explanation has prose,
and the comment above that line argues the case for it correctly:

    The one case where a disabled control is better than silence: the feature
    IS available, and the student is a keystroke away from being able to use
    it. Saying nothing here would read as the button having vanished.

The explanation was a `title`, and a `title` opens on hover. A `disabled`
button **cannot take focus**, so a keyboard user can never surface it; a touch
screen has no hover at all; and `title` exposure to screen readers is
inconsistent where the element already has a name from its text. The student
most likely to need the sentence is the one who cannot get it.

What #398 itself reasoned from was something else, and it is **false on this
engine** — recorded here because the issue flagged it as the one claim wanting
confirmation in the app, and because a wrong mechanism in a fix's comments is
how the fix gets undone later. The issue said Chromium dispatches no mouse
events to a disabled form control, so the tooltip could never open for anybody.
Measured on QtWebEngine 6.9.2 / Chromium 130, offscreen, with a disabled
``<button>`` and a disabled ``<input>`` inserted on this very page:

    disabled <button>   pointerover, mouseover, mouseenter, mousemove; :hover matches
    disabled <input>    pointerover, mouseover, mouseenter, mousemove; :hover matches
    aria-disabled       same, and focusable
    enabled <button>    same (the control)

So a mouse user probably *did* see that tooltip. The focus half is the one that
holds, and it was measured the same way: ``el.focus()`` on a disabled button
leaves ``document.activeElement`` elsewhere and ``:focus`` unmatched, while the
same button enabled takes focus — which is what
``test_the_greyed_button_cannot_be_reached_to_be_hovered`` asserts. Programmatic
focus is the *weaker* instrument than a real Tab, and the inference runs the
safe way: Tab only moves focus to focusable elements, so something that cannot
be focused at all cannot be tabbed to either.

The fix is `.relprop-hint`: the same sentence `describeNotStarted` already had
for the state, drawn beside the bar and removed when the button becomes
pressable. It lives in the bar's own child rather than in the proposal list
because `update()` is bound to `renderBar` alone — the cards hold a textarea a
student may be part way through, so the list is not rebuilt on a keystroke, and
a sentence that has to follow the explanation keystroke by keystroke cannot
live there.

Why a browser
-------------
* The hint must be **visible and in the accessibility tree**, and those are
  two different instruments: `innerText` for "is the page painting it",
  `Accessibility.getFullAXTree` for "can it be heard". #121's lesson — the AX
  tree cannot see a painted false state, and a DOM read cannot see an exposed
  one.
* It must **go away again**. A permanent line under the explanation on every
  entry would be its own defect, and no source check can tell the two apart.

The availability status is FAKED: the relations runtime is not in this `.venv`,
so the module would render nothing at all (#5179, and
`test_relations_are_silent_when_unavailable.py` guards that). Everything after
the fake is the shipped code path.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.page_gate import (
    ax_mentions,
    ax_snapshot,
    enable_accessibility,
    wait_for_release,
)
from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

HINT = '[data-testid="entry-form-relations-hint"]'
FIND = '[data-testid="entry-form-relations-find"]'

SENTENCE = 'Write the explanation first'

#: `ready` without the runtime. The module reads one boolean off this.
FAKE_READY = """
(() => {
  window.api.getRelationExtractionStatus = () =>
      Promise.resolve({ready: true, state: 'ready'});
  window.__relReady = false;
  EntryState.relationProposals.refresh()
      .then(() => { window.__relReady = true; });
  return true;
})()
"""

STATE = """
(() => {
  const hint = document.querySelector(%s);
  const find = document.querySelector(%s);
  return JSON.stringify({
    find_present: !!find,
    find_disabled: find ? find.disabled : null,
    find_title: find ? find.getAttribute('title') : null,
    find_describedby: find ? find.getAttribute('aria-describedby') : null,
    hint_present: !!hint,
    // innerText, not textContent: it excludes display:none subtrees, which
    // is the distinction between "rendered" and "in the DOM" (#121).
    hint_text: hint ? hint.innerText.trim() : null,
    hint_height: hint ? Math.round(hint.getBoundingClientRect().height) : 0,
    hint_id: hint ? hint.id : null,
  });
})()
""" % (json.dumps(HINT), json.dumps(FIND))

#: Can the button hold focus? `el.focus()` and read it back, then blur so the
#: probe leaves the page as it found it.
TRY_FOCUS = """
(() => {
  const find = document.querySelector(%s);
  find.focus();
  const held = document.activeElement === find;
  const styled = find.matches(':focus');
  if (held) find.blur();
  return JSON.stringify({disabled: find.disabled, held: held,
                         styled: styled, tabindex: find.tabIndex});
})()
""" % json.dumps(FIND)

WRITE_EXPLANATION = """
(() => {
  // setContent() does not fire the editor's change event, so markDirty() is
  // called explicitly -- which is also the real path by which the host
  // re-parks this button (`EntryState.relationProposals?.update()`).
  EntryState.explanationEditor.setContent(
      '<p>Hypertension is a risk factor for stroke.</p>');
  markDirty();
  validateForm();
  return true;
})()
"""


def _seed(db) -> tuple[int, int]:
    """A saved entry with **no** explanation. Returns (session id, entry id).

    The entry id is what makes this the state the hint is for rather than the
    one where the whole feature is absent: `canRun` wants an entry id *and*
    prose, so a saved entry with an empty explanation leaves exactly one of
    the two missing, and it is the one the sentence names.
    """
    exam = db.create_exam_context(
        exam_name='Hint Exam',
        exam_description='#398 -- the greyed button says why')
    db.create_subject_node(
        exam_context=exam.exam_name, name='Hypertension', level_type='Topic')
    db.create_subject_node(
        exam_context=exam.exam_name, name='Stroke', level_type='Topic')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='Hint session', date_encountered=date.today())
    entry = db.create_question_entry(session.id, 'A', 'B')
    db.conn.commit()
    return session.id, entry.id


def _open(page: WimiPage, db) -> None:
    session_id, entry_id = _seed(db)
    page.goto('entry-form', query={'session_id': session_id,
                                   'entry': entry_id})
    wait_for_release(page)
    assert poll(page, "(() => typeof EntryState !== 'undefined'"
                      " && !!EntryState.relationProposals"
                      " && !!EntryState.currentEntry)()"), (
        'the entry form never attached relation proposals')
    assert page.eval_js(FAKE_READY)
    assert poll(page, 'window.__relReady === true')
    assert poll(page, "(() => !!document.querySelector(%s))()"
                % json.dumps(FIND)), (
        'the Find button never rendered, so the faked status did not take')


@pytest.mark.slow
@pytest.mark.regression
def test_the_reason_is_on_the_page_and_then_goes_away(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    page = wimi_page
    _open(page, wimi_session.user.db)
    enable_accessibility(page)

    before = json.loads(page.eval_js(STATE))
    assert before['find_disabled'] is True, (
        'the Find button is pressable on an entry with no explanation, so '
        'this test is not in the state it is about')
    assert before['find_title'] is None, (
        f'the Find button carries title={before["find_title"]!r}. A disabled '
        f'control cannot be focused, so a keyboard user can never open that '
        f'tooltip and a touch user has no hover to open it with (#398)')

    assert before['hint_present'], (
        'the greyed button offers no reason at all. Silence here reads as the '
        'button having vanished, which renderBar\'s own comment rejects')
    assert SENTENCE in before['hint_text'], (
        f'the hint reads {before["hint_text"]!r}, which does not name the '
        f'next step. It is meant to be describeNotStarted\'s own sentence')
    assert before['hint_height'] > 0, (
        f'the hint is in the DOM with zero height ({before["hint_height"]}px), '
        f'so nothing is painted -- the #134/#136/#141 shape')
    assert before['find_describedby'] == before['hint_id'], (
        f'aria-describedby is {before["find_describedby"]!r} and the hint id '
        f'is {before["hint_id"]!r}; a reader reaching the disabled button in '
        f'browse mode gets no description')

    # The second instrument. `innerText` above says the page paints it; this
    # says a reader is handed it. Neither substitutes for the other (#121).
    assert ax_mentions(ax_snapshot(page), SENTENCE), (
        'the reason is painted but absent from the accessibility tree')

    # --- and it must not be permanent. One line under the explanation on
    # --- every entry forever is its own defect.
    assert page.eval_js(WRITE_EXPLANATION)
    assert poll(page, "(() => { const b = document.querySelector(%s);"
                      " return !!b && !b.disabled; })()" % json.dumps(FIND)), (
        'writing the explanation never made the button pressable')

    after = json.loads(page.eval_js(STATE))
    assert not after['hint_present'], (
        f'the hint is still on the page ({after["hint_text"]!r}) now that the '
        f'button works. It is removed from the tree rather than emptied, so '
        f'it needs no `:empty` rule to collapse')
    assert after['find_describedby'] is None, (
        'the button still points aria-describedby at a hint that is gone')


@pytest.mark.slow
@pytest.mark.regression
def test_the_greyed_button_cannot_be_reached_to_be_hovered(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    """Why a `title` could not have served, measured on the shipped button.

    A tooltip opens on hover. A keyboard user hovers nothing, so for them the
    only route to a `title` would be focusing the control — and a `disabled`
    button takes no focus. Same element, same page, two states, so nothing but
    `disabled` differs between the arms.

    This is the claim the fix rests on. #398's own stated mechanism (no mouse
    events at all) is false here and is recorded in the module docstring
    instead of asserted, because pinning an engine quirk this fix does not
    depend on would only make a future Qt upgrade fail for nothing.
    """
    page = wimi_page
    _open(page, wimi_session.user.db)

    while_disabled = json.loads(page.eval_js(TRY_FOCUS))
    assert while_disabled['disabled'] is True, (
        f'the Find button is not disabled ({while_disabled}), so this test is '
        f'not in the state it is about')
    assert while_disabled['held'] is False and while_disabled['styled'] is False, (
        f'the disabled Find button took focus ({while_disabled}). If it can be '
        f'focused it can be tabbed to, and the keyboard argument for visible '
        f'text weakens -- re-read #398 before changing anything, and do not '
        f'simply put the `title` back: touch and screen-reader exposure are '
        f'unaffected by this')

    # The control: the same button, enabled, does take focus. Without it
    # "cannot be focused" would also be true of an element that is not there.
    assert page.eval_js(WRITE_EXPLANATION)
    assert poll(page, "(() => { const b = document.querySelector(%s);"
                      " return !!b && !b.disabled; })()" % json.dumps(FIND))
    while_enabled = json.loads(page.eval_js(TRY_FOCUS))
    assert while_enabled['held'] is True, (
        f'the ENABLED button does not take focus either ({while_enabled}), so '
        f'the assertion above is about the instrument and not about `disabled`')
