"""Regression: the Find-related-topics hint names the blocker in force (#483).

The button is greyed unless **both** halves of

    var canRun = !!context.entry_id && !!context.has_explanation;

hold, and the sentence beside it was written **once, at attach time**, as
``describeNotStarted('no_explanation')``. So it always read *"Write the
explanation first — that is what WIMI reads."*

``entry_id`` is ``null`` until the entry's first save, and the first save is
normally the thirty-second autosave. So the ordinary case is: open a fresh
entry slot, type an explanation, look at the button. It is grey, and the reason
given is that you have not written the explanation you are looking at.

#398 moved this reason out of a ``title`` and into visible text precisely so a
keyboard or touch user could read it. Having made it visible, it was visibly
wrong in the commoner of its two cases.

**No torch on this machine, so the relations runtime cannot load.** This drives
the module itself: `api.getRelationExtractionStatus` is faked to `ready` from
the page — the same technique
``test_relation_proposals_keep_focus_and_announce.py`` uses — and the module is
re-attached to a scratch mount with a `getContext` the test controls. That is
the right level anyway: #483 is about which sentence the module chooses, not
about how the host computes the context it is handed.

**The third case is the control.** With both halves satisfied the hint must be
absent entirely. Without it, a fix that simply always said "Save this entry
first" would pass the other two.
"""

from __future__ import annotations

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

#: Fake the availability probe and re-attach the module with a context the
#: test owns. `attachRelationProposals` closes over `getContext`, so the
#: context has to be swappable from outside rather than replaced afterwards.
_ATTACH = """
(() => {
  window.api.getRelationExtractionStatus = () => Promise.resolve(
      {ready: true, state: 'ready'});
  window.__p483ctx = {entry_id: null, has_explanation: false};
  const mount = document.createElement('div');
  mount.id = 'p483-mount';
  document.body.appendChild(mount);
  window.__p483 = window.attachRelationProposals({
      mountEl: mount,
      getContext: () => window.__p483ctx,
      notify: () => {},
  });
  // eval_js does not await, so the caller polls for the bar instead of
  // reading a Promise back as {}.
  window.__p483.refresh();
  return true;
})()
"""

_READ = """
(() => {
  const el = document.querySelector('#p483-mount [data-testid="entry-form-relations-hint"]');
  const btn = document.querySelector('#p483-mount [data-testid="entry-form-relations-find"]');
  return JSON.stringify({
      hint: el ? el.textContent : null,
      inTree: !!(el && el.parentNode),
      disabled: btn ? btn.disabled : null,
  });
})()
"""


def _state(page: WimiPage, *, entry_id, has_explanation):
    import json
    page.eval_js(
        f"window.__p483ctx = {{entry_id: {entry_id if entry_id is not None else 'null'}, "
        f"has_explanation: {str(bool(has_explanation)).lower()}}}; "
        "window.__p483.update(); true")
    return json.loads(page.eval_js(_READ))


@pytest.fixture
def module(wimi_session: WimiTestSession, wimi_page: WimiPage):
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Hint Exam", exam_description="#483")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name="hint")
    db.conn.commit()

    wimi_page.goto("entry-form", query={"session_id": session.id})
    assert poll(wimi_page, "EntryState && EntryState.isLoading === false"), (
        "the entry form never got ready")
    assert wimi_page.eval_js(_ATTACH) is True, "the attach script did not run"
    assert poll(
        wimi_page,
        "!!document.querySelector('#p483-mount "
        "[data-testid=\"entry-form-relations-find\"]')",
    ), "the module never rendered its bar, so `ready` never arrived"
    return wimi_page


@pytest.mark.slow
@pytest.mark.regression
def test_an_unsaved_entry_is_told_to_save_not_to_write(module):
    """The headline, and the case that was wrong.

    An explanation is written and the entry has not been saved yet, which is
    every fresh entry for its first thirty seconds.
    """
    state = _state(module, entry_id=None, has_explanation=True)

    assert state["inTree"], "the reason was not drawn at all"
    assert state["disabled"] is True, (
        "the precondition is a greyed button; if it is live this asserts nothing")
    assert "Save this entry first" in state["hint"], state["hint"]
    assert "Write the explanation first" not in state["hint"], (
        f"told to write an explanation that is already written: {state['hint']!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_an_empty_explanation_still_says_to_write_one(module):
    """The other half, unchanged, and the reason this is not a blind swap."""
    state = _state(module, entry_id=7, has_explanation=False)

    assert state["inTree"], "the reason was not drawn at all"
    assert "Write the explanation first" in state["hint"], state["hint"]
    assert "Save this entry first" not in state["hint"], state["hint"]


@pytest.mark.slow
@pytest.mark.regression
def test_with_both_satisfied_there_is_no_reason_at_all(module):
    """The control.

    Without this, a fix that always said "Save this entry first" would pass
    the first test and leave the second's sentence reachable only by accident.
    The hint is *removed from the tree* rather than emptied (#134/#136/#141 --
    `:empty` stops re-invalidating on QtWebEngine 6.10 -- and an emptied node
    stays in the accessibility tree announcing nothing).
    """
    state = _state(module, entry_id=7, has_explanation=True)

    assert state["disabled"] is False, "the button should be live here"
    assert not state["inTree"], (
        f"a reason is drawn beside a working button: {state['hint']!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_the_explanation_wins_when_both_are_missing(module):
    """Both halves false. The student can act on the explanation in place.

    Asserted because it is a choice rather than a fallout: naming the save
    first would send them to wait for an autosave when there is nothing yet
    for it to save.
    """
    state = _state(module, entry_id=None, has_explanation=False)

    assert "Write the explanation first" in state["hint"], state["hint"]
