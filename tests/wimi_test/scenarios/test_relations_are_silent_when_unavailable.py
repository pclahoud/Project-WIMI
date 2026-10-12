"""Regression: the entry form says NOTHING about relation suggestions it cannot
make (#60, owner's decision #5179/#5183).

    Settings states that relation extraction is unavailable on this machine,
    and why. **The entry form shows nothing.** No disabled button, no
    "unavailable" notice, no tooltip, no placeholder where the proposals
    would have been. Manual creation (#14) is the fallback, and it is not
    labelled as a fallback — it is simply how relations are made.

That follows two of #14's own decisions rather than inventing a rule: decision
10, *"a student who never touches this must never notice it exists"*, and
decision 11, *"degrade to absent, not to an empty card"*.

Why this scenario can run here, and the full flow cannot
--------------------------------------------------------
This machine's `.venv` has no `torch`, `transformers`, `gliner2` or `peft`, so
`getRelationExtractionStatus` reports `dev_runtime_missing` — which is exactly
the state this test needs. **The absence of the runtime is the fixture.**

The opposite scenario — press the button, get proposals, confirm one — needs
the 845 MB model and a venv carrying the runtime, so it is not written here.
What stands in for it: `tests/app/test_bridge_relation_proposals.py` drives
the real job runner over a fake runtime, and
`tests/test_relation_proposals_markup.py` pins the wiring and the copy.

The trap this is written around
-------------------------------
Asserting an absence is easy to do vacuously. A test that merely checked the
mount was empty would pass against a page that had never loaded
`relation_proposals.js` at all, or where the module threw on its first line,
or where the mount id was misspelled — none of which is the decision being
tested. So this asserts the **positive control first**: the module is loaded,
its attach function ran, and the controller exists. Only then is the empty
mount a finding rather than a tautology.

That is #121's lesson applied to a feature rather than to a gate: an assertion
that a page does not say something passes whether or not the page could ever
have said it.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.page_gate import wait_for_release
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

STATE = """
(() => {
  const mount = document.querySelector('[data-testid="entry-form-relations-mount"]');
  return JSON.stringify({
    mount_present: !!mount,
    mount_text: mount ? mount.textContent.trim() : null,
    buttons: mount ? mount.querySelectorAll('button').length : -1,
    controls: mount ? mount.querySelectorAll('button, select, textarea, input').length : -1,
    module_loaded: typeof window.attachRelationProposals === 'function',
    // `const EntryState` is a SCRIPT-SCOPE binding, so `window.EntryState`
    // is undefined and the bare name is what resolves -- already written
    // down in test_entry_form_flat_layout.py. Reading it the other way
    // made this control report a false negative about a feature that was
    // working, which is the right direction for a control to fail in.
    controller_attached: typeof EntryState !== 'undefined'
      && !!EntryState.relationProposals,
  });
})()
"""


def _seed(db):
    """A session the entry form can open.

    Through ``create_review_session`` and keyed as ``session_id``, which is
    what every other entry-form scenario does -- my first version used raw
    SQL and a ``session`` query key, and the page never finished
    initialising. The positive control in the first test is what said so,
    rather than the silence assertion passing anyway.

    No explanation is seeded: this scenario is about a machine that cannot
    extract, where silence is required whatever the form holds.
    """
    exam = db.create_exam_context(
        exam_name='Silence Exam',
        exam_description='#60 — the entry form says nothing it cannot deliver',
    )
    db.create_subject_node(
        exam_context=exam.exam_name, name='SI Hypertension', level_type='Topic')
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=3,
        total_incorrect=1,
        session_name='Silence session',
        date_encountered=date.today(),
    )
    db.conn.commit()
    return session.id


@pytest.mark.slow
@pytest.mark.regression
def test_the_entry_form_shows_nothing_when_extraction_cannot_run(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    session_id = _seed(wimi_session.user.db)

    wimi_page.goto('entry-form', query={'session_id': session_id})
    wait_for_release(wimi_page)

    state = json.loads(wimi_page.eval_js(STATE))

    # --- the positive control, first. Without it the assertions below pass
    # --- against a page that never loaded the module at all.
    assert state['module_loaded'], (
        'relation_proposals.js did not load, so the silence below would be '
        'the absence of the feature rather than the decision being kept')
    assert state['mount_present'], (
        'the mount is missing, so nothing could have rendered there whatever '
        'the availability was')
    assert state['controller_attached'], (
        'attachRelationProposals never ran, so this asserts nothing about '
        'what it decides to draw')

    # --- and now the decision itself.
    assert state['controls'] == 0, (
        f"the entry form offers {state['controls']} relation control(s) on a "
        f"machine that cannot extract. The owner's decision is silence here: "
        f"no disabled button, no notice, no placeholder. Settings carries the "
        f"one line that says why (#5179)")
    assert not state['mount_text'], (
        f'the entry form says {state["mount_text"]!r} about a feature it '
        f'cannot offer. Degrade to absent, not to an empty card (#14 '
        f'decision 11)')


@pytest.mark.slow
@pytest.mark.regression
def test_the_rest_of_the_form_is_unaffected(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    """The other half of "degrade to absent": nothing else may degrade with it.

    A module that threw during attach could leave the page silent about
    relations *and* half-initialised — and the first test would still pass.
    So this checks the things that come after `initRelationProposals()` in the
    init chain are there: the editors mounted, and the footer buttons bound.
    """
    session_id = _seed(wimi_session.user.db)

    wimi_page.goto('entry-form', query={'session_id': session_id})
    wait_for_release(wimi_page)

    state = json.loads(wimi_page.eval_js("""
    (() => JSON.stringify({
      explanation_editor: !!EntryState.explanationEditor,
      reflection_editor: !!EntryState.reflectionEditor,
      dictation: (EntryState.dictation || []).length,
      save_next: !!document.querySelector('#btn-save-next'),
      loading: !!EntryState.isLoading,
    }))()
    """))

    assert state['explanation_editor'] and state['reflection_editor'], (
        'an editor is missing, so initRichTextEditors did not finish -- '
        'which is where attachRelationProposals is called from')
    assert state['save_next'], 'the footer never bound'
    assert state['loading'] is False, (
        'the form is still loading, so the init chain did not complete')
